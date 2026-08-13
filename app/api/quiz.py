import logging
import os
from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api._shared import duration_seconds, iso, load_ai_questions
from app.core import config
from app.core.security import (
    ensure_can_access_user,
    get_current_user,
    require_staff,
)
from app.database import get_db
from app.models import (
    KnowledgeChunk,
    QuizAttempt,
    QuizAttemptStatus,
    QuizQuestion,
    StudentGrade,
    Subject,
    Topic,
    User,
    UserRole,
    utcnow,
)
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

router = APIRouter()
ai_service = AIService()
pdf_service = PDFService()

VALID_OPTIONS = ("A", "B", "C", "D")


def _cleanup(path: str) -> BackgroundTask:
    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


# ---------------------------------------------------------------------------
# Test generatsiya qilish va topshirish
# ---------------------------------------------------------------------------

class QuizStartRequest(BaseModel):
    topic_id: int
    language: str = Field(default="uz", max_length=10)


class QuizAnswer(BaseModel):
    question_id: int
    selected_option: Optional[str] = Field(default=None, max_length=10)


class QuizSubmitRequest(BaseModel):
    attempt_id: int
    answers: List[QuizAnswer] = Field(default_factory=list)
    elapsed_seconds: Optional[int] = Field(default=None, ge=0, le=86400)


def _normalize_generated(raw_questions: List[Dict]) -> List[Dict]:
    """AI javobini tekshirib, faqat to'g'ri tuzilgan savollarni qoldiradi."""
    cleaned = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        options = item.get("options")
        correct = str(item.get("correct_option") or "").strip().upper()

        if isinstance(options, list):
            options = {
                VALID_OPTIONS[i]: str(v)
                for i, v in enumerate(options[: len(VALID_OPTIONS)])
            }
        if not text or not isinstance(options, dict) or len(options) < 2:
            continue

        options = {str(k).strip().upper(): str(v) for k, v in options.items()}
        if correct not in options:
            continue

        cleaned.append({
            "question": text,
            "options": options,
            "correct_option": correct,
            "explanation": str(item.get("explanation") or "").strip(),
        })
    return cleaned


