from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import (
    User,
    UserRole,
    QuizAttempt,
    QuizQuestion,
    Topic,
    TopicQuestionLog,
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

    qa_res = await db.execute(
        select(TopicQuestionLog)
        .where(TopicQuestionLog.student_user_id == student_id)
        .order_by(TopicQuestionLog.created_at.desc())
    )
    qa_logs = qa_res.scalars().all()

    qa_items = []
    for log in qa_logs:
        topic_res = await db.execute(select(Topic).where(Topic.id == log.topic_id))
        topic = topic_res.scalar_one_or_none()
        qa_items.append({
            "id": log.id,
            "topic_title": topic.title if topic else "O'chirilgan mavzu",
            "question": log.question_text,
            "answer": log.answer_text,
            "language": log.language,
            "date": log.created_at.isoformat(),
        })

    total_questions = sum(a.total_questions for a in attempts)
    correct_answers = sum(a.correct_answers for a in attempts)
    return {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "username": student.username,
            "role": student.role.value,
            "is_active": student.is_active,
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
