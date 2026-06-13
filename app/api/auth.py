from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from app.database import get_db
from app.models import (
    User,
    UserRole,
    QuizAttempt,
    QuizQuestion,
    Topic,
    HomeworkSubmission,
    ClinicalArenaAttempt,
)
from pydantic import BaseModel, Field
from jose import jwt
from datetime import datetime, timedelta, timezone
import os

router = APIRouter(redirect_slashes=True)

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 1 week

class LoginRequest(BaseModel):
    telegram_id: int

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.telegram_user_id == req.telegram_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "role": user.role.value
        }
    }

@router.get("/students")
async def list_students(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.role == UserRole.student)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    students = result.scalars().all()

    # Aggregate quiz stats for the whole page in a single query (avoids N+1).
    student_ids = [s.id for s in students]
    quiz_map: dict[int, tuple[int, int, int]] = {}
    if student_ids:
        quiz_rows = await db.execute(
            select(
                QuizAttempt.student_user_id,
                func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                func.count(QuizAttempt.id),
            )
            .where(QuizAttempt.student_user_id.in_(student_ids))
            .group_by(QuizAttempt.student_user_id)
        )
        quiz_map = {row[0]: (row[1], row[2], row[3]) for row in quiz_rows.all()}

    output = []
    for student in students:
        correct_answers, total_questions, total_attempts = quiz_map.get(student.id, (0, 0, 0))
        output.append({
            "id": student.id,
            "full_name": student.full_name,
            "username": student.username,
            "is_active": student.is_active,
            "phone_number": student.phone_number,
            "student_group": student.student_group,
            "parent_name": student.parent_name,
            "parent_phone": student.parent_phone,
            "birth_date": student.birth_date,
            "notes": student.notes,
            "created_at": student.created_at.isoformat(),
            "attempts_count": total_attempts,
            "questions_count": total_questions,
            "correct_answers": correct_answers,
        })
    return output

@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.role == UserRole.student)
    )
    students = result.scalars().all()

    # Aggregate all per-student stats in three grouped queries instead of
    # running three queries per student (eliminates the N+1 pattern).
    quiz_rows = await db.execute(
        select(
            QuizAttempt.student_user_id,
            func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
            func.coalesce(func.sum(QuizAttempt.total_questions), 0),
            func.count(QuizAttempt.id),
        ).group_by(QuizAttempt.student_user_id)
    )
    quiz_map = {row[0]: (row[1], row[2], row[3]) for row in quiz_rows.all()}

    hw_rows = await db.execute(
        select(
            HomeworkSubmission.student_user_id,
            func.count(HomeworkSubmission.id),
        )
        .where(HomeworkSubmission.status == "approved")
        .group_by(HomeworkSubmission.student_user_id)
    )
    hw_map = {row[0]: row[1] for row in hw_rows.all()}

    arena_rows = await db.execute(
        select(
            ClinicalArenaAttempt.student_user_id,
            func.coalesce(func.sum(ClinicalArenaAttempt.points_awarded), 0),
        ).group_by(ClinicalArenaAttempt.student_user_id)
    )
    arena_map = {row[0]: row[1] for row in arena_rows.all()}

    leaderboard = []
    for student in students:
        correct_answers, total_questions, attempts_count = quiz_map.get(student.id, (0, 0, 0))
        approved_subs = hw_map.get(student.id, 0)
        arena_points = arena_map.get(student.id, 0)

        points = (correct_answers * 10) + (approved_subs * 25) + arena_points
        accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0.0

        leaderboard.append({
            "id": student.id,
            "full_name": student.full_name,
            "student_group": student.student_group or "Noma'lum guruh",
            "username": student.username,
            "points": points,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "accuracy": round(accuracy, 1),
            "approved_homeworks": approved_subs,
            "attempts_count": attempts_count,
        })

    leaderboard.sort(key=lambda x: (x["points"], x["accuracy"]), reverse=True)

    for idx, item in enumerate(leaderboard):
        item["rank"] = idx + 1

    # Ranks are assigned across the full set; slice for the requested page
    # while preserving the list response shape the app expects.
    return leaderboard[offset:offset + limit]