@router.post("/generate")
async def generate_quiz(
    request: QuizStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test savollarini yaratadi va urinishni ochadi.

    To'g'ri javoblar bazada saqlanadi va **klientga qaytarilmaydi** — baholash
    faqat server tomonda amalga oshiriladi.
    """
    topic = (
        await db.execute(select(Topic).where(Topic.id == request.topic_id))
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")

    chunks = (
        await db.execute(
            select(KnowledgeChunk.chunk_text)
            .where(KnowledgeChunk.topic_id == request.topic_id)
            .order_by(KnowledgeChunk.chunk_index)
            .limit(config.TOPIC_CONTEXT_CHUNK_LIMIT)
        )
    ).scalars().all()
    context = "\n".join(chunks)
    if not context.strip():
        raise HTTPException(
            status_code=400, detail="Bu mavzu uchun test tuzishga material yetarli emas."
        )

    # Model vaqti-vaqti bilan buzuq yoki to'liqsiz JSON qaytaradi. Bitta noaniq
    # javob tufayli talabaga xato ko'rsatmaslik uchun qayta so'raymiz.
    questions: List[Dict] = []
    last_raw = ""
    for attempt_no in range(2):
        try:
            last_raw = await ai_service.generate_quiz(
                context, count=config.QUIZ_QUESTION_COUNT, language=request.language
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            logger.error("Test generatsiya xatosi (topic=%s): %s", request.topic_id, exc)
            if "rate_limit" in message.lower() or "429" in message:
                raise HTTPException(
                    status_code=429,
                    detail="Sun'iy intellekt xizmati band. Iltimos, bir ozdan so'ng qayta urinib ko'ring.",
                )
            raise HTTPException(
                status_code=502, detail="Sun'iy intellektdan javob olishda xatolik yuz berdi."
            )

        try:
            questions = _normalize_generated(AIService.parse_quiz_payload(last_raw))
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Test JSON tahlil xatosi (urinish %s): %s | xom javob: %s",
                attempt_no + 1, exc, last_raw[:500],
            )
            questions = []

        if questions:
            break
        logger.warning(
            "AI yaroqli savol qaytarmadi (topic=%s, urinish %s/2)", request.topic_id, attempt_no + 1
        )

    if not questions:
        logger.error(
            "Test generatsiyasi ikki urinishda ham muvaffaqiyatsiz (topic=%s) | xom javob: %s",
            request.topic_id, last_raw[:500],
        )
        raise HTTPException(
            status_code=422,
            detail="Bu mavzu matnidan test tuzib bo'lmadi. Mavzu matni yetarli va mazmunli ekaniga ishonch hosil qiling.",
        )

    # Shu mavzu bo'yicha tugallanmagan eski urinishlarni tozalaymiz, aks holda
    # ular statistikada osilib qoladi.
    stale = (
        await db.execute(
            select(QuizAttempt.id).where(
                QuizAttempt.student_user_id == current_user.id,
                QuizAttempt.topic_id == request.topic_id,
                QuizAttempt.status == QuizAttemptStatus.in_progress,
            )
        )
    ).scalars().all()
    if stale:
        # Savollarni ham aniq o'chiramiz. Faqat ON DELETE CASCADE ga tayanib
        # bo'lmaydi: SQLite'da u sukut bo'yicha o'chirilgan, natijada yetim
        # savollar qolib, yangi urinishda unique constraint buzilardi.
        await db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_attempt_id.in_(stale)))
        await db.execute(delete(QuizAttempt).where(QuizAttempt.id.in_(stale)))

    attempt = QuizAttempt(
        student_user_id=current_user.id,
        topic_id=topic.id,
        employee_user_id=topic.employee_user_id,
        status=QuizAttemptStatus.in_progress,
        language=request.language,
        total_questions=len(questions),
        correct_answers=0,
        started_at=utcnow(),
    )
    db.add(attempt)
    await db.flush()

    stored = []
    for order, item in enumerate(questions):
        row = QuizQuestion(
            quiz_attempt_id=attempt.id,
            question_order=order,
            question_text=item["question"],
            options=item["options"],
            expected_answer=item["correct_option"],
            feedback_text=item["explanation"],
        )
        db.add(row)
        stored.append(row)

    await db.commit()

    return {
        "attempt_id": attempt.id,
        "topic_id": topic.id,
        "topic_title": topic.title,
        "language": attempt.language,
        "total_questions": attempt.total_questions,
        # Diqqat: `correct_option` va `explanation` bu yerda yo'q — ataylab.
        "questions": [
            {
                "id": row.id,
                "order": row.question_order,
                "question": row.question_text,
                "options": row.options,
            }
            for row in stored
        ],
    }


@router.post("/submit")
async def submit_quiz(
    req: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == req.attempt_id))
    ).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Test urinishi topilmadi")
    if attempt.student_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu test sizga tegishli emas")
    if attempt.status == QuizAttemptStatus.finished:
        raise HTTPException(status_code=409, detail="Bu test allaqachon yakunlangan")

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_attempt_id == attempt.id)
            .order_by(QuizQuestion.question_order)
        )
    ).scalars().all()
    if not questions:
        raise HTTPException(status_code=409, detail="Test savollari topilmadi")

    selected_by_id = {a.question_id: (a.selected_option or "").strip().upper() for a in req.answers}

    finished_at = utcnow()
    correct_count = 0
    for question in questions:
        selected = selected_by_id.get(question.id) or None
        # To'g'riligini FAQAT server hal qiladi.
        is_correct = bool(selected) and selected == (question.expected_answer or "").upper()
        if is_correct:
            correct_count += 1
        question.student_answer = selected
        question.is_correct = is_correct
        question.checked_at = finished_at

    elapsed = req.elapsed_seconds or 0
    attempt.correct_answers = correct_count
    attempt.status = QuizAttemptStatus.finished
    attempt.finished_at = finished_at
    if elapsed:
        attempt.started_at = finished_at - timedelta(seconds=elapsed)

    await db.commit()

    return {
        "status": "success",
        "attempt_id": attempt.id,
        "score": correct_count,
        "total": attempt.total_questions,
        "elapsed_seconds": duration_seconds(attempt) or elapsed,
        "results": [_question_public(q) for q in questions],
    }


def _question_public(q: QuizQuestion) -> dict:
    return {
        "question_id": q.id,
        "question": q.question_text,
        "options": q.options or {},
        "correct_option": q.expected_answer,
        "user_answer": q.student_answer,
        "is_correct": q.is_correct,
        "explanation": q.feedback_text or "",
    }


# ---------------------------------------------------------------------------
# Natijalar va hisobotlar
# ---------------------------------------------------------------------------

async def _load_attempt_for_user(db: AsyncSession, attempt_id: int, user: User) -> QuizAttempt:
    attempt = (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))
    ).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Natija topilmadi")
    ensure_can_access_user(user, attempt.student_user_id)
    return attempt


@router.get("/report/pdf")
async def get_pdf_report_by_id(
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = await _load_attempt_for_user(db, attempt_id, current_user)

    topic_title = (
        await db.execute(select(Topic.title).where(Topic.id == attempt.topic_id))
    ).scalar_one_or_none() or "Mavzu"
    student_name = (
        await db.execute(select(User.full_name).where(User.id == attempt.student_user_id))
    ).scalar_one_or_none() or "Talaba"

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_attempt_id == attempt_id)
            .order_by(QuizQuestion.question_order)
        )
    ).scalars().all()

    try:
        filepath = pdf_service.generate_quiz_report(
            student_name,
            topic_title,
            [_question_public(q) for q in questions],
            attempt.correct_answers,
            attempt.total_questions,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Natija PDF xatosi (attempt=%s): %s", attempt_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"Natija_{attempt_id}.pdf",
        background=_cleanup(filepath),
    )


class AdHocReportRequest(BaseModel):
    """Saqlanmagan natija uchun PDF (ilova `attempt_id` bo'lmaganda chaqiradi)."""

    user_full_name: Optional[str] = Field(default=None, max_length=255)
    topic_title: Optional[str] = Field(default=None, max_length=255)
    results: List[Dict] = Field(default_factory=list)
    score: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


@router.post("/report/pdf")
async def create_pdf_report(
    req: AdHocReportRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        filepath = pdf_service.generate_quiz_report(
            req.user_full_name or current_user.full_name,
            req.topic_title or "Mavzu",
            req.results,
            req.score,
            req.total,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Ad-hoc PDF xatosi: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename="Natija.pdf",
        background=_cleanup(filepath),
    )


@router.get("/history/{user_id}")
async def get_quiz_history(
    user_id: int,
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, user_id)

    attempts = (
        await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.student_user_id == user_id,
                QuizAttempt.status == QuizAttemptStatus.finished,
            )
            .order_by(QuizAttempt.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not attempts:
        return []

    titles = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Topic.id, Topic.title).where(
                    Topic.id.in_({a.topic_id for a in attempts})
                )
            )
        ).all()
    }

    return [
        {
            "id": a.id,
            "topic_id": a.topic_id,
            "topic_title": titles.get(a.topic_id, "O'chirilgan mavzu"),
            "score": a.correct_answers,
            "total": a.total_questions,
            "date": iso(a.started_at),
            "finished_at": iso(a.finished_at),
            "duration_seconds": duration_seconds(a),
        }
        for a in attempts
    ]


