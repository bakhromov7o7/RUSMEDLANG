import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso
from app.core import config
from app.core.files import save_upload
from app.core.security import get_current_user, is_staff
from app.database import get_db
from app.models import ChatMessage, GroupChatMessage, NotificationLog, User, UserRole, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)

# "Yozmoqda..." signallari xotirada saqlanadi (bitta instans uchun yetarli).
_typing_signals: dict[tuple[int, int], float] = {}
_TYPING_TTL = 6.0
_TYPING_MAX_ENTRIES = 5000


def _prune_typing(now: float) -> None:
    """Eskirgan yozuvlarni tozalaydi — ilgari lug'at cheksiz o'sardi."""
    if len(_typing_signals) < _TYPING_MAX_ENTRIES:
        return
    for key, stamp in list(_typing_signals.items()):
        if now - stamp >= _TYPING_TTL:
            _typing_signals.pop(key, None)


def _touch_last_active(user: User) -> None:
    user.last_active = utcnow()


class MessageSendRequest(BaseModel):
    sender_id: Optional[int] = None  # e'tiborsiz — tokendan olinadi
    recipient_id: int = Field(..., gt=0)
    message_text: str = Field(..., min_length=1, max_length=4000)


class TypingRequest(BaseModel):
    sender_id: Optional[int] = None
    recipient_id: int = Field(..., gt=0)


def _message_public(msg: ChatMessage) -> dict:
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "recipient_id": msg.recipient_id,
        "message_text": msg.message_text,
        "image_path": msg.image_path,
        "is_read": msg.is_read,
        "created_at": iso(msg.created_at),
    }


async def _load_peer(db: AsyncSession, current_user: User, peer_id: int) -> User:
    """Suhbatdoshni oladi va rol qoidasiga muvofiqligini tekshiradi."""
    peer = (await db.execute(select(User).where(User.id == peer_id))).scalar_one_or_none()
    if not peer:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    if peer.id == current_user.id:
        raise HTTPException(status_code=400, detail="O'zingizga xabar yubora olmaysiz")

    # Talaba faqat ustozlar bilan, ustoz faqat talabalar bilan yozishadi.
    if current_user.role == UserRole.student and peer.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar bir-biriga yozisha olmaydi")
    return peer


@router.get("/contacts")
async def get_contacts(
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    me = current_user.id

    if current_user.role == UserRole.student:
        stmt = select(User).where(
            User.role.in_([UserRole.employee, UserRole.superadmin]),
            User.is_active.is_(True),
        )
    else:
        stmt = select(User).where(User.role == UserRole.student, User.is_active.is_(True))

    contacts = (await db.execute(stmt.order_by(User.full_name))).scalars().all()
    contact_ids = [c.id for c in contacts]
    if not contact_ids:
        _touch_last_active(current_user)
        await db.commit()
        return []

    # Har bir kontakt uchun oxirgi xabar — 2 ta so'rovda (ilgari kontakt boshiga
    # 2 tadan so'rov ketardi).
    peer_expr = case(
        (ChatMessage.sender_id == me, ChatMessage.recipient_id),
        else_=ChatMessage.sender_id,
    ).label("peer_id")

    pair_filter = or_(
        and_(ChatMessage.sender_id == me, ChatMessage.recipient_id.in_(contact_ids)),
        and_(ChatMessage.recipient_id == me, ChatMessage.sender_id.in_(contact_ids)),
    )

    last_ids = [
        row[1]
        for row in (
            await db.execute(
                select(peer_expr, func.max(ChatMessage.id))
                .where(pair_filter)
                .group_by(peer_expr)
            )
        ).all()
    ]

    last_at_map: dict[int, object] = {}
    texts: dict[int, str] = {}
    if last_ids:
        for msg in (
            await db.execute(select(ChatMessage).where(ChatMessage.id.in_(last_ids)))
        ).scalars().all():
            peer_id = msg.recipient_id if msg.sender_id == me else msg.sender_id
            last_at_map[peer_id] = msg.created_at
            texts[peer_id] = msg.message_text or ("📷 Rasm" if msg.image_path else "")

    unread_map = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(ChatMessage.sender_id, func.count(ChatMessage.id))
                .where(
                    ChatMessage.recipient_id == me,
                    ChatMessage.sender_id.in_(contact_ids),
                    ChatMessage.is_read.is_(False),
                )
                .group_by(ChatMessage.sender_id)
            )
        ).all()
    }

    result = [
        {
            "id": c.id,
            "full_name": c.full_name,
            "username": c.username,
            "role": c.role.value,
            "student_group": c.student_group or "",
            "unread_count": unread_map.get(c.id, 0),
            "last_message": texts.get(c.id),
            "last_message_time": iso(last_at_map.get(c.id)),
            "last_active": iso(c.last_active),
        }
        for c in contacts
    ]
    result.sort(key=lambda x: (x["last_message_time"] or "", x["full_name"]), reverse=True)

    _touch_last_active(current_user)
    await db.commit()
    return result


