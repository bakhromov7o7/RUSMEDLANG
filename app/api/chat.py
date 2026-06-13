import os
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func
from app.database import get_db
from app.models import ChatMessage, User, UserRole, NotificationLog
from pydantic import BaseModel, Field

router = APIRouter(redirect_slashes=True)

UPLOAD_DIR = "uploads"

# In-memory "typing" signals: (sender_id, recipient_id) -> last typing time.
# Good enough for a single-instance deployment; clears on restart.
_typing_signals: dict = {}
_TYPING_TTL = 6.0  # seconds


async def _touch_last_active(db: AsyncSession, user_id: int):
    """Best-effort update of a user's last_active timestamp."""
    try:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user:
            user.last_active = datetime.utcnow()
    except Exception:
        pass


class MessageSendRequest(BaseModel):
    sender_id: int = Field(..., gt=0)
    recipient_id: int = Field(..., gt=0)
    message_text: str = Field(..., min_length=1, max_length=4000)


class TypingRequest(BaseModel):
    sender_id: int = Field(..., gt=0)
    recipient_id: int = Field(..., gt=0)

@router.get("/contacts")
async def get_contacts(user_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Fetch current user
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    contacts = []
    
    # 2. Get potential contacts based on roles
    if user.role == UserRole.student:
        # Students can chat with any teacher/employee
        stmt = select(User).where(User.role.in_([UserRole.employee, UserRole.superadmin]))
    else:
        # Teachers can chat with any student
        stmt = select(User).where(User.role == UserRole.student)
        
    res_contacts = await db.execute(stmt.order_by(User.full_name))
    potential_contacts = res_contacts.scalars().all()
    
    for c in potential_contacts:
        # Query last message between user and contact c
        msg_stmt = select(ChatMessage).where(
            or_(
                and_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == c.id),
                and_(ChatMessage.sender_id == c.id, ChatMessage.recipient_id == user_id)
            )
        ).order_by(ChatMessage.created_at.desc()).limit(1)
        
        msg_res = await db.execute(msg_stmt)
        last_msg = msg_res.scalar_one_or_none()
        
        # Query unread count from c to user
        unread_stmt = select(func.count(ChatMessage.id)).where(
            and_(
                ChatMessage.sender_id == c.id,
                ChatMessage.recipient_id == user_id,
                ChatMessage.is_read == False
            )
        )
        unread_res = await db.execute(unread_stmt)
        unread_count = unread_res.scalar() or 0
        
        contacts.append({
            "id": c.id,
            "full_name": c.full_name,
            "username": c.username,
            "role": c.role.value,
            "student_group": c.student_group or "",
            "unread_count": unread_count,
            "last_message": last_msg.message_text if last_msg else None,
            "last_message_time": last_msg.created_at.isoformat() if last_msg else None,
            "last_active": c.last_active.isoformat() if c.last_active else None,
        })

    # Sort contacts: those with messages first, then alphabetically
    contacts.sort(key=lambda x: (x["last_message_time"] or "", x["full_name"]), reverse=True)

    await _touch_last_active(db, user_id)
    await db.commit()
    return contacts

@router.get("/messages")
async def get_messages(user_id: int, other_user_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Fetch message history
    stmt = select(ChatMessage).where(
        or_(
            and_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == other_user_id),
            and_(ChatMessage.sender_id == other_user_id, ChatMessage.recipient_id == user_id)
        )
    ).order_by(ChatMessage.created_at.asc())
    
    res = await db.execute(stmt)
    messages = res.scalars().all()
    
    # 2. Mark incoming messages as read
    update_stmt = select(ChatMessage).where(
        and_(
            ChatMessage.sender_id == other_user_id,
            ChatMessage.recipient_id == user_id,
            ChatMessage.is_read == False
        )
    )
    to_update_res = await db.execute(update_stmt)
    to_update = to_update_res.scalars().all()
    for m in to_update:
        m.is_read = True
        
    # Touch presence and persist read-state together.
    await _touch_last_active(db, user_id)
    await db.commit()

    key = (other_user_id, user_id)
    ts = _typing_signals.get(key)
    other_typing = ts is not None and (time.time() - ts) < _TYPING_TTL

    return {
        "other_typing": other_typing,
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "recipient_id": m.recipient_id,
                "message_text": m.message_text,
                "image_path": m.image_path,
                "is_read": m.is_read,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }

@router.post("/send")
async def send_message(req: MessageSendRequest, db: AsyncSession = Depends(get_db)):
    text_body = req.message_text.strip()
    if not text_body:
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas")
    if req.sender_id == req.recipient_id:
        raise HTTPException(status_code=400, detail="O'zingizga xabar yubora olmaysiz")

    # Verify sender and recipient exist
    sender = (await db.execute(select(User).where(User.id == req.sender_id))).scalar_one_or_none()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")

    recipient = (await db.execute(select(User).where(User.id == req.recipient_id))).scalar_one_or_none()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    msg = ChatMessage(
        sender_id=req.sender_id,
        recipient_id=req.recipient_id,
        message_text=text_body,
        is_read=False
    )
    db.add(msg)

    # Notify the recipient of the new message.
    try:
        db.add(NotificationLog(
            user_id=req.recipient_id,
            event_type="new_message",
            payload={
                "sender_id": req.sender_id,
                "sender_name": sender.full_name,
                "preview": text_body[:80],
            },
        ))
    except Exception:
        pass

    await _touch_last_active(db, req.sender_id)
    _typing_signals.pop((req.sender_id, req.recipient_id), None)
    await db.commit()

    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "recipient_id": msg.recipient_id,
            "message_text": msg.message_text,
            "image_path": msg.image_path,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
        }
    }


@router.post("/typing")
async def set_typing(req: TypingRequest):
    """Register that `sender_id` is typing to `recipient_id` (in-memory, TTL ~6s)."""
    _typing_signals[(req.sender_id, req.recipient_id)] = time.time()
    return {"status": "ok"}


@router.post("/send-image")
async def send_image(
    sender_id: int = Form(...),
    recipient_id: int = Form(...),
    message_text: str = Form(""),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="O'zingizga xabar yubora olmaysiz")

    sender = (await db.execute(select(User).where(User.id == sender_id))).scalar_one_or_none()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    recipient = (await db.execute(select(User).where(User.id == recipient_id))).scalar_one_or_none()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(image.filename or "")[1] or ".jpg"
    fname = f"chat_{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(await image.read())
    image_url = f"/uploads/{fname}"

    msg = ChatMessage(
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_text=(message_text or "").strip(),
        image_path=image_url,
        is_read=False,
    )
    db.add(msg)
    try:
        db.add(NotificationLog(
            user_id=recipient_id,
            event_type="new_message",
            payload={"sender_id": sender_id, "sender_name": sender.full_name, "preview": "📷 Rasm"},
        ))
    except Exception:
        pass

    await _touch_last_active(db, sender_id)
    await db.commit()

    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "recipient_id": msg.recipient_id,
            "message_text": msg.message_text,
            "image_path": msg.image_path,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
        },
    }
