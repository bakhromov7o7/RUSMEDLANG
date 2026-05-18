import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import (
    Topic,
    KnowledgeChunk,
    User,
    UserRole,
    TopicQuestionLog,
)
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService
from pydantic import BaseModel
from typing import List, Dict, Optional

router = APIRouter()
ai_service = AIService()
pdf_service = PDFService()

class QuizStartRequest(BaseModel):
    topic_id: int
    language: str = "uz"

class QuizSubmitRequest(BaseModel):
    topic_id: int
    user_id: int
    answers: List[Dict] # List of {question_id: str, selected_option: str}
    elapsed_seconds: Optional[int] = None

@router.post("/generate")
async def generate_quiz(request: QuizStartRequest, db: AsyncSession = Depends(get_db)):
    # 1. Get Topic and Context
    result = await db.execute(select(Topic).where(Topic.id == request.topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    chunks_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.topic_id == request.topic_id).limit(10)
    )
    chunks = chunks_result.scalars().all()
    context = "\n".join([c.chunk_text for c in chunks])
    
    if not context:
        raise HTTPException(status_code=400, detail="No content available for this topic to generate quiz.")
    
    # 2. Generate Quiz using AI
    quiz_json_raw = await ai_service.generate_quiz(context, language=request.language)
    try:
        # Clean up JSON if AI returned it with markdown blocks
        if "```json" in quiz_json_raw:
            quiz_json_raw = quiz_json_raw.split("```json")[1].split("```")[0].strip()
        elif "```" in quiz_json_raw:
            quiz_json_raw = quiz_json_raw.split("```")[1].split("```")[0].strip()
            
        quiz_data = json.loads(quiz_json_raw)
        # If AI returned an object with a key (like "questions"), unwrap it
        if isinstance(quiz_data, dict):
            for key in ["questions", "quiz", "test"]:
                if key in quiz_data:
                    quiz_data = quiz_data[key]
                    break
        return quiz_data
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        print(f"Raw AI Output: {quiz_json_raw}")
        raise HTTPException(status_code=500, detail="Failed to parse AI generated quiz.")

from app.models import QuizAttempt, QuizQuestion

@router.post("/submit")
async def submit_quiz(req: QuizSubmitRequest, db: AsyncSession = Depends(get_db)):
    # 1. Fetch user and topic (validation)
    result = await db.execute(select(Topic).where(Topic.id == req.topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # 2. Create QuizAttempt
    finished_at = datetime.utcnow()
    elapsed_seconds = max(req.elapsed_seconds or 0, 0)
    started_at = finished_at - timedelta(seconds=elapsed_seconds) if elapsed_seconds else finished_at

    attempt = QuizAttempt(
        student_user_id=req.user_id,
        topic_id=req.topic_id,
        employee_user_id=topic.employee_user_id,
        total_questions=len(req.answers),
        correct_answers=0,
        started_at=started_at,
        finished_at=finished_at
    )
    db.add(attempt)
    await db.flush()

    correct_count = 0
    for i, ans in enumerate(req.answers):
        is_correct = ans.get('is_correct', False)
        if is_correct: correct_count += 1
        
        q = QuizQuestion(
            quiz_attempt_id=attempt.id,
            question_order=i,
            question_text=ans.get('question', ''),
            expected_answer=ans.get('correct_option', ''),
            student_answer=ans.get('user_answer', ''),
            is_correct=is_correct,
            feedback_text=ans.get('explanation', ''),
            checked_at=finished_at
        )
        db.add(q)
    
    attempt.correct_answers = correct_count
    await db.commit()
    
    return {
        "status": "success",
        "attempt_id": attempt.id,
        "score": correct_count,
        "elapsed_seconds": elapsed_seconds
    }

@router.get("/report/pdf")
async def get_pdf_report_by_id(attempt_id: int, db: AsyncSession = Depends(get_db)):
    try:
        # Fetch attempt and user data
        result = await db.execute(
            select(QuizAttempt).where(QuizAttempt.id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt not found")
            
        topic_res = await db.execute(select(Topic).where(Topic.id == attempt.topic_id))
        topic = topic_res.scalar_one()
        
        user_res = await db.execute(select(User).where(User.id == attempt.student_user_id))
        user = user_res.scalar_one()
        
        questions_res = await db.execute(
            select(QuizQuestion).where(QuizQuestion.quiz_attempt_id == attempt_id).order_by(QuizQuestion.question_order)
        )
        questions = questions_res.scalars().all()
        
        results = []
        for q in questions:
            results.append({
                "question": q.question_text,
                "correct_option": q.expected_answer,
                "user_answer": q.student_answer,
                "is_correct": q.is_correct
            })

        filepath = pdf_service.generate_quiz_report(
            user.full_name,
            topic.title,
            results,
            attempt.correct_answers,
            attempt.total_questions
        )
        return FileResponse(
            filepath, 
            media_type="application/pdf", 
            filename=f"Natija_{topic.title}.pdf"
        )
    except Exception as e:
        print(f"PDF Generation Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF yaratishda xatolik yuz berdi: {str(e)}")

@router.get("/history/{user_id}")
async def get_quiz_history(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.student_user_id == user_id)
        .order_by(QuizAttempt.started_at.desc())
    )
    attempts = result.scalars().all()
    
    output = []
    for a in attempts:
        topic_res = await db.execute(select(Topic).where(Topic.id == a.topic_id))
        topic = topic_res.scalar_one_or_none()
        output.append({
            "id": a.id,
            "topic_title": topic.title if topic else "O'chirilgan mavzu",
            "score": a.correct_answers,
            "total": a.total_questions,
            "date": a.started_at.isoformat(),
            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
            "duration_seconds": _duration_seconds(a)
        })
    return output

@router.get("/attempt/{attempt_id}")
async def get_quiz_attempt(attempt_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    topic_res = await db.execute(select(Topic).where(Topic.id == attempt.topic_id))
    topic = topic_res.scalar_one_or_none()

    user_res = await db.execute(select(User).where(User.id == attempt.student_user_id))
    user = user_res.scalar_one_or_none()

    questions_res = await db.execute(
        select(QuizQuestion)
        .where(QuizQuestion.quiz_attempt_id == attempt_id)
        .order_by(QuizQuestion.question_order)
    )
    questions = questions_res.scalars().all()

    return {
        "id": attempt.id,
        "student": {
            "id": user.id if user else attempt.student_user_id,
            "full_name": user.full_name if user else "Noma'lum student",
            "username": user.username if user else None,
        },
        "topic_id": attempt.topic_id,
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
    }

def _duration_seconds(attempt: QuizAttempt) -> Optional[int]:
    if not attempt.started_at or not attempt.finished_at:
        return None
    return max(int((attempt.finished_at - attempt.started_at).total_seconds()), 0)

@router.get("/students")
async def list_quiz_students(db: AsyncSession = Depends(get_db)):
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
        output.append({
            "id": student.id,
            "full_name": student.full_name,
            "username": student.username,
            "is_active": student.is_active,
            "created_at": student.created_at.isoformat(),
            "attempts_count": len(attempts),
            "questions_count": sum(a.total_questions for a in attempts),
            "correct_answers": sum(a.correct_answers for a in attempts),
        })
    return output

@router.get("/students/{student_id}/overview")
async def quiz_student_overview(student_id: int, db: AsyncSession = Depends(get_db)):
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
            "questions_count": sum(a.total_questions for a in attempts),
            "correct_answers": sum(a.correct_answers for a in attempts),
            "ai_questions_count": len(qa_items),
        },
        "attempts": attempt_items,
        "ai_questions": qa_items,
    }
