import os
import shutil
import uuid
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Homework, User

router = APIRouter(redirect_slashes=True)

# Make sure uploads directory exists
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/")
async def create_homework(
    title: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    link: Optional[str] = Form(None),
    created_by_user_id: Optional[int] = Form(None),
    student_user_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    image_path = None
    if image and image.filename:
        # Generate a unique filename to prevent collisions
        file_ext = os.path.splitext(image.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        destination = os.path.join(UPLOAD_DIR, unique_filename)
        
        try:
            with open(destination, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            # Store the URL path
            image_path = f"/uploads/{unique_filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Rasm yuklashda xatolik yuz berdi: {str(e)}")

    try:
        homework = Homework(
            title=title,
            text=text,
            link=link,
            image_path=image_path,
            created_by_user_id=created_by_user_id,
            student_user_id=student_user_id
        )
        db.add(homework)
        await db.commit()
        await db.refresh(homework)
        
        return {
            "status": "success",
            "homework": {
                "id": homework.id,
                "title": homework.title,
                "text": homework.text,
                "link": homework.link,
                "image_path": homework.image_path,
                "created_at": homework.created_at.isoformat(),
                "created_by_user_id": homework.created_by_user_id,
                "student_user_id": homework.student_user_id
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Vazifa yaratishda xatolik yuz berdi: {str(e)}")

@router.get("/")
async def list_homeworks(student_user_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Homework)
    if student_user_id:
        stmt = stmt.where((Homework.student_user_id == None) | (Homework.student_user_id == student_user_id))
    result = await db.execute(stmt.order_by(Homework.created_at.desc()))
    homeworks = result.scalars().all()
    
    return [
        {
            "id": hw.id,
            "title": hw.title,
            "text": hw.text,
            "link": hw.link,
            "image_path": hw.image_path,
            "created_at": hw.created_at.isoformat(),
            "created_by_user_id": hw.created_by_user_id,
            "student_user_id": hw.student_user_id
        }
        for hw in homeworks
    ]

@router.delete("/{homework_id}")
async def delete_homework(homework_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Homework).where(Homework.id == homework_id)
    result = await db.execute(stmt)
    homework = result.scalar_one_or_none()
    if not homework:
        raise HTTPException(status_code=404, detail="Vazifa topilmadi")
    
    # Safely delete image file from server if it exists
    if homework.image_path:
        filename = homework.image_path.replace("/uploads/", "")
        filepath = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
                
    try:
        await db.delete(homework)
        await db.commit()
        return {"status": "success", "message": "Vazifa muvaffaqiyatli o'chirildi"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"O'chirishda xatolik yuz berdi: {str(e)}")