@router.get("/messages")
async def get_messages(
    other_user_id: int,
    user_id: Optional[int] = None,  # e'tiborsiz — tokendan olinadi
    limit: int = Query(default=config.CHAT_PAGE_SIZE, ge=1, le=500),
    before_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    me = current_user.id
    await _load_peer(db, current_user, other_user_id)

    pair_filter = or_(
        and_(ChatMessage.sender_id == me, ChatMessage.recipient_id == other_user_id),
        and_(ChatMessage.sender_id == other_user_id, ChatMessage.recipient_id == me),
    )

    # Oxirgi `limit` ta xabarni olamiz (eski tarix bir marta yuklanmaydi).
    stmt = select(ChatMessage).where(pair_filter)
    if before_id:
        stmt = stmt.where(ChatMessage.id < before_id)
    page = (
        await db.execute(stmt.order_by(ChatMessage.id.desc()).limit(limit))
    ).scalars().all()
    messages = list(reversed(page))

    # Kiruvchi xabarlarni o'qilgan deb belgilaymiz — bitta UPDATE bilan.
    await db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.sender_id == other_user_id,
            ChatMessage.recipient_id == me,
            ChatMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    _touch_last_active(current_user)
    await db.commit()

    now = time.time()
    stamp = _typing_signals.get((other_user_id, me))
    other_typing = stamp is not None and (now - stamp) < _TYPING_TTL

    return {
        "other_typing": other_typing,
        "has_more": len(page) == limit,
        "messages": [_message_public(m) for m in messages],
    }


@router.post("/send")
async def send_message(
    req: MessageSendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    text_body = req.message_text.strip()
    if not text_body:
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas")

    await _load_peer(db, current_user, req.recipient_id)

    msg = ChatMessage(
        sender_id=current_user.id,
        recipient_id=req.recipient_id,
        message_text=text_body,
        is_read=False,
    )
    db.add(msg)
    db.add(NotificationLog(
        user_id=req.recipient_id,
        event_type="new_message",
        payload={
            "sender_id": current_user.id,
            "sender_name": current_user.full_name,
            "preview": text_body[:80],
        },
    ))

    _touch_last_active(current_user)
    _typing_signals.pop((current_user.id, req.recipient_id), None)
    await db.commit()
    await db.refresh(msg)

    return {"status": "success", "message": _message_public(msg)}


@router.post("/typing")
async def set_typing(req: TypingRequest, current_user: User = Depends(get_current_user)):
    now = time.time()
    _prune_typing(now)
    _typing_signals[(current_user.id, req.recipient_id)] = now
    return {"status": "ok"}


@router.post("/send-image")
async def send_image(
    recipient_id: int = Form(...),
    sender_id: Optional[int] = Form(None),  # e'tiborsiz — tokendan olinadi
    message_text: str = Form(""),
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _load_peer(db, current_user, recipient_id)

    image_url = await save_upload(image, prefix="chat_")

    msg = ChatMessage(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        message_text=(message_text or "").strip(),
        image_path=image_url,
        is_read=False,
    )
    db.add(msg)
    db.add(NotificationLog(
        user_id=recipient_id,
        event_type="new_message",
        payload={
            "sender_id": current_user.id,
            "sender_name": current_user.full_name,
            "preview": "📷 Rasm",
        },
    ))

    _touch_last_active(current_user)
    await db.commit()
    await db.refresh(msg)

    return {"status": "success", "message": _message_public(msg)}


# ---------------------------------------------------------------------------
# Guruh chati
# ---------------------------------------------------------------------------

def _ensure_group_access(current_user: User, group_name: str) -> None:
    if is_staff(current_user):
        return
    if (current_user.student_group or "") != group_name:
        raise HTTPException(status_code=403, detail="Siz bu guruh a'zosi emassiz")


@router.get("/group/messages")
async def get_group_messages(
    group_name: str,
    limit: int = Query(default=config.CHAT_PAGE_SIZE, ge=1, le=500),
    before_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_group_access(current_user, group_name)

    stmt = select(GroupChatMessage).where(GroupChatMessage.group_name == group_name)
    if before_id:
        stmt = stmt.where(GroupChatMessage.id < before_id)
    page = (
        await db.execute(stmt.order_by(GroupChatMessage.id.desc()).limit(limit))
    ).scalars().all()
    messages = list(reversed(page))
    if not messages:
        return []

    # Yuboruvchilar bitta so'rovda (ilgari har bir xabar uchun alohida edi).
    senders = {
        row[0]: (row[1], row[2])
        for row in (
            await db.execute(
                select(User.id, User.full_name, User.role).where(
                    User.id.in_({m.sender_id for m in messages})
                )
            )
        ).all()
    }

    return [
        {
            "id": m.id,
            "group_name": m.group_name,
            "sender_id": m.sender_id,
            "sender_name": senders.get(m.sender_id, ("Noma'lum", None))[0],
            "sender_role": (
                senders[m.sender_id][1].value if m.sender_id in senders else "student"
            ),
            "message_text": m.message_text,
            "image_path": m.image_path,
            "created_at": iso(m.created_at),
        }
        for m in messages
    ]


@router.post("/group/messages")
async def send_group_message(
    group_name: str = Form(...),
    sender_id: Optional[int] = Form(None),  # e'tiborsiz — tokendan olinadi
    message_text: str = Form(""),
    image: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_group_access(current_user, group_name)

    body = (message_text or "").strip()
    image_url = None
    if image and image.filename:
        image_url = await save_upload(image, prefix="group_")
    if not body and not image_url:
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas")

    msg = GroupChatMessage(
        group_name=group_name,
        sender_id=current_user.id,
        message_text=body,
        image_path=image_url,
    )
    db.add(msg)

    members = (
        await db.execute(
            select(User.id).where(
                User.student_group == group_name,
                User.id != current_user.id,
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    for member_id in members:
        db.add(NotificationLog(
            user_id=member_id,
            event_type="group_message",
            payload={
                "group_name": group_name,
                "sender_id": current_user.id,
                "sender_name": current_user.full_name,
                "preview": "📷 Rasm" if image_url else body[:50],
            },
        ))

    _touch_last_active(current_user)
    await db.commit()
    await db.refresh(msg)

    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "group_name": msg.group_name,
            "sender_id": msg.sender_id,
            "sender_name": current_user.full_name,
            "sender_role": current_user.role.value,
            "message_text": msg.message_text,
            "image_path": msg.image_path,
            "created_at": iso(msg.created_at),
        },
    }
