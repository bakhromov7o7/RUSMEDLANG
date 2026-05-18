import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
)
from app.services.ai_service import AIService
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter(redirect_slashes=True)
ai_service = AIService()
QUESTION_LIMIT = 5

class TopicCreateRequest(BaseModel):
    employee_id: int
    title: str
    description: Optional[str] = ""
    video_url: Optional[str] = ""
    content: str # The main text content

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
            title=req.title,
            description=req.description,
            status=TopicStatus.active
        )
        db.add(topic)
        await db.flush()

        # 3. Add Video Material if exists
        if req.video_url:
            video_material = TopicMaterial(
                topic_id=topic.id,
                uploaded_by_user_id=employee.id,
                material_type=MaterialType.video,
                title=f"{req.title} - Video",
                source_url=req.video_url
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
async def list_topics(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Topic)
        .options(selectinload(Topic.materials))
        .order_by(Topic.created_at.desc())
    )
    topics = result.scalars().all()
    
    # Manually serialize to include materials source_url and content
    output = []
    for t in topics:
        video = next((m for m in t.materials if m.material_type == MaterialType.video), None)
        text = next((m for m in t.materials if m.material_type == MaterialType.text), None)
        output.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status.value if t.status else "draft",
            "video_url": video.source_url if video else None,
            "content": text.raw_text if text else ""
        })
    return output

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

        if session.question_count >= QUESTION_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Question limit reached",
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
        used = session.question_count
        remaining = max(QUESTION_LIMIT - session.question_count, 0)
        await db.commit()

    return {
        "answer": answer,
        "limit": QUESTION_LIMIT,
        "used": used,
        "remaining": remaining,
    }

@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)):
    # Delete chunks first
    from sqlalchemy import delete
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id == topic_id))
    # Delete materials
    await db.execute(delete(TopicMaterial).where(TopicMaterial.topic_id == topic_id))
    # Delete topic
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()
    if topic:
        await db.delete(topic)
        await db.commit()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Topic not found")

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
    
    # 3. Update Video Material
    from sqlalchemy import delete
    if req.video_url:
        # Check if exists, else create
        result = await db.execute(select(TopicMaterial).where(
            TopicMaterial.topic_id == topic_id, 
            TopicMaterial.material_type == MaterialType.video
        ))
        video_material = result.scalar_one_or_none()
        if video_material:
            video_material.source_url = req.video_url
            video_material.title = f"{req.title} - Video"
        else:
            video_material = TopicMaterial(
                topic_id=topic_id,
                uploaded_by_user_id=req.employee_id,
                material_type=MaterialType.video,
                title=f"{req.title} - Video",
                source_url=req.video_url
            )
            db.add(video_material)
    else:
        # Delete video if removed
        await db.execute(delete(TopicMaterial).where(
            TopicMaterial.topic_id == topic_id, 
            TopicMaterial.material_type == MaterialType.video
        ))

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
