"""Chuqurlashtirilgan tahlil — xodim va administrator paneli uchun.

`GET /api/auth/analytics` panelning bosh sahifasiga umumiy ko'rsatkichlarni
beradi; bu modul esa kesimlar bo'yicha tahlilni qaytaradi: guruhlar, fanlar,
kunlik faollik, e'tibor talab qiladigan talabalar va (superadmin uchun)
xodimlar faoliyati.

Barcha hisob-kitob bir necha yig'ma so'rovda bajariladi — talabalar soni
o'sganda ham N+1 muammosi bo'lmasligi uchun.
"""

import logging
import os
from datetime import date as date_cls, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api._shared import as_utc, iso, tashkent_date
from app.core.security import require_staff, require_superadmin
from app.database import get_db
from app.models import (
    AttendanceRecord,
    AttendanceStatus,
    ExamAttempt,
    ExamStatus,
    Homework,
    HomeworkSubmission,
    NotificationLog,
    QuizAttempt,
    QuizAttemptStatus,
    Subject,
    Topic,
    User,
    UserRole,
    utcnow,
)
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)
pdf_service = PDFService()

# Davomat foiziga "kelgan" deb hisoblanadigan holatlar (attendance.py bilan bir xil).
ATTENDED = (AttendanceStatus.present, AttendanceStatus.late, AttendanceStatus.excused)

# E'tibor talab qiladigan talaba chegaralari.
LOW_ATTENDANCE = 75.0   # foiz
LOW_SCORE = 3.0         # 5 ballik shkalada


def _cleanup(path: str) -> BackgroundTask:
    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _score5(correct: int, total: int) -> float:
    """To'g'ri javoblar ulushini 5 ballik shkalaga o'tkazadi."""
    return round(correct / total * 5.0, 2) if total else 0.0


# ---------------------------------------------------------------------------
# Umumiy yig'malar (bir marta o'qib, kesimlarga tarqatiladi)
# ---------------------------------------------------------------------------

