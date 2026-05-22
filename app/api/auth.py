from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.models import (
    User,
    UserRole,
    QuizAttempt,
    QuizQuestion,
    Topic,
)
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
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
async def list_students(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User)
        .where(User.role == UserRole.student)
        .order_by(User.created_at.desc())
    )
    students = result.scalars().all()

    output = []
    for student in students:
        attempts_res = await db.execute(
            select(QuizAttempt).where(QuizAttempt.student_user_id == student.id)
        )
        attempts = attempts_res.scalars().all()
        total_attempts = len(attempts)
        total_questions = sum(a.total_questions for a in attempts)
        correct_answers = sum(a.correct_answers for a in attempts)
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
    telegram_user_id: int
    full_name: str
    username: Optional[str] = None
    created_by_user_id: Optional[int] = None
    phone_number: Optional[str] = None
    student_group: Optional[str] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    birth_date: Optional[str] = None
    notes: Optional[str] = None

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
            full_name=req.full_name,
            username=req.username,
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
