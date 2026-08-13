from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso
from app.core.security import get_current_user, require_staff
from app.database import get_db
from app.models import Announcement, User

router = APIRouter(redirect_slashes=True)


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=20000)
    announcement_type: Optional[str] = Field(default="umumiy", max_length=50)


class AnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    announcement_type: Optional[str] = Field(default=None, max_length=50)


def _public(a: Announcement) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "content": a.content,
        "announcement_type": a.announcement_type,
        "views": a.views,
        "created_at": iso(a.created_at),
    }


@router.get("/")
@router.get("")
async def list_announcements(
    q: Optional[str] = None,
    announcement_type: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Announcement)
    if announcement_type:
        stmt = stmt.where(Announcement.announcement_type == announcement_type)
    if q:
        # Qidiruv bazada bajariladi — ilgari butun jadval Python'ga yuklanardi.
        pattern = f"%{q}%"
        stmt = stmt.where(
            Announcement.title.ilike(pattern) | Announcement.content.ilike(pattern)
        )

    rows = (
        await db.execute(stmt.order_by(Announcement.created_at.desc()).limit(limit))
    ).scalars().all()
    return [_public(a) for a in rows]


@router.post("/")
@router.post("")
async def create_announcement(
    req: AnnouncementCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    announcement = Announcement(
        title=req.title,
        content=req.content,
        announcement_type=req.announcement_type or "umumiy",
    )
    db.add(announcement)
    await db.commit()
    await db.refresh(announcement)
    return {"status": "success", "announcement": _public(announcement)}


@router.put("/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    req: AnnouncementUpdateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    announcement = (
        await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    ).scalar_one_or_none()
    if not announcement:
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    for field, value in req.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(announcement, field, value)

    await db.commit()
    await db.refresh(announcement)
    return {"status": "success", "announcement": _public(announcement)}


@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    announcement = (
        await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    ).scalar_one_or_none()
    if not announcement:
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    await db.delete(announcement)
    await db.commit()
    return {"status": "success", "message": "E'lon muvaffaqiyatli o'chirildi"}


@router.post("/{announcement_id}/view")
async def increment_views(
    announcement_id: int,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Atomik oshirish — ilgari o'qib-yozish edi va parallel so'rovlarda
    # ko'rishlar yo'qolardi.
    result = await db.execute(
        update(Announcement)
        .where(Announcement.id == announcement_id)
        .values(views=Announcement.views + 1)
        .returning(Announcement.views)
    )
    views = result.scalar_one_or_none()
    if views is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="E'lon topilmadi")

    await db.commit()
    return {"status": "success", "views": views}
