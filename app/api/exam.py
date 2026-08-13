"""Imtihon rejimi — bir nechta mavzudan yig'ma test.

Oddiy testdan farqi:

* savollar bir nechta mavzudan (yoki butun fandan) yig'iladi;
* vaqt cheklangan, qolgan vaqt serverda hisoblanadi;
* har bir javob darhol saqlanadi — ilova yopilsa ham imtihon davom etadi;
* yakunda mavzular kesimida tahlil beriladi.

Baholash, vaqt nazorati va savollarni aralashtirish faqat server tomonda.
"""

import asyncio
import logging
import os
import random
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from app.api._shared import as_utc, iso
from app.api.quiz import _normalize_generated
from app.core import config
from app.core.security import get_current_user
from app.database import get_db
from app.models import (
    ExamAttempt,
    ExamQuestion,
    ExamStatus,
    KnowledgeChunk,
    QuizAttempt,
    QuizAttemptStatus,
    QuizQuestion,
    Subject,
    Topic,
    TopicStatus,
    User,
    utcnow,
)
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)
ai_service = AIService()
pdf_service = PDFService()

OPTION_KEYS = ("A", "B", "C", "D")

# Vaqt tugagach klient submit qilishga ulgurmasligi mumkin (tarmoq, fon rejimi).
# Shu qadar kechikish kechiriladi, keyin urinish "expired" deb belgilanadi.
SUBMIT_GRACE_SECONDS = 90

MIN_QUESTIONS = 5
MAX_QUESTIONS = 50


class ExamStartRequest(BaseModel):
    subject_id: Optional[int] = None
    # Aniq mavzular ko'rsatilsa shular olinadi, aks holda fanning barcha
    # aktiv mavzulari.
    topic_ids: Optional[List[int]] = Field(default=None, max_length=50)
    question_count: int = Field(default=20, ge=MIN_QUESTIONS, le=MAX_QUESTIONS)
    duration_minutes: int = Field(default=30, ge=0, le=180)
    language: str = Field(default="uz", max_length=10)


class ExamAnswerRequest(BaseModel):
    question_id: int
    # Bo'sh qiymat — javobni bekor qilish.
    selected_option: Optional[str] = Field(default=None, max_length=10)


class ExamSubmitRequest(BaseModel):
    answers: List[ExamAnswerRequest] = Field(default_factory=list, max_length=MAX_QUESTIONS)


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------

def _cleanup(path: str) -> BackgroundTask:
    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _shuffle_options(item: dict) -> dict:
    """Variantlarni aralashtiradi va to'g'ri javob harfini moslaydi.

    Savollar bankdan olinganda talaba ularni ilgari ko'rgan bo'lishi mumkin —
    variantlar tartibi o'zgargani yodlab olishning oldini oladi.
    """
    options = item.get("options") or {}
    correct = item.get("correct_option")
    correct_text = options.get(correct)
    if not options or correct_text is None:
        return item

    texts = list(options.values())
    random.shuffle(texts)
    shuffled = {OPTION_KEYS[i]: text for i, text in enumerate(texts[: len(OPTION_KEYS)])}

    new_correct = next(
        (key for key, text in shuffled.items() if text == correct_text), None
    )
    if new_correct is None:
        # To'g'ri javob kesib tashlangan bo'lsa — o'zgartirmaymiz.
        return item

    return {**item, "options": shuffled, "correct_option": new_correct}