async def _quiz_by_student(db: AsyncSession) -> dict[int, tuple[int, int, int]]:
    """student_id -> (to'g'ri, jami savol, urinishlar soni)."""
    rows = (
        await db.execute(
            select(
                QuizAttempt.student_user_id,
                func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                func.count(QuizAttempt.id),
            )
            .where(QuizAttempt.status == QuizAttemptStatus.finished)
            .group_by(QuizAttempt.student_user_id)
        )
    ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def _attendance_by_student(db: AsyncSession) -> dict[int, tuple[int, int]]:
    """student_id -> (kelgan, jami)."""
    rows = (
        await db.execute(
            select(AttendanceRecord.student_user_id, AttendanceRecord.status)
        )
    ).all()
    result: dict[int, list[int]] = {}
    for student_id, status in rows:
        bucket = result.setdefault(student_id, [0, 0])
        bucket[1] += 1
        if status in ATTENDED:
            bucket[0] += 1
    return {k: (v[0], v[1]) for k, v in result.items()}


async def _homework_by_student(db: AsyncSession) -> dict[int, tuple[int, int]]:
    """student_id -> (tasdiqlangan, jami yuborilgan)."""
    raw = (
        await db.execute(
            select(HomeworkSubmission.student_user_id, HomeworkSubmission.status)
        )
    ).all()
    result: dict[int, list[int]] = {}
    for student_id, status in raw:
        bucket = result.setdefault(student_id, [0, 0])
        bucket[1] += 1
        if status == "approved":
            bucket[0] += 1
    return {k: (v[0], v[1]) for k, v in result.items()}


async def _active_students(db: AsyncSession) -> list[User]:
    return (
        await db.execute(
            select(User)
            .where(User.role == UserRole.student, User.is_active.is_(True))
            .order_by(User.full_name)
        )
    ).scalars().all()


# ---------------------------------------------------------------------------
# Guruhlar kesimi
# ---------------------------------------------------------------------------

@router.get("/groups")
async def analytics_by_group(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Har bir guruh bo'yicha: talabalar, o'rtacha ball, davomat, vazifalar."""
    students = await _active_students(db)
    quiz = await _quiz_by_student(db)
    attendance = await _attendance_by_student(db)
    homework = await _homework_by_student(db)

    groups: dict[str, dict] = {}
    for student in students:
        key = (student.student_group or "").strip() or "Guruhsiz"
        bucket = groups.setdefault(key, {
            "student_group": key,
            "students": 0,
            "_correct": 0, "_questions": 0,
            "_present": 0, "_lessons": 0,
            "_approved": 0, "_submissions": 0,
        })
        bucket["students"] += 1

        correct, questions, _ = quiz.get(student.id, (0, 0, 0))
        bucket["_correct"] += correct
        bucket["_questions"] += questions

        present, lessons = attendance.get(student.id, (0, 0))
        bucket["_present"] += present
        bucket["_lessons"] += lessons

        approved, submissions = homework.get(student.id, (0, 0))
        bucket["_approved"] += approved
        bucket["_submissions"] += submissions

    output = []
    for bucket in groups.values():
        output.append({
            "student_group": bucket["student_group"],
            "students": bucket["students"],
            "average_score": _score5(bucket["_correct"], bucket["_questions"]),
            "accuracy": _pct(bucket["_correct"], bucket["_questions"]),
            "attendance_percent": _pct(bucket["_present"], bucket["_lessons"]),
            "attendance_total": bucket["_lessons"],
            "homework_percent": _pct(bucket["_approved"], bucket["_submissions"]),
            "homework_total": bucket["_submissions"],
        })

    # Eng zaif guruh yuqorida — e'tibor birinchi shunga kerak.
    output.sort(key=lambda x: (x["average_score"], x["attendance_percent"]))
    return output


# ---------------------------------------------------------------------------
# Fanlar kesimi
# ---------------------------------------------------------------------------

@router.get("/subjects")
async def analytics_by_subject(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Har bir fan bo'yicha: mavzular, testlar, o'rtacha natija, davomat."""
    subjects = (await db.execute(select(Subject).order_by(Subject.title))).scalars().all()
    if not subjects:
        return []

    topic_rows = (
        await db.execute(
            select(Topic.subject_id, func.count(Topic.id)).group_by(Topic.subject_id)
        )
    ).all()
    topics_by_subject = {r[0]: r[1] for r in topic_rows}

    # Test natijalari fan bo'yicha — mavzu orqali bog'lanadi.
    quiz_rows = (
        await db.execute(
            select(
                Topic.subject_id,
                func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                func.count(QuizAttempt.id),
            )
            .join(QuizAttempt, QuizAttempt.topic_id == Topic.id)
            .where(QuizAttempt.status == QuizAttemptStatus.finished)
            .group_by(Topic.subject_id)
        )
    ).all()
    quiz_by_subject = {r[0]: (r[1], r[2], r[3]) for r in quiz_rows}

    attendance_rows = (
        await db.execute(
            select(AttendanceRecord.subject_id, AttendanceRecord.status)
        )
    ).all()
    attendance_by_subject: dict[int, list[int]] = {}
    for subject_id, status in attendance_rows:
        bucket = attendance_by_subject.setdefault(subject_id, [0, 0])
        bucket[1] += 1
        if status in ATTENDED:
            bucket[0] += 1

    exam_rows = (
        await db.execute(
            select(ExamAttempt.subject_id, func.count(ExamAttempt.id))
            .where(ExamAttempt.status != ExamStatus.in_progress)
            .group_by(ExamAttempt.subject_id)
        )
    ).all()
    exams_by_subject = {r[0]: r[1] for r in exam_rows}

    output = []
    for subject in subjects:
        correct, questions, attempts = quiz_by_subject.get(subject.id, (0, 0, 0))
        present, lessons = attendance_by_subject.get(subject.id, [0, 0])
        output.append({
            "subject_id": subject.id,
            "subject_title": subject.title,
            "topics": topics_by_subject.get(subject.id, 0),
            "quiz_attempts": attempts,
            "average_score": _score5(correct, questions),
            "accuracy": _pct(correct, questions),
            "attendance_percent": _pct(present, lessons),
            "attendance_total": lessons,
            "exam_attempts": exams_by_subject.get(subject.id, 0),
        })

    output.sort(key=lambda x: x["average_score"])
    return output


# ---------------------------------------------------------------------------
# E'tibor talab qiladigan talabalar
# ---------------------------------------------------------------------------

@router.get("/at-risk")
async def students_at_risk(
    limit: int = Query(50, ge=1, le=200),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Davomati past yoki natijasi past talabalar — ustoz e'tibori uchun.

    Har bir talaba uchun sabab(lar) ro'yxati qaytariladi, shuning uchun
    ilovada "nima uchun" degan savol tug'ilmaydi.
    """
    students = await _active_students(db)
    quiz = await _quiz_by_student(db)
    attendance = await _attendance_by_student(db)
    homework = await _homework_by_student(db)

    # Yuborilmagan vazifalar: umumiy vazifalar soni - talaba yuborganlari.
    total_homeworks = (
        await db.execute(select(func.count(Homework.id)).where(Homework.student_user_id.is_(None)))
    ).scalar() or 0

    output = []
    for student in students:
        reasons = []
        correct, questions, attempts = quiz.get(student.id, (0, 0, 0))
        present, lessons = attendance.get(student.id, (0, 0))
        _approved, submissions = homework.get(student.id, (0, 0))

        attendance_percent = _pct(present, lessons)
        score = _score5(correct, questions)

        if lessons >= 3 and attendance_percent < LOW_ATTENDANCE:
            reasons.append(f"Davomat past ({attendance_percent:.0f}%)")
        if attempts >= 2 and score < LOW_SCORE:
            reasons.append(f"Test natijasi past ({score:.1f}/5)")
        if total_homeworks >= 2 and submissions == 0:
            reasons.append("Vazifa yubormagan")
        if lessons == 0 and attempts == 0:
            reasons.append("Umuman faol emas")

        if not reasons:
            continue

        output.append({
            "student_user_id": student.id,
            "full_name": student.full_name,
            "student_group": student.student_group or "",
            "avatar_path": student.avatar_path,
            "attendance_percent": attendance_percent,
            "attendance_total": lessons,
            "average_score": score,
            "quiz_attempts": attempts,
            "submissions": submissions,
            "reasons": reasons,
            # Ko'proq sabab = ko'proq e'tibor kerak.
            "severity": len(reasons),
        })

    output.sort(key=lambda x: (-x["severity"], x["attendance_percent"], x["average_score"]))
    return output[:limit]


# ---------------------------------------------------------------------------
# Kunlik faollik
# ---------------------------------------------------------------------------

@router.get("/activity")
async def activity_series(
    days: int = Query(14, ge=7, le=90),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Oxirgi `days` kun uchun kunlik faollik.

    Sanalar Toshkent vaqti bo'yicha guruhlanadi (bazada UTC saqlanadi).
    """
    today = tashkent_date(utcnow()) or date_cls.today()
    start_day = today - timedelta(days=days - 1)
    window_start = utcnow() - timedelta(days=days + 1)

    series = {
        start_day + timedelta(days=i): {
            "date": (start_day + timedelta(days=i)).isoformat(),
            "quizzes": 0,
            "submissions": 0,
            "attendance": 0,
            "ai_questions": 0,
        }
        for i in range(days)
    }

    def bump(dt, key: str) -> None:
        day = tashkent_date(as_utc(dt))
        if day in series:
            series[day][key] += 1

    quiz_rows = (
        await db.execute(
            select(QuizAttempt.started_at).where(
                QuizAttempt.status == QuizAttemptStatus.finished,
                QuizAttempt.started_at >= window_start,
            )
        )
    ).scalars().all()
    for value in quiz_rows:
        bump(value, "quizzes")

    submission_rows = (
        await db.execute(
            select(HomeworkSubmission.submitted_at).where(
                HomeworkSubmission.submitted_at >= window_start
            )
        )
    ).scalars().all()
    for value in submission_rows:
        bump(value, "submissions")

    ai_rows = (
        await db.execute(
            select(NotificationLog.created_at).where(
                NotificationLog.event_type == "ai_question",
                NotificationLog.created_at >= window_start,
            )
        )
    ).scalars().all()
    for value in ai_rows:
        bump(value, "ai_questions")

    # Davomat sana bo'yicha saqlanadi — vaqt mintaqasi kerak emas.
    attendance_rows = (
        await db.execute(
            select(AttendanceRecord.lesson_date, func.count(AttendanceRecord.id))
            .where(AttendanceRecord.lesson_date >= start_day)
            .group_by(AttendanceRecord.lesson_date)
        )
    ).all()
    for lesson_date, count in attendance_rows:
        if lesson_date in series:
            series[lesson_date]["attendance"] = count

    return {
        "days": days,
        "from": start_day.isoformat(),
        "to": today.isoformat(),
        "series": [series[key] for key in sorted(series)],
    }


# ---------------------------------------------------------------------------
# Xodimlar faoliyati (faqat superadmin)
# ---------------------------------------------------------------------------

@router.get("/teachers")
async def teacher_activity(
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Har bir xodim nima qilgani — administrator nazorati uchun."""
    staff = (
        await db.execute(
            select(User)
            .where(User.role.in_([UserRole.employee, UserRole.superadmin]))
            .order_by(User.full_name)
        )
    ).scalars().all()
    if not staff:
        return []

    def counts(rows) -> dict:
        return {r[0]: r[1] for r in rows if r[0] is not None}

    topics = counts((
        await db.execute(
            select(Topic.employee_user_id, func.count(Topic.id))
            .group_by(Topic.employee_user_id)
        )
    ).all())

    homeworks = counts((
        await db.execute(
            select(Homework.created_by_user_id, func.count(Homework.id))
            .group_by(Homework.created_by_user_id)
        )
    ).all())

    graded = counts((
        await db.execute(
            select(
                Homework.created_by_user_id,
                func.count(HomeworkSubmission.id),
            )
            .join(Homework, Homework.id == HomeworkSubmission.homework_id)
            .where(HomeworkSubmission.graded_at.isnot(None))
            .group_by(Homework.created_by_user_id)
        )
    ).all())

    marked = counts((
        await db.execute(
            select(AttendanceRecord.marked_by_user_id, func.count(AttendanceRecord.id))
            .group_by(AttendanceRecord.marked_by_user_id)
        )
    ).all())

    return [
        {
            "id": member.id,
            "full_name": member.full_name,
            "role": member.role.value,
            "department": member.department,
            "avatar_path": member.avatar_path,
            "is_active": member.is_active,
            "last_active": iso(member.last_active),
            "topics": topics.get(member.id, 0),
            "homeworks": homeworks.get(member.id, 0),
            "graded_submissions": graded.get(member.id, 0),
            "attendance_marked": marked.get(member.id, 0),
        }
        for member in staff
    ]


# ---------------------------------------------------------------------------
# PDF hisobot
# ---------------------------------------------------------------------------

@router.get("/report/pdf")
async def analytics_report_pdf(
    student_group: Optional[str] = None,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Guruhlar va fanlar kesimidagi tahlilni PDF sifatida beradi."""
    groups = await analytics_by_group(_staff=staff, db=db)
    subjects = await analytics_by_subject(_staff=staff, db=db)
    at_risk = await students_at_risk(limit=25, _staff=staff, db=db)

    if student_group:
        groups = [g for g in groups if g["student_group"] == student_group]
        at_risk = [s for s in at_risk if s["student_group"] == student_group]

    try:
        filepath = pdf_service.generate_analytics_report(
            groups=groups, subjects=subjects, at_risk=at_risk
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Tahlil PDF xatosi: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename="Tahlil.pdf",
        background=_cleanup(filepath),
    )
