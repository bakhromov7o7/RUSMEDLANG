from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Announcement

router = APIRouter(redirect_slashes=True)

class AnnouncementCreateRequest(BaseModel):
    title: str
    content: str
    announcement_type: Optional[str] = "umumiy"

class AnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    announcement_type: Optional[str] = None

@router.get("/")
@router.get("")
async def list_announcements(
    q: Optional[str] = None,
    announcement_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Announcement)
    if announcement_type:
        stmt = stmt.where(Announcement.announcement_type == announcement_type)
    
    result = await db.execute(stmt.order_by(Announcement.created_at.desc()))
    announcements = result.scalars().all()

    if q:
        q_lower = q.lower()
        announcements = [
            a for a in announcements 
            if q_lower in a.title.lower() or q_lower in a.content.lower()
        ]

    return [
        {
            "id": a.id,
            "title": a.title,
            "content": a.content,
            "announcement_type": a.announcement_type,
            "views": a.views,
            "created_at": a.created_at.isoformat()
        }
        for a in announcements
    ]

@router.post("/")
@router.post("")
async def create_announcement(req: AnnouncementCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        ann = Announcement(
            title=req.title,
            content=req.content,
            announcement_type=req.announcement_type or "umumiy"
        )
        db.add(ann)
        await db.commit()
        await db.refresh(ann)
        return {
            "status": "success",
            "announcement": {
                "id": ann.id,
                "title": ann.title,
                "content": ann.content,
                "announcement_type": ann.announcement_type,
                "views": ann.views,
                "created_at": ann.created_at.isoformat()
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"E'lon yaratishda xatolik yuz berdi: {str(e)}")

@router.put("/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    req: AnnouncementUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Announcement).where(Announcement.id == announcement_id)
    result = await db.execute(stmt)
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    try:
        if req.title is not None:
            ann.title = req.title
        if req.content is not None:
            ann.content = req.content
        if req.announcement_type is not None:
            ann.announcement_type = req.announcement_type
        
        await db.commit()
        await db.refresh(ann)
        return {
            "status": "success",
            "announcement": {
                "id": ann.id,
                "title": ann.title,
                "content": ann.content,
                "announcement_type": ann.announcement_type,
                "views": ann.views,
                "created_at": ann.created_at.isoformat()
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"E'lonni tahrirlashda xatolik: {str(e)}")

@router.delete("/{announcement_id}")
async def delete_announcement(announcement_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Announcement).where(Announcement.id == announcement_id)
    result = await db.execute(stmt)
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    try:
        await db.delete(ann)
        await db.commit()
        return {"status": "success", "message": "E'lon muvaffaqiyatli o'chirildi"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"O'chirishda xatolik yuz berdi: {str(e)}")

@router.post("/{announcement_id}/view")
async def increment_views(announcement_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Announcement).where(Announcement.id == announcement_id)
    result = await db.execute(stmt)
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    try:
        ann.views += 1
        await db.commit()
        return {"status": "success", "views": ann.views}
    except Exception as e:
        await db.rollback()
        return {"status": "error", "message": str(e)}
