import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.models import (
    Topic,
    TopicMaterial,
    KnowledgeChunk,
    User,
    MaterialType,
    TopicStatus,
    UserRole,
    StudentSession,
    SessionState,
    Subject,
)
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter(redirect_slashes=True)
ai_service = AIService()
pdf_service = PDFService()
QUESTION_LIMIT = 10

class TopicCreateRequest(BaseModel):
    employee_id: int
    subject_id: Optional[int] = None
    title: str
    description: Optional[str] = ""
    video_url: Optional[str] = ""
    video_urls: Optional[List[str]] = []
    topic_type: Optional[str] = "leksika"
    content: str # The main text content

class SubjectCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""

class TopicAskRequest(BaseModel):
    question: str
    user_id: Optional[int] = None
    language: str = "uz"

@router.post("/")
async def create_topic(req: TopicCreateRequest, db: AsyncSession = Depends(get_db)):
    # 1. Verify employee
    result = await db.execute(
        select(User).where(User.id == req.employee_id)
    )
    employee = result.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with ID {req.employee_id} not found")
    
    if employee.role not in [UserRole.employee, UserRole.superadmin]:
        raise HTTPException(status_code=403, detail="Only employees can create topics")

    try:
        # 2. Create Topic
        topic = Topic(
            employee_user_id=employee.id,
            subject_id=req.subject_id,
            title=req.title,
            description=req.description,
            topic_type=req.topic_type or "leksika",
            status=TopicStatus.active
        )
        db.add(topic)
        await db.flush()

        # 3. Add Video Materials
        urls = list(req.video_urls) if req.video_urls else []
        if req.video_url and req.video_url not in urls:
            urls.insert(0, req.video_url)

        for i, url in enumerate(urls):
            if url.strip():
                video_material = TopicMaterial(
                    topic_id=topic.id,
                    uploaded_by_user_id=employee.id,
                    material_type=MaterialType.video,
                    title=f"{req.title} - Video {i+1}",
                    source_url=url.strip()
                )
                db.add(video_material)

        # 4. Add Text Material
        text_material = TopicMaterial(
            topic_id=topic.id,
            uploaded_by_user_id=employee.id,
            material_type=MaterialType.text,
            title=f"{req.title} - Content",
            raw_text=req.content
        )
        db.add(text_material)
        await db.flush()

        # 5. Chunk the content into KnowledgeChunks
        paragraphs = [p.strip() for p in req.content.split("\n\n") if p.strip()]
        for i, p in enumerate(paragraphs):
            chunk = KnowledgeChunk(
                topic_id=topic.id,
                material_id=text_material.id,
                chunk_index=i,
                chunk_text=p
            )
            db.add(chunk)

        await db.commit()
    except Exception as e:
        await db.rollback()
        logging.error(f"Error creating topic: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "success", "topic_id": topic.id}

from sqlalchemy.orm import selectinload

@router.get("/")
async def list_topics(subject_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Topic).options(selectinload(Topic.materials))
    if subject_id:
        stmt = stmt.where(Topic.subject_id == subject_id)
    result = await db.execute(stmt.order_by(Topic.created_at.desc()))
    topics = result.scalars().all()
    
    # Manually serialize to include materials source_url and content
    output = []
    for t in topics:
        video_materials = [m for m in t.materials if m.material_type == MaterialType.video]
        video_urls = [v.source_url for v in video_materials if v.source_url]
        text = next((m for m in t.materials if m.material_type == MaterialType.text), None)
        output.append({
            "id": t.id,
            "subject_id": t.subject_id,
            "title": t.title,
            "description": t.description,
            "topic_type": t.topic_type or "leksika",
            "status": t.status.value if t.status else "draft",
            "video_url": video_urls[0] if video_urls else None,
            "video_urls": video_urls,
            "content": text.raw_text if text else ""
        })
    return output

@router.get("/subjects")
async def list_subjects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subject).order_by(Subject.title))
    subjects = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "description": s.description or "",
            "created_at": s.created_at.isoformat()
        }
        for s in subjects
    ]