@router.get("/attempt/{attempt_id}")
async def get_quiz_attempt(
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = await _load_attempt_for_user(db, attempt_id, current_user)

    topic_title = (
        await db.execute(select(Topic.title).where(Topic.id == attempt.topic_id))
    ).scalar_one_or_none()
    student = (
        await db.execute(select(User).where(User.id == attempt.student_user_id))
    ).scalar_one_or_none()

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_attempt_id == attempt_id)
            .order_by(QuizQuestion.question_order)
        )
    ).scalars().all()

    return {
        "id": attempt.id,
        "student": {
            "id": student.id if student else attempt.student_user_id,
            "full_name": student.full_name if student else "Noma'lum talaba",
            "username": student.username if student else None,
        },
        "topic_id": attempt.topic_id,
        "topic_title": topic_title or "O'chirilgan mavzu",
        "score": attempt.correct_answers,
        "total": attempt.total_questions,
        "date": iso(attempt.started_at),
        "finished_at": iso(attempt.finished_at),
        "duration_seconds": duration_seconds(attempt),
        "results": [_question_public(q) for q in questions],
    }


@router.get("/students")
async def list_quiz_students(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    students = (
        await db.execute(
            select(User)
            .where(User.role == UserRole.student, User.is_active.is_(True))
            .order_by(User.created_at.desc())
        )
    ).scalars().all()

    stats = {
        row[0]: (row[1], row[2], row[3])
        for row in (
            await db.execute(
                select(
                    QuizAttempt.student_user_id,
                    func.count(QuizAttempt.id),
                    func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                    func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                )
                .where(QuizAttempt.status == QuizAttemptStatus.finished)
                .group_by(QuizAttempt.student_user_id)
            )
        ).all()
    }

    return [
        {
            "id": s.id,
            "full_name": s.full_name,
            "username": s.username,
            "is_active": s.is_active,
            "student_group": s.student_group,
            "created_at": iso(s.created_at),
            "attempts_count": stats.get(s.id, (0, 0, 0))[0],
            "questions_count": stats.get(s.id, (0, 0, 0))[1],
            "correct_answers": stats.get(s.id, (0, 0, 0))[2],
        }
        for s in students
    ]


@router.get("/students/{student_id}/overview")
async def quiz_student_overview(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_id)

    student = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Talaba topilmadi")

    attempts = (
        await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.student_user_id == student_id,
                QuizAttempt.status == QuizAttemptStatus.finished,
            )
            .order_by(QuizAttempt.started_at.desc())
        )
    ).scalars().all()

    from app.api.auth import _serialize_attempts  # aylanma importni oldini olish uchun shu yerda

    attempt_items = await _serialize_attempts(db, attempts)
    qa_items = await load_ai_questions(db, student_id)

    return {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "username": student.username,
            "role": student.role.value,
            "is_active": student.is_active,
            "created_at": iso(student.created_at),
        },
        "summary": {
            "attempts_count": len(attempts),
            "questions_count": sum(a.total_questions for a in attempts),
            "correct_answers": sum(a.correct_answers for a in attempts),
            "ai_questions_count": len(qa_items),
        },
        "attempts": attempt_items,
        "ai_questions": qa_items,
    }