@router.get("/students/{student_id}/overview")
async def student_overview(student_id: int, db: AsyncSession = Depends(get_db)):
    user_res = await db.execute(select(User).where(User.id == student_id))
    student = user_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    attempts_res = await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.student_user_id == student_id)
        .order_by(QuizAttempt.started_at.desc())
    )
    attempts = attempts_res.scalars().all()

    attempt_items = []
    for attempt in attempts:
        topic_res = await db.execute(select(Topic).where(Topic.id == attempt.topic_id))
        topic = topic_res.scalar_one_or_none()
        questions_res = await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_attempt_id == attempt.id)
            .order_by(QuizQuestion.question_order)
        )
        questions = questions_res.scalars().all()
        attempt_items.append({
            "id": attempt.id,
            "topic_title": topic.title if topic else "O'chirilgan mavzu",
            "score": attempt.correct_answers,
            "total": attempt.total_questions,
            "date": attempt.started_at.isoformat(),
            "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
            "duration_seconds": _duration_seconds(attempt),
            "results": [
                {
                    "question": q.question_text,
                    "correct_option": q.expected_answer,
                    "user_answer": q.student_answer,
                    "is_correct": q.is_correct,
                    "explanation": q.feedback_text or "",
                }
                for q in questions
            ],
        })

    qa_items = await _load_ai_questions(db, student_id)

    total_questions = sum(a.total_questions for a in attempts)
    correct_answers = sum(a.correct_answers for a in attempts)
    return {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "username": student.username,
            "role": student.role.value,
            "is_active": student.is_active,
            "phone_number": student.phone_number,
            "student_group": student.student_group,
            "parent_name": student.parent_name,
            "parent_phone": student.parent_phone,
            "birth_date": student.birth_date,
            "notes": student.notes,
            "created_at": student.created_at.isoformat(),
        },
        "summary": {
            "attempts_count": len(attempts),
            "questions_count": total_questions,
            "correct_answers": correct_answers,
            "ai_questions_count": len(qa_items),
        },
        "attempts": attempt_items,
        "ai_questions": qa_items,
    }

def _duration_seconds(attempt: QuizAttempt):
    if not attempt.started_at or not attempt.finished_at:
        return None
    return max(int((attempt.finished_at - attempt.started_at).total_seconds()), 0)

async def _load_ai_questions(db: AsyncSession, student_id: int):
    try:
        table_res = await db.execute(text("select to_regclass('public.notification_logs')"))
        if table_res.scalar_one_or_none() is None:
            return []

        result = await db.execute(
            text("""
                select id, payload, created_at
                from notification_logs
                where user_id = :student_id and event_type = 'ai_question'
                order by created_at desc
            """),
            {"student_id": student_id},
        )
    except Exception:
        return []

    import json
    items = []
    for row in result.mappings().all():
        payload = row["payload"] or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        topic_id = payload.get("topic_id")
        topic = None
        if topic_id:
            topic_res = await db.execute(select(Topic).where(Topic.id == topic_id))
            topic = topic_res.scalar_one_or_none()
        items.append({
            "id": row["id"],
            "topic_title": topic.title if topic else "Mavzu",
            "question": payload.get("question", ""),
            "answer": payload.get("answer", ""),
            "language": payload.get("language", "uz"),
            "date": row["created_at"].isoformat(),
        })
    return items

from typing import Optional

class StudentCreateRequest(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    full_name: str = Field(..., min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)
    created_by_user_id: Optional[int] = None
    phone_number: Optional[str] = Field(default=None, max_length=50)
    student_group: Optional[str] = Field(default=None, max_length=100)
    parent_name: Optional[str] = Field(default=None, max_length=255)
    parent_phone: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)

