import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.models import (
    Topic,
    KnowledgeChunk,
    User,
    UserRole,
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
    try:
        quiz_json_raw = await ai_service.generate_quiz(context, language=request.language)
    except Exception as e:
        err_msg = str(e)
        print(f"AI Generation Error: {e}")
        if "rate_limit" in err_msg.lower() or "429" in err_msg:
            raise HTTPException(
                status_code=429, 
                detail="Sun'iy intellekt xizmati band (Rate Limit). Iltimos, bir ozdan so'ng qayta urinib ko'ring."
            )
        raise HTTPException(
            status_code=502,
            detail=f"Sun'iy intellektdan javob olishda xatolik yuz berdi: {err_msg}"
        )

    try:
        # Clean up JSON if AI returned it with markdown blocks
        if "```json" in quiz_json_raw:
            quiz_json_raw = quiz_json_raw.split("```json")[1].split("```")[0].strip()
        elif "```" in quiz_json_raw:
            quiz_json_raw = quiz_json_raw.split("```")[1].split("```")[0].strip()
            
        quiz_data = json.loads(quiz_json_raw)
        
        # Robust unwrapping if AI returned an object instead of a direct list
        if isinstance(quiz_data, dict):
            found_list = None
            # 1. Search for standard keys
            for key in ["questions", "quiz", "test", "savollar", "savol"]:
                if key in quiz_data and isinstance(quiz_data[key], list):
                    found_list = quiz_data[key]
                    break
            
            # 2. Search for any key holding a list of dicts/questions
            if found_list is None:
                for key, val in quiz_data.items():
                    if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                        found_list = val
                        break
            
            # 3. If it's a dict containing questions as values (e.g. {"1": {...}, "2": {...}})
            if found_list is None:
                vals = list(quiz_data.values())
                if len(vals) > 0 and isinstance(vals[0], dict) and ("question" in vals[0] or "options" in vals[0]):
                    found_list = vals
            
            if found_list is not None:
                quiz_data = found_list
                
        if not isinstance(quiz_data, list):
            raise ValueError("Parsed JSON is not a list of questions.")
            
        return quiz_data
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        print(f"Raw AI Output: {quiz_json_raw}")
        raise HTTPException(
            status_code=422, 
            detail=f"Test savollarini o'qishda (JSON parse) xatolik yuz berdi: {str(e)}"
        )


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

    qa_items = await _load_ai_questions(db, student_id)

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