@router.post("/subjects")
async def create_subject(req: SubjectCreateRequest, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Subject).where(Subject.title == req.title))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bunday fan allaqachon mavjud.")
        
    try:
        subject = Subject(
            title=req.title,
            description=req.description
        )
        db.add(subject)
        await db.commit()
        await db.refresh(subject)
        return {
            "status": "success",
            "subject": {
                "id": subject.id,
                "title": subject.title,
                "description": subject.description
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Fan yaratishda xatolik yuz berdi: {str(e)}")

async def _topic_content(db: AsyncSession, topic_id: int):
    result = await db.execute(
        select(Topic)
        .options(selectinload(Topic.materials))
        .where(Topic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    text = next((m for m in topic.materials if m.material_type == MaterialType.text), None)
    chunks_result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.topic_id == topic_id)
        .order_by(KnowledgeChunk.chunk_index)
        .limit(20)
    )
    chunks = chunks_result.scalars().all()
    content = "\n\n".join([c.chunk_text for c in chunks]) or (text.raw_text if text else "") or topic.description or ""
    return topic, content

@router.get("/{topic_id}/translation")
async def translate_topic(topic_id: int, language: str = "ru", db: AsyncSession = Depends(get_db)):
    topic, content = await _topic_content(db, topic_id)
    translated = await ai_service.translate_topic(topic.title, content, language)
    return {
        "language": language,
        "title": translated["title"],
        "content": translated["content"],
    }

@router.get("/{topic_id}/pdf")
async def get_topic_pdf(topic_id: int, language: str = "uz", db: AsyncSession = Depends(get_db)):
    try:
        topic, content = await _topic_content(db, topic_id)
        title = topic.title
        
        if language == "ru":
            translated = await ai_service.translate_topic(topic.title, content, language)
            title = translated["title"]
            content = translated["content"]
            
        filepath = pdf_service.generate_topic_pdf(title, content)
        return FileResponse(
            filepath, 
            media_type="application/pdf", 
            filename=f"Mavzu_{title}.pdf"
        )
    except Exception as e:
        logging.error(f"PDF Generation Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF yaratishda xatolik yuz berdi: {str(e)}")

@router.post("/{topic_id}/ask")
async def ask_topic(topic_id: int, req: TopicAskRequest, db: AsyncSession = Depends(get_db)):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    topic, content = await _topic_content(db, topic_id)
    if not content.strip():
        raise HTTPException(status_code=400, detail="No content available for this topic.")

    session = None
    if req.user_id:
        result = await db.execute(
            select(StudentSession).where(StudentSession.student_user_id == req.user_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            session = StudentSession(
                student_user_id=req.user_id,
                topic_id=topic.id,
                state=SessionState.asking,
                question_count=0,
            )
            db.add(session)
            await db.flush()
        elif session.topic_id != topic.id:
            session.topic_id = topic.id
            session.question_count = 0

        # Query global questions asked by the user today (Tashkent timezone: GMT+5)
        try:
            count_res = await db.execute(
                text("""
                    select count(*) 
                    from notification_logs 
                    where user_id = :user_id 
                      and event_type = 'ai_question' 
                      and created_at >= date_trunc('day', now() at time zone 'Asia/Tashkent')
                """),
                {"user_id": req.user_id}
            )
            questions_today = count_res.scalar_one_or_none() or 0
        except Exception as e:
            logging.error(f"Error querying notification_logs limit: {e}")
            # Fallback to session-based count if the logs table cannot be queried
            questions_today = session.question_count

        if questions_today >= QUESTION_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Kunlik savollar limiti tugadi (maksimal 10 ta).",
                    "limit": QUESTION_LIMIT,
                    "remaining": 0,
                },
            )

    answer = await ai_service.answer_topic_question(content, question, req.language)

    remaining = QUESTION_LIMIT
    used = 0
    if session:
        session.question_count += 1
        session.state = SessionState.asking
        session.last_user_message = question
        await _log_ai_question(db, req.user_id, topic.id, question, answer, req.language)
        await db.commit()

        # Recalculate used and remaining based on global logs
        try:
            count_res = await db.execute(
                text("""
                    select count(*) 
                    from notification_logs 
                    where user_id = :user_id 
                      and event_type = 'ai_question' 
                      and created_at >= date_trunc('day', now() at time zone 'Asia/Tashkent')
                """),
                {"user_id": req.user_id}
            )
            used = count_res.scalar_one_or_none() or 0
        except Exception:
            used = session.question_count

        remaining = max(QUESTION_LIMIT - used, 0)

    return {
        "answer": answer,
        "limit": QUESTION_LIMIT,
        "used": used,
        "remaining": remaining,
    }

async def _log_ai_question(
    db: AsyncSession,
    student_user_id: int,
    topic_id: int,
    question: str,
    answer: str,
    language: str,
):
    try:
        table_res = await db.execute(text("select to_regclass('public.notification_logs')"))
        if table_res.scalar_one_or_none() is None:
            return
        async with db.begin_nested():
            await db.execute(
                text("""
                    insert into notification_logs (user_id, event_type, payload)
                    values (:user_id, 'ai_question', cast(:payload as jsonb))
                """),
                {
                    "user_id": student_user_id,
                    "payload": json_dumps({
                        "topic_id": topic_id,
                        "question": question,
                        "answer": answer,
                        "language": language,
                    }),
                },
            )
    except Exception:
        logging.info("AI question log skipped; notification_logs is unavailable", exc_info=True)

def json_dumps(value: dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)

@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete, update
    from app.models import StudentTopicAccess, UserState, StudentSession, QuizAttempt, TopicMaterial, KnowledgeChunk
    
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
        
    try:
        # Delete related quiz attempts (cascade deletes quiz questions)
        await db.execute(delete(QuizAttempt).where(QuizAttempt.topic_id == topic_id))
        
        # Nullify user state references to this topic
        await db.execute(
            update(UserState)
            .where((UserState.pending_topic_id == topic_id) | (UserState.active_topic_id == topic_id))
            .values(pending_topic_id=None, active_topic_id=None)
        )
        
        # Nullify student session references to this topic
        await db.execute(
            update(StudentSession)
            .where(StudentSession.topic_id == topic_id)
            .values(topic_id=None)
        )
        
        # Delete student topic access records
        await db.execute(delete(StudentTopicAccess).where(StudentTopicAccess.topic_id == topic_id))
        
        # Delete knowledge chunks
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id == topic_id))
        
        # Delete materials
        await db.execute(delete(TopicMaterial).where(TopicMaterial.topic_id == topic_id))
        
        # Delete topic itself
        await db.delete(topic)
        await db.commit()
        return {"status": "deleted"}
    except Exception as e:
        await db.rollback()
        logging.error(f"Error deleting topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Mavzuni o'chirishda xatolik yuz berdi: {str(e)}"
        )