@router.post("/students")
async def create_student(req: StudentCreateRequest, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where(User.telegram_user_id == req.telegram_user_id))
    existing = res.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Bu Telegram ID ga ega student allaqachon mavjud."
        )
    
    try:
        new_student = User(
            telegram_user_id=req.telegram_user_id,
            full_name=req.full_name.strip(),
            username=req.username.strip() if req.username else None,
            role=UserRole.student,
            created_by_user_id=req.created_by_user_id,
            phone_number=req.phone_number,
            student_group=req.student_group,
            parent_name=req.parent_name,
            parent_phone=req.parent_phone,
            birth_date=req.birth_date,
            notes=req.notes,
            is_active=True
        )
        db.add(new_student)
        await db.commit()
        await db.refresh(new_student)
        
        return {
            "status": "success",
            "student": {
                "id": new_student.id,
                "full_name": new_student.full_name,
                "username": new_student.username,
                "telegram_user_id": new_student.telegram_user_id,
                "role": new_student.role.value,
                "is_active": new_student.is_active,
                "phone_number": new_student.phone_number,
                "student_group": new_student.student_group,
                "parent_name": new_student.parent_name,
                "parent_phone": new_student.parent_phone,
                "birth_date": new_student.birth_date,
                "notes": new_student.notes,
                "created_at": new_student.created_at.isoformat()
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Student yaratishda xatolik yuz berdi: {str(e)}")

@router.get("/students/{student_id}/academic-stats")
async def student_academic_stats(student_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where(User.id == student_id))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    quiz_res = await db.execute(
        select(QuizAttempt).where(QuizAttempt.student_user_id == student_id)
    )
    quiz_attempts = quiz_res.scalars().all()
    
    sum_correct = sum(q.correct_answers for q in quiz_attempts)
    sum_total = sum(q.total_questions for q in quiz_attempts)
    quiz_avg = round((sum_correct / sum_total * 5.0), 2) if sum_total > 0 else 0.0
    
    hw_res = await db.execute(
        select(HomeworkSubmission).where(
            (HomeworkSubmission.student_user_id == student_id) &
            (HomeworkSubmission.status == "approved")
        )
    )
    hw_submissions = hw_res.scalars().all()
    
    hw_grades = []
    for sub in hw_submissions:
        if sub.grade:
            try:
                val = float(sub.grade)
                hw_grades.append(val)
            except ValueError:
                pass
    hw_avg = round((sum(hw_grades) / len(hw_grades)), 2) if hw_grades else 0.0
    
    arena_res = await db.execute(
        select(ClinicalArenaAttempt).where(ClinicalArenaAttempt.student_user_id == student_id)
    )
    arena_attempts = arena_res.scalars().all()
    
    arena_duels_won = sum(1 for a in arena_attempts if a.mode == "duel" and a.is_winner)
    arena_duels_lost = sum(1 for a in arena_attempts if a.mode == "duel" and not a.is_winner)
    arena_cases_solved = sum(1 for a in arena_attempts if a.mode == "case" and a.is_winner)
    
    combined_avg = 0.0
    total_metrics = 0
    if sum_total > 0:
        combined_avg += quiz_avg
        total_metrics += 1
    if hw_grades:
        combined_avg += hw_avg
        total_metrics += 1
        
    gpa = combined_avg / total_metrics if total_metrics > 0 else 0.0
    if gpa >= 4.5:
        standing = "A'lochi / Excellent"
    elif gpa >= 3.8:
        standing = "Yaxshi / Good"
    elif gpa >= 3.0:
        standing = "Qoniqarli / Satisfactory"
    else:
        standing = "Qoniqarsiz / Needs Improvement" if total_metrics > 0 else "Noma'lum / No grades yet"
        
    return {
        "student_id": student_id,
        "quiz_avg": quiz_avg,
        "homework_avg": hw_avg,
        "arena_duels_won": arena_duels_won,
        "arena_duels_lost": arena_duels_lost,
        "arena_cases_solved": arena_cases_solved,
        "standing": standing,
        "total_quizzes_taken": len(quiz_attempts),
        "total_homeworks_graded": len(hw_grades)
    }


TASHKENT_OFFSET = timedelta(hours=5)


def _tashkent_date(dt):
    """Return the calendar date in Tashkent time for a (possibly naive UTC) datetime."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return (dt + TASHKENT_OFFSET).date()


@router.get("/students/{student_id}/gamification")
async def student_gamification(student_id: int, db: AsyncSession = Depends(get_db)):
    """Derive XP, level, daily streak and today's goal from existing activity."""
    res = await db.execute(select(User).where(User.id == student_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    quiz_rows = (await db.execute(
        select(QuizAttempt.correct_answers, QuizAttempt.started_at)
        .where(QuizAttempt.student_user_id == student_id)
    )).all()
    hw_rows = (await db.execute(
        select(HomeworkSubmission.status, HomeworkSubmission.submitted_at)
        .where(HomeworkSubmission.student_user_id == student_id)
    )).all()
    arena_rows = (await db.execute(
        select(ClinicalArenaAttempt.points_awarded, ClinicalArenaAttempt.created_at)
        .where(ClinicalArenaAttempt.student_user_id == student_id)
    )).all()

    correct = sum((r[0] or 0) for r in quiz_rows)
    approved = sum(1 for r in hw_rows if r[0] == "approved")
    arena_points = sum((r[0] or 0) for r in arena_rows)
    xp = correct * 10 + approved * 25 + arena_points

    # Level curve: xp needed for level n floor = 50*(n-1)^2
    level = int((xp / 50) ** 0.5) + 1
    floor_current = 50 * (level - 1) ** 2
    floor_next = 50 * level ** 2
    xp_in_level = xp - floor_current
    xp_for_next = floor_next - floor_current
    progress = round(xp_in_level / xp_for_next, 3) if xp_for_next > 0 else 0.0

    # Active days (Tashkent) across all activity types -> consecutive streak.
    active_days = set()
    for r in quiz_rows:
        d = _tashkent_date(r[1])
        if d:
            active_days.add(d)
    for r in hw_rows:
        d = _tashkent_date(r[1])
        if d:
            active_days.add(d)
    for r in arena_rows:
        d = _tashkent_date(r[1])
        if d:
            active_days.add(d)

    today = _tashkent_date(datetime.utcnow())
    cursor = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    done_today = sum(1 for r in quiz_rows if _tashkent_date(r[1]) == today)
    daily_target = 1

    return {
        "student_id": student_id,
        "xp": xp,
        "level": level,
        "xp_in_level": xp_in_level,
        "xp_for_next": xp_for_next,
        "progress": progress,
        "streak": streak,
        "daily_goal": {
            "target": daily_target,
            "done_today": done_today,
            "completed": done_today >= daily_target,
        },
    }
