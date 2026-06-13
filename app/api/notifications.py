import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import NotificationLog

router = APIRouter(redirect_slashes=True)


def _coerce_payload(payload):
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return payload or {}


def _format(n: NotificationLog) -> dict:
    et = n.event_type
    p = _coerce_payload(n.payload)

    if et == "homework_graded":
        title = "Vazifa baholandi"
        name = p.get("title", "Vazifa")
        status = p.get("status", "")
        grade = p.get("grade")
        if status == "approved":
            body = f"\"{name}\" qabul qilindi" + (f" — baho: {grade}" if grade else "")
        elif status == "rejected":
            body = f"\"{name}\" qayta ishlash uchun qaytarildi"
        else:
            body = f"\"{name}\" ko'rib chiqildi"
        icon = "homework"
    elif et == "new_message":
        title = p.get("sender_name") or "Yangi xabar"
        body = p.get("preview") or "Sizga yangi xabar keldi"
        icon = "message"
    elif et == "ai_question":
        title = "AI javobi"
        body = p.get("question") or "Savolingizga javob berildi"
        icon = "ai"
    else:
        title = et.replace("_", " ").title()
        body = ""
        icon = "bell"

    return {
        "id": n.id,
        "event_type": et,
        "title": title,
        "body": body,
        "icon": icon,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("")
@router.get("/")
async def list_notifications(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        res = await db.execute(
            select(NotificationLog)
            .where(NotificationLog.user_id == user_id)
            .order_by(NotificationLog.created_at.desc())
            .limit(limit)
        )
        return [_format(n) for n in res.scalars().all()]
    except Exception:
        # notification_logs may be absent in some environments — fail soft.
        return []
