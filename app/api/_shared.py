"""API modullari orasida takrorlanadigan yordamchi funksiyalar.

Ilgari `_load_ai_questions` va `_duration_seconds` `auth.py` va `quiz.py` da
so'zma-so'z takrorlangan edi.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.models import NotificationLog, QuizAttempt, Topic


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive qiymatni UTC deb qabul qiladi (eski yozuvlar naive saqlangan)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    value = as_utc(dt)
    return value.isoformat() if value else None


def tashkent_date(dt: Optional[datetime]) -> Optional[date]:
    """Berilgan vaqtning Toshkent (UTC+5) bo'yicha kalendar sanasi."""
    value = as_utc(dt)
    if value is None:
        return None
    return (value + config.TASHKENT_OFFSET).date()


def tashkent_day_start_utc(reference: Optional[datetime] = None) -> datetime:
    """Toshkentdagi joriy kun boshining UTC ko'rinishi.

    Kunlik limitlarni hisoblashda ishlatiladi — ilgari bu Postgres'ga xos
    `date_trunc(... at time zone ...)` raw SQL orqali qilinardi.
    """
    now = as_utc(reference) or datetime.now(timezone.utc)
    local = now + config.TASHKENT_OFFSET
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight - config.TASHKENT_OFFSET


def duration_seconds(attempt: QuizAttempt) -> Optional[int]:
    started = as_utc(attempt.started_at)
    finished = as_utc(attempt.finished_at)
    if not started or not finished:
        return None
    return max(int((finished - started).total_seconds()), 0)


async def count_ai_questions_today(db: AsyncSession, user_id: int) -> int:
    day_start = tashkent_day_start_utc()
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(NotificationLog.id)).where(
            NotificationLog.user_id == user_id,
            NotificationLog.event_type == "ai_question",
            NotificationLog.created_at >= day_start,
        )
    )
    return result.scalar() or 0


async def load_ai_questions(db: AsyncSession, student_id: int, limit: int = 200) -> list[dict]:
    """Talabaning AI ga bergan savollari — bildirishnoma jurnalidan.

    Ilgari bu `to_regclass` + raw SQL orqali qilinar va har bir yozuv uchun
    alohida topic so'rovi yuborilardi (N+1).
    """
    rows = (
        await db.execute(
            select(NotificationLog)
            .where(
                NotificationLog.user_id == student_id,
                NotificationLog.event_type == "ai_question",
            )
            .order_by(NotificationLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    if not rows:
        return []

    payloads = [_coerce_payload(row.payload) for row in rows]
    topic_ids = {p.get("topic_id") for p in payloads if p.get("topic_id")}
    titles: dict[int, str] = {}
    if topic_ids:
        topic_rows = await db.execute(
            select(Topic.id, Topic.title).where(Topic.id.in_(topic_ids))
        )
        titles = {row[0]: row[1] for row in topic_rows.all()}

    return [
        {
            "id": row.id,
            "topic_title": titles.get(payload.get("topic_id"), "Mavzu"),
            "question": payload.get("question", ""),
            "answer": payload.get("answer", ""),
            "language": payload.get("language", "uz"),
            "date": iso(row.created_at),
        }
        for row, payload in zip(rows, payloads)
    ]


def _coerce_payload(payload) -> dict:
    if isinstance(payload, str):
        import json

        try:
            parsed = json.loads(payload)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return payload or {}
