import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Topic, KnowledgeChunk, User
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService
from pydantic import BaseModel
from typing import List, Dict

router = APIRouter()
ai_service = AIService()
pdf_service = PDFService()

class QuizStartRequest(BaseModel):
    topic_id: int

class QuizSubmitRequest(BaseModel):
    topic_id: int
    user_id: int
    answers: List[Dict] # List of {question_id: str, selected_option: str}

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
    quiz_json_raw = await ai_service.generate_quiz(context)
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

class QuizReportRequest(BaseModel):
    user_full_name: str
    topic_title: str
    results: List[Dict]
    score: int
    total: int

@router.post("/report/pdf")
async def get_pdf_report(request: QuizReportRequest):
    try:
        filepath = pdf_service.generate_quiz_report(
            request.user_full_name,
            request.topic_title,
            request.results,
            request.score,
            request.total
        )
        return FileResponse(
            filepath, 
            media_type="application/pdf", 
            filename=f"Natija_{request.topic_title}.pdf"
        )
    except Exception as e:
        print(f"PDF Generation Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF yaratishda xatolik yuz berdi: {str(e)}")