async def _resolve_topics(
    db: AsyncSession, req: ExamStartRequest
) -> tuple[List[int], str]:
    """Imtihon uchun mavzular ro'yxati va sarlavhani aniqlaydi."""
    if req.topic_ids:
        rows = (
            await db.execute(
                select(Topic.id).where(
                    Topic.id.in_(req.topic_ids), Topic.status == TopicStatus.active
                )
            )
        ).scalars().all()
        if not rows:
            raise HTTPException(status_code=404, detail="Ko'rsatilgan mavzular topilmadi")
        title = "Tanlangan mavzular bo'yicha imtihon"
        if req.subject_id:
            subject_title = (
                await db.execute(select(Subject.title).where(Subject.id == req.subject_id))
            ).scalar_one_or_none()
            if subject_title:
                title = f"{subject_title} — imtihon"
        return list(rows), title

    if not req.subject_id:
        raise HTTPException(
            status_code=400, detail="Fan yoki mavzular ro'yxatidan birini ko'rsating"
        )

    subject_title = (
        await db.execute(select(Subject.title).where(Subject.id == req.subject_id))
    ).scalar_one_or_none()
    if subject_title is None:
        raise HTTPException(status_code=404, detail="Fan topilmadi")

    rows = (
        await db.execute(
            select(Topic.id).where(
                Topic.subject_id == req.subject_id, Topic.status == TopicStatus.active
            )
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=422, detail="Bu fanda hali mavzular yo'q — imtihon tuzib bo'lmaydi."
        )
    return list(rows), f"{subject_title} — imtihon"


async def _questions_from_bank(
    db: AsyncSession, topic_ids: List[int], language: str
) -> List[dict]:
    """Ilgari tuzilgan savollardan bank yig'adi (AI ni kutmaslik uchun).

    Manba: shu mavzular bo'yicha yakunlangan testlar va imtihonlar savollari.
    """
    quiz_rows = (
        await db.execute(
            select(
                QuizQuestion.question_text,
                QuizQuestion.options,
                QuizQuestion.expected_answer,
                QuizQuestion.feedback_text,
                QuizAttempt.topic_id,
            )
            .join(QuizAttempt, QuizAttempt.id == QuizQuestion.quiz_attempt_id)
            .where(
                QuizAttempt.topic_id.in_(topic_ids),
                QuizAttempt.status == QuizAttemptStatus.finished,
                QuizAttempt.language == language,
            )
            .limit(600)
        )
    ).all()

    exam_rows = (
        await db.execute(
            select(
                ExamQuestion.question_text,
                ExamQuestion.options,
                ExamQuestion.expected_answer,
                ExamQuestion.feedback_text,
                ExamQuestion.topic_id,
            )
            .join(ExamAttempt, ExamAttempt.id == ExamQuestion.exam_attempt_id)
            .where(
                ExamQuestion.topic_id.in_(topic_ids),
                ExamAttempt.language == language,
            )
            .limit(600)
        )
    ).all()

    seen: set[str] = set()
    bank: List[dict] = []
    for text, options, expected, feedback, topic_id in [*quiz_rows, *exam_rows]:
        key = _normalize_text(text)
        if not key or key in seen:
            continue
        if not isinstance(options, dict) or len(options) < 2 or not expected:
            continue
        if expected not in options:
            continue
        seen.add(key)
        bank.append({
            "question": text,
            "options": dict(options),
            "correct_option": expected,
            "explanation": feedback or "",
            "topic_id": topic_id,
        })
    return bank


async def _generate_for_topic(
    db: AsyncSession, topic_id: int, count: int, language: str
) -> List[dict]:
    """Bitta mavzu bo'yicha AI orqali savollar tuzadi."""
    chunks = (
        await db.execute(
            select(KnowledgeChunk.chunk_text)
            .where(KnowledgeChunk.topic_id == topic_id)
            .order_by(KnowledgeChunk.chunk_index)
            .limit(config.TOPIC_CONTEXT_CHUNK_LIMIT)
        )
    ).scalars().all()
    context = "\n".join(chunks).strip()
    if not context:
        return []

    try:
        raw = await ai_service.generate_quiz(context, count=count, language=language)
        items = _normalize_generated(AIService.parse_quiz_payload(raw))
    except Exception as exc:  # noqa: BLE001 — bitta mavzu yiqilsa imtihon davom etadi
        logger.warning("Imtihon uchun savol tuzilmadi (topic=%s): %s", topic_id, exc)
        return []

    return [{**item, "topic_id": topic_id} for item in items]


def _public_question(q: ExamQuestion) -> dict:
    """Talabaga ko'rinadigan ko'rinish — to'g'ri javobsiz."""
    return {
        "id": q.id,
        "order": q.question_order,
        "topic_id": q.topic_id,
        "question": q.question_text,
        "options": q.options or {},
        "selected_option": q.student_answer,
    }


def _review_question(q: ExamQuestion) -> dict:
    """Yakundan keyingi ko'rinish — to'g'ri javob va izoh bilan."""
    return {
        "question_id": q.id,
        "topic_id": q.topic_id,
        "question": q.question_text,
        "options": q.options or {},
        "correct_option": q.expected_answer,
        "user_answer": q.student_answer,
        "is_correct": q.is_correct,
        "explanation": q.feedback_text or "",
    }


def _remaining_seconds(attempt: ExamAttempt) -> Optional[int]:
    """Qolgan vaqt. Cheklov bo'lmasa `None`."""
    if not attempt.duration_seconds:
        return None
    started = as_utc(attempt.started_at) or utcnow()
    elapsed = (utcnow() - started).total_seconds()
    return max(int(attempt.duration_seconds - elapsed), 0)


def _elapsed_seconds(attempt: ExamAttempt) -> int:
    started = as_utc(attempt.started_at) or utcnow()
    finished = as_utc(attempt.finished_at) or utcnow()
    return max(int((finished - started).total_seconds()), 0)


def _label_for(percent: float) -> str:
    if percent >= 90:
        return "A'lo"
    if percent >= 80:
        return "Yaxshi"
    if percent >= 60:
        return "Qoniqarli"
    return "Qoniqarsiz"


async def _load_attempt(
    db: AsyncSession, attempt_id: int, user: User, *, with_questions: bool = True
) -> ExamAttempt:
    stmt = select(ExamAttempt).where(ExamAttempt.id == attempt_id)
    if with_questions:
        stmt = stmt.options(selectinload(ExamAttempt.questions))
    attempt = (await db.execute(stmt)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi")
    if attempt.student_user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu imtihon sizga tegishli emas")
    return attempt


# ---------------------------------------------------------------------------
# Endpointlar
# ---------------------------------------------------------------------------

@router.get("/active")
async def get_active_exam(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tugallanmagan imtihon (bo'lsa) — ilova "davom ettirish" taklif qiladi."""
    attempt = (
        await db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.questions))
            .where(
                ExamAttempt.student_user_id == current_user.id,
                ExamAttempt.status == ExamStatus.in_progress,
            )
            .order_by(ExamAttempt.started_at.desc())
        )
    ).scalars().first()

    if not attempt:
        return {"active": None}

    remaining = _remaining_seconds(attempt)
    # Vaqti allaqachon tugagan bo'lsa uni ochiq qoldirmaymiz.
    if remaining == 0:
        await _finalize(db, attempt, timed_out=True)
        return {"active": None}

    return {"active": _attempt_public(attempt, remaining)}


def _attempt_public(attempt: ExamAttempt, remaining: Optional[int]) -> dict:
    return {
        "attempt_id": attempt.id,
        "title": attempt.title,
        "subject_id": attempt.subject_id,
        "language": attempt.language,
        "total_questions": attempt.total_questions,
        "duration_seconds": attempt.duration_seconds,
        "remaining_seconds": remaining,
        "started_at": iso(attempt.started_at),
        "questions": [_public_question(q) for q in attempt.questions],
    }


@router.post("/start")
async def start_exam(
    req: ExamStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Imtihonni boshlaydi.

    Savollar avval mavjud bankdan olinadi (tez), yetmasa AI bilan to'ldiriladi.
    To'g'ri javoblar klientga **qaytarilmaydi**.
    """
    existing = (
        await db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.questions))
            .where(
                ExamAttempt.student_user_id == current_user.id,
                ExamAttempt.status == ExamStatus.in_progress,
            )
            .order_by(ExamAttempt.started_at.desc())
        )
    ).scalars().first()
    if existing:
        if _remaining_seconds(existing) == 0:
            await _finalize(db, existing, timed_out=True)
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Sizda tugallanmagan imtihon bor. Avval uni yakunlang.",
                    "attempt_id": existing.id,
                },
            )

    topic_ids, title = await _resolve_topics(db, req)
    language = "ru" if str(req.language).lower().startswith("ru") else "uz"

    bank = await _questions_from_bank(db, topic_ids, language)
    random.shuffle(bank)
    selected = bank[: req.question_count]

    # Bankda yetmasa — yetishmagan qismini AI tuzadi (mavzular bo'yicha
    # parallel, aks holda kutish vaqti mavzular soniga ko'payib ketardi).
    shortfall = req.question_count - len(selected)
    if shortfall > 0:
        targets = topic_ids[:5]
        per_topic = max(1, -(-shortfall // len(targets)))  # yuqoriga yaxlitlash
        generated_groups = await asyncio.gather(
            *[
                _generate_for_topic(db, topic_id, per_topic, language)
                for topic_id in targets
            ]
        )
        seen = {_normalize_text(item["question"]) for item in selected}
        for group in generated_groups:
            for item in group:
                key = _normalize_text(item["question"])
                if key in seen:
                    continue
                seen.add(key)
                selected.append(item)
        random.shuffle(selected)
        selected = selected[: req.question_count]

    if len(selected) < MIN_QUESTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Imtihon uchun yetarli savol topilmadi. Avval shu fandagi "
                "mavzular bo'yicha oddiy testlarni topshiring yoki mavzu "
                "matnlari to'ldirilganini tekshiring."
            ),
        )

    attempt = ExamAttempt(
        student_user_id=current_user.id,
        subject_id=req.subject_id,
        title=title,
        topic_ids=topic_ids,
        status=ExamStatus.in_progress,
        language=language,
        total_questions=len(selected),
        correct_answers=0,
        duration_seconds=req.duration_minutes * 60,
        started_at=utcnow(),
    )
    db.add(attempt)
    await db.flush()

    for order, item in enumerate(_shuffle_options(x) for x in selected):
        db.add(ExamQuestion(
            exam_attempt_id=attempt.id,
            topic_id=item.get("topic_id"),
            question_order=order,
            question_text=item["question"],
            options=item["options"],
            expected_answer=item["correct_option"],
            feedback_text=item.get("explanation") or "",
        ))

    await db.commit()

    refreshed = (
        await db.execute(
            select(ExamAttempt)
            .options(selectinload(ExamAttempt.questions))
            .where(ExamAttempt.id == attempt.id)
        )
    ).scalar_one()
    return _attempt_public(refreshed, _remaining_seconds(refreshed))


@router.get("/history")
async def exam_history(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempts = (
        await db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.student_user_id == current_user.id,
                ExamAttempt.status != ExamStatus.in_progress,
            )
            .order_by(ExamAttempt.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return [
        {
            "attempt_id": a.id,
            "title": a.title,
            "subject_id": a.subject_id,
            "score": a.correct_answers,
            "total": a.total_questions,
            "percent": (
                round(a.correct_answers / a.total_questions * 100, 1)
                if a.total_questions
                else 0.0
            ),
            "status": a.status.value,
            "started_at": iso(a.started_at),
            "finished_at": iso(a.finished_at),
            "duration_seconds": _elapsed_seconds(a),
        }
        for a in attempts
    ]


@router.get("/{attempt_id}")
async def get_exam(
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Davom ettirish uchun: savollar, saqlangan javoblar va qolgan vaqt."""
    attempt = await _load_attempt(db, attempt_id, current_user)

    if attempt.status != ExamStatus.in_progress:
        return _result_payload(attempt, timed_out=attempt.status == ExamStatus.expired)

    remaining = _remaining_seconds(attempt)
    if remaining == 0:
        await _finalize(db, attempt, timed_out=True)
        return _result_payload(attempt, timed_out=True)

    return _attempt_public(attempt, remaining)


@router.post("/{attempt_id}/answer")
async def save_answer(
    attempt_id: int,
    req: ExamAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bitta javobni saqlaydi — ilova yopilsa ham javoblar yo'qolmaydi."""
    attempt = await _load_attempt(db, attempt_id, current_user)
    if attempt.status != ExamStatus.in_progress:
        raise HTTPException(status_code=409, detail="Imtihon allaqachon yakunlangan")
    if _remaining_seconds(attempt) == 0:
        await _finalize(db, attempt, timed_out=True)
        raise HTTPException(status_code=409, detail="Imtihon vaqti tugadi")

    question = next((q for q in attempt.questions if q.id == req.question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Savol topilmadi")

    choice = (req.selected_option or "").strip().upper() or None
    if choice is not None and choice not in (question.options or {}):
        raise HTTPException(status_code=400, detail="Bunday variant yo'q")

    question.student_answer = choice
    question.answered_at = utcnow()
    await db.commit()

    answered = sum(1 for q in attempt.questions if q.student_answer)
    return {
        "status": "saved",
        "answered_count": answered,
        "total_questions": attempt.total_questions,
        "remaining_seconds": _remaining_seconds(attempt),
    }


async def _finalize(db: AsyncSession, attempt: ExamAttempt, *, timed_out: bool) -> None:
    """Javoblarni tekshiradi va urinishni yopadi."""
    finished_at = utcnow()
    correct = 0
    for question in attempt.questions:
        selected = (question.student_answer or "").strip().upper() or None
        is_correct = bool(selected) and selected == (question.expected_answer or "").upper()
        question.is_correct = is_correct
        if is_correct:
            correct += 1

    attempt.correct_answers = correct
    attempt.status = ExamStatus.expired if timed_out else ExamStatus.finished
    attempt.finished_at = finished_at

    if attempt.duration_seconds:
        # Vaqt tugagach yopilgan bo'lsa, sarflangan vaqt aynan chegaraga teng.
        started = as_utc(attempt.started_at) or finished_at
        limit_end = started + timedelta(seconds=attempt.duration_seconds)
        if timed_out and finished_at > limit_end:
            attempt.finished_at = limit_end

    await db.commit()


def _result_payload(attempt: ExamAttempt, *, timed_out: bool) -> dict:
    total = attempt.total_questions or 0
    percent = round(attempt.correct_answers / total * 100, 1) if total else 0.0

    # Mavzular kesimida tahlil — qaysi mavzuni takrorlash kerakligi ko'rinadi.
    per_topic: dict[int, dict] = {}
    for question in attempt.questions:
        key = question.topic_id or 0
        bucket = per_topic.setdefault(key, {"topic_id": question.topic_id, "correct": 0, "total": 0})
        bucket["total"] += 1
        if question.is_correct:
            bucket["correct"] += 1

    breakdown = sorted(
        (
            {
                **bucket,
                "percent": (
                    round(bucket["correct"] / bucket["total"] * 100, 1)
                    if bucket["total"]
                    else 0.0
                ),
            }
            for bucket in per_topic.values()
        ),
        key=lambda x: x["percent"],
    )

    unanswered = sum(1 for q in attempt.questions if not q.student_answer)

    return {
        "attempt_id": attempt.id,
        "title": attempt.title,
        "status": attempt.status.value,
        "timed_out": timed_out,
        "score": attempt.correct_answers,
        "total": total,
        "percent": percent,
        "grade_label": _label_for(percent),
        "unanswered": unanswered,
        "duration_seconds": _elapsed_seconds(attempt),
        "started_at": iso(attempt.started_at),
        "finished_at": iso(attempt.finished_at),
        "topic_breakdown": breakdown,
        "results": [_review_question(q) for q in attempt.questions],
    }


@router.post("/{attempt_id}/submit")
async def submit_exam(
    attempt_id: int,
    req: ExamSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Imtihonni yakunlaydi va natijani qaytaradi."""
    attempt = await _load_attempt(db, attempt_id, current_user)
    if attempt.status != ExamStatus.in_progress:
        raise HTTPException(status_code=409, detail="Bu imtihon allaqachon yakunlangan")

    remaining = _remaining_seconds(attempt)
    started = as_utc(attempt.started_at) or utcnow()
    overdue = (
        attempt.duration_seconds
        and (utcnow() - started).total_seconds()
        > attempt.duration_seconds + SUBMIT_GRACE_SECONDS
    )

    # Oxirgi javoblar (klient ularni bittalab yubormagan bo'lishi mumkin).
    by_id = {q.id: q for q in attempt.questions}
    for answer in req.answers:
        question = by_id.get(answer.question_id)
        if question is None:
            continue
        choice = (answer.selected_option or "").strip().upper() or None
        if choice is not None and choice not in (question.options or {}):
            continue
        question.student_answer = choice

    await _finalize(db, attempt, timed_out=bool(overdue))
    return _result_payload(attempt, timed_out=bool(overdue) or remaining == 0)


@router.get("/{attempt_id}/result")
async def get_exam_result(
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = await _load_attempt(db, attempt_id, current_user)
    if attempt.status == ExamStatus.in_progress:
        raise HTTPException(status_code=409, detail="Imtihon hali yakunlanmagan")
    return _result_payload(attempt, timed_out=attempt.status == ExamStatus.expired)


@router.get("/{attempt_id}/report/pdf")
async def exam_report_pdf(
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = await _load_attempt(db, attempt_id, current_user)
    if attempt.status == ExamStatus.in_progress:
        raise HTTPException(status_code=409, detail="Imtihon hali yakunlanmagan")

    try:
        filepath = pdf_service.generate_quiz_report(
            current_user.full_name,
            attempt.title,
            [_review_question(q) for q in attempt.questions],
            attempt.correct_answers,
            attempt.total_questions,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Imtihon PDF xatosi (attempt=%s): %s", attempt_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"Imtihon_{attempt_id}.pdf",
        background=_cleanup(filepath),
    )