# ---------------------------------------------------------------------------
# Baholar
# ---------------------------------------------------------------------------

_SUBJECT_CREDITS = {
    "anatomiya": 5,
    "gistologiya": 4,
    "biokimyo": 5,
    "fiziologiya": 4,
    "mikrobiologiya": 3,
    "farmakologiya": 3,
}


def _credit_for(title: str) -> int:
    lowered = title.lower()
    for keyword, credit in _SUBJECT_CREDITS.items():
        if keyword in lowered:
            return credit
    return 2


def _label_for(score: float) -> str:
    if score >= 90:
        return "A'lo"
    if score >= 80:
        return "Yaxshi"
    if score >= 60:
        return "Qoniqarli"
    return "Qoniqarsiz" if score > 0 else "-"


class StudentGradeCreateRequest(BaseModel):
    student_user_id: int
    subject_id: int
    score: float = Field(..., ge=0, le=100)
    grade_label: Optional[str] = Field(default=None, max_length=50)


@router.get("/grades/{student_user_id}")
async def get_student_grades(
    student_user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_user_id)

    subjects = (await db.execute(select(Subject).order_by(Subject.title))).scalars().all()
    grades = (
        await db.execute(
            select(StudentGrade).where(StudentGrade.student_user_id == student_user_id)
        )
    ).scalars().all()
    grades_map = {g.subject_id: g for g in grades}

    output = []
    for subject in subjects:
        grade = grades_map.get(subject.id)
        score = grade.score if grade else 0.0
        output.append({
            "subject_id": subject.id,
            "subject_title": subject.title,
            "credit": _credit_for(subject.title),
            "score": score,
            "grade_label": (grade.grade_label if grade and grade.grade_label else _label_for(score)),
            "grade_id": grade.id if grade else None,
        })
    return output


@router.post("/grades")
async def upsert_student_grade(
    req: StudentGradeCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if not (await db.execute(select(User.id).where(User.id == req.student_user_id))).first():
        raise HTTPException(status_code=404, detail="Talaba topilmadi")
    if not (await db.execute(select(Subject.id).where(Subject.id == req.subject_id))).first():
        raise HTTPException(status_code=404, detail="Fan topilmadi")

    existing = (
        await db.execute(
            select(StudentGrade).where(
                StudentGrade.student_user_id == req.student_user_id,
                StudentGrade.subject_id == req.subject_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.score = req.score
        existing.grade_label = req.grade_label
    else:
        db.add(StudentGrade(
            student_user_id=req.student_user_id,
            subject_id=req.subject_id,
            score=req.score,
            grade_label=req.grade_label,
        ))

    await db.commit()
    return {"status": "success", "message": "Baho saqlandi"}


@router.delete("/grades/{grade_id}")
async def delete_student_grade(
    grade_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    grade = (
        await db.execute(select(StudentGrade).where(StudentGrade.id == grade_id))
    ).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="Baho topilmadi")

    await db.delete(grade)
    await db.commit()
    return {"status": "success", "message": "Baho o'chirildi"}
