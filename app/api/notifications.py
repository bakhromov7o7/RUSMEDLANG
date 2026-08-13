import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso
from app.core.security import get_current_user
from app.database import get_db
from app.models import NotificationLog, User

router = APIRouter(redirect_slashes=True)

# Texnik yozuvlar — jurnalda saqlanadi, lekin bildirishnoma sifatida
# ko'rsatilmaydi (masalan xavfsizlik bo'limidagi "oxirgi kirish").
HIDDEN_EVENT_TYPES = ("login", "ai_question")


def _coerce_payload(payload) -> dict:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return payload or {}


def _format(n: NotificationLog) -> dict:
    event_type = n.event_type
    payload = _coerce_payload(n.payload)

    if event_type == "homework_graded":
        title = "Vazifa baholandi"
        name = payload.get("title", "Vazifa")
        state = payload.get("status", "")
        grade = payload.get("grade")
        if state == "approved":
            body = f'"{name}" qabul qilindi' + (f" — baho: {grade}" if grade else "")
        elif state == "rejected":
            body = f'"{name}" qayta ishlash uchun qaytarildi'
        else:
            body = f'"{name}" ko\'rib chiqildi'
        icon = "homework"
    elif event_type == "new_message":
        title = payload.get("sender_name") or "Yangi xabar"
        body = payload.get("preview") or "Sizga yangi xabar keldi"
        icon = "message"
    elif event_type == "group_message":
        title = payload.get("group_name") or "Guruh chati"
        sender = payload.get("sender_name") or ""
        preview = payload.get("preview") or ""
        body = f"{sender}: {preview}".strip(": ")
        icon = "message"
    elif event_type == "new_request":
        title = "Yangi murojaat"
        sender = payload.get("student_name") or "Talaba"
        body = f"{sender}: {payload.get('subject', '')}".strip(': ')
        icon = "request"
    elif event_type == "request_answered":
        title = "Murojaatingizga javob"
        state = payload.get("status", "")
        label = {
            "resolved": "hal qilindi",
            "rejected": "rad etildi",
            "in_progress": "ko'rib chiqilmoqda",
        }.get(state, "yangilandi")
        body = f"\"{payload.get('subject', 'Murojaat')}\" {label}"
        icon = "request"
    elif event_type == "ai_question":
        title = "AI javobi"
        body = payload.get("question") or "Savolingizga javob berildi"
        icon = "ai"
    elif event_type == "attendance_absent":
        title = "Davomat belgilandi"
        label = payload.get("status_label") or "Kelmadi"
        body = (
            f"{payload.get('subject', 'Dars')} — {label}"
            + (f" ({payload.get('date')})" if payload.get("date") else "")
        )
        icon = "attendance"
    elif event_type == "excuse_reviewed":
        title = "Sabab ko'rib chiqildi"
        state = "qabul qilindi" if payload.get("approved") else "rad etildi"
        body = f"{payload.get('subject', 'Dars')} — sababingiz {state}"
        if payload.get("comment"):
            body += f". {payload['comment']}"
        icon = "attendance"
    elif event_type == "location_violation":
        title = "Dars vaqtida o'quv binosida emassiz"
        # Xabar matni serverda tayyorlanadi — muddat va fan nomi bilan.
        body = payload.get("message") or (
            "Dars vaqtida o'quv binosidan tashqarida ekanligingiz aniqlandi. "
            "12 soat ichida sababini tushuntirib so'rov yuboring."
        )
        icon = "warning"
    elif event_type == "violation_reviewed":
        title = "Tushuntirishingiz ko'rib chiqildi"
        state = "qabul qilindi" if payload.get("accepted") else "rad etildi"
        body = f"Tushuntirishingiz {state}"
        if payload.get("comment"):
            body += f". {payload['comment']}"
        icon = "warning"
    else:
        title = event_type.replace("_", " ").title()
        body = ""
        icon = "bell"

    return {
        "id": n.id,
        "event_type": event_type,
        "title": title,
        "body": body,
        "icon": icon,
        "is_read": n.is_read,
        "created_at": iso(n.created_at),
    }


@router.get("")
@router.get("/")
async def list_notifications(
    user_id: Optional[int] = None,  # e'tiborsiz — tokendan olinadi
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(NotificationLog).where(
        NotificationLog.user_id == current_user.id,
        NotificationLog.event_type.notin_(HIDDEN_EVENT_TYPES),
    )
    if unread_only:
        stmt = stmt.where(NotificationLog.is_read.is_(False))

    rows = (
        await db.execute(stmt.order_by(NotificationLog.created_at.desc()).limit(limit))
    ).scalars().all()
    return [_format(n) for n in rows]


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.user_id == current_user.id,
                NotificationLog.is_read.is_(False),
                NotificationLog.event_type.notin_(HIDDEN_EVENT_TYPES),
            )
        )
    ).scalar() or 0
    return {"count": total}


@router.post("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(NotificationLog)
        .where(
            NotificationLog.user_id == current_user.id,
            NotificationLog.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "success"}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notification = (
        await db.execute(
            select(NotificationLog).where(NotificationLog.id == notification_id)
        )
    ).scalar_one_or_none()
    if not notification or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bildirishnoma topilmadi")

    notification.is_read = True
    await db.commit()
    return {"status": "success"}