@router.put("/{topic_id}")
async def update_topic(topic_id: int, req: TopicCreateRequest, db: AsyncSession = Depends(get_db)):
    # 1. Fetch Topic
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # 2. Update Topic fields
    topic.title = req.title
    topic.description = req.description
    topic.subject_id = req.subject_id
    topic.topic_type = req.topic_type or "leksika"
    
    # 3. Update Video Materials (Delete old and insert new)
    from sqlalchemy import delete
    await db.execute(delete(TopicMaterial).where(
        TopicMaterial.topic_id == topic_id, 
        TopicMaterial.material_type == MaterialType.video
    ))
    
    urls = list(req.video_urls) if req.video_urls else []
    if req.video_url and req.video_url not in urls:
        urls.insert(0, req.video_url)
        
    for i, url in enumerate(urls):
        if url.strip():
            video_material = TopicMaterial(
                topic_id=topic_id,
                uploaded_by_user_id=req.employee_id,
                material_type=MaterialType.video,
                title=f"{req.title} - Video {i+1}",
                source_url=url.strip()
            )
            db.add(video_material)

    # 4. Update Text Material and Chunks
    result = await db.execute(select(TopicMaterial).where(
        TopicMaterial.topic_id == topic_id, 
        TopicMaterial.material_type == MaterialType.text
    ))
    text_material = result.scalar_one_or_none()
    if text_material:
        text_material.raw_text = req.content
        text_material.title = f"{req.title} - Content"
        
        # Clear old chunks and re-chunk
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id == topic_id))
        paragraphs = [p.strip() for p in req.content.split("\n\n") if p.strip()]
        for i, p in enumerate(paragraphs):
            chunk = KnowledgeChunk(
                topic_id=topic.id,
                material_id=text_material.id,
                chunk_index=i,
                chunk_text=p
            )
            db.add(chunk)

    await db.commit()
    return {"status": "updated"}

@router.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete, update
    from app.models import StudentTopicAccess, UserState, StudentSession, QuizAttempt, TopicMaterial, KnowledgeChunk
    
    result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Fan topilmadi")
        
    try:
        # Find all topics under this subject
        topics_res = await db.execute(select(Topic).where(Topic.subject_id == subject_id))
        topics_list = topics_res.scalars().all()
        topic_ids = [t.id for t in topics_list]
        
        if topic_ids:
            # Delete related quiz attempts for all these topics
            await db.execute(delete(QuizAttempt).where(QuizAttempt.topic_id.in_(topic_ids)))
            
            # Nullify user states
            await db.execute(
                update(UserState)
                .where((UserState.pending_topic_id.in_(topic_ids)) | (UserState.active_topic_id.in_(topic_ids)))
                .values(pending_topic_id=None, active_topic_id=None)
            )
            
            # Nullify student sessions
            await db.execute(
                update(StudentSession)
                .where(StudentSession.topic_id.in_(topic_ids))
                .values(topic_id=None)
            )
            
            # Delete student topic access records
            await db.execute(delete(StudentTopicAccess).where(StudentTopicAccess.topic_id.in_(topic_ids)))
            
            # Delete knowledge chunks
            await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id.in_(topic_ids)))
            
            # Delete materials
            await db.execute(delete(TopicMaterial).where(TopicMaterial.topic_id.in_(topic_ids)))
            
            # Delete topics
            for t in topics_list:
                await db.delete(t)
                
        # Delete subject itself
        await db.delete(subject)
        await db.commit()
        return {"status": "deleted"}
    except Exception as e:
        await db.rollback()
        logging.error(f"Error deleting subject {subject_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fanni o'chirishda xatolik yuz berdi: {str(e)}"
        )

@router.put("/subjects/{subject_id}")
async def update_subject(subject_id: int, req: SubjectCreateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Fan topilmadi")
        
    # Check if another subject has the same title
    title_check = await db.execute(
        select(Subject).where((Subject.title == req.title) & (Subject.id != subject_id))
    )
    if title_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bunday nomli fan allaqachon mavjud.")
        
    try:
        subject.title = req.title
        subject.description = req.description
        await db.commit()
        return {
            "status": "updated",
            "subject": {
                "id": subject.id,
                "title": subject.title,
                "description": subject.description
            }
        }
    except Exception as e:
        await db.rollback()
        logging.error(f"Error updating subject {subject_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fanni tahrirlashda xatolik yuz berdi: {str(e)}"
        )
