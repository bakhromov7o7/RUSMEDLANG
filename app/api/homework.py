import os
import shutil
import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Homework, User, HomeworkSubmission, NotificationLog

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

class GradeRequest(BaseModel):
    status: str  # approved, rejected
    grade: Optional[str] = None
    teacher_feedback: Optional[str] = None

@router.post("/{homework_id}/submit")
async def submit_homework(
    homework_id: int,
    student_user_id: int = Form(...),
    text: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    # Check if homework exists
    hw_res = await db.execute(select(Homework).where(Homework.id == homework_id))
    hw = hw_res.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Vazifa topilmadi")

    # Check if already submitted
    existing_res = await db.execute(
        select(HomeworkSubmission).where(
            (HomeworkSubmission.homework_id == homework_id) &
            (HomeworkSubmission.student_user_id == student_user_id)
        )
    )
    existing = existing_res.scalar_one_or_none()
    
    image_path = None
    if image and image.filename:
        file_ext = os.path.splitext(image.filename)[1]
        unique_filename = f"sub_{uuid.uuid4()}{file_ext}"
        destination = os.path.join(UPLOAD_DIR, unique_filename)
        try:
            with open(destination, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            image_path = f"/uploads/{unique_filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Rasm yuklashda xatolik: {str(e)}")

    try:
        if existing:
            # Update existing submission
            existing.text = text
            if image_path:
                # Safely remove old image file if it exists
                if existing.image_path:
                    old_filename = existing.image_path.replace("/uploads/", "")
                    old_filepath = os.path.join(UPLOAD_DIR, old_filename)
                    if os.path.exists(old_filepath):
                        try:
                            os.remove(old_filepath)
                        except Exception:
                            pass
                existing.image_path = image_path
            existing.status = "pending"
            existing.grade = None
            existing.teacher_feedback = None
            existing.submitted_at = datetime.utcnow()
            sub = existing
        else:
            # Create new submission
            sub = HomeworkSubmission(
                homework_id=homework_id,
                student_user_id=student_user_id,
                text=text,
                image_path=image_path,
                status="pending"
            )
            db.add(sub)
        
        await db.commit()
        await db.refresh(sub)
        return {
            "status": "success",
            "submission": {
                "id": sub.id,
                "homework_id": sub.homework_id,
                "student_user_id": sub.student_user_id,
                "text": sub.text,
                "image_path": sub.image_path,
                "status": sub.status,
                "submitted_at": sub.submitted_at.isoformat()
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Javobni yuborishda xatolik: {str(e)}")

@router.get("/{homework_id}/submissions")
async def list_homework_submissions(homework_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(HomeworkSubmission, User.full_name, User.student_group)
        .join(User, User.id == HomeworkSubmission.student_user_id)
        .where(HomeworkSubmission.homework_id == homework_id)
        .order_by(HomeworkSubmission.submitted_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    return [
        {
            "id": row.HomeworkSubmission.id,
            "homework_id": row.HomeworkSubmission.homework_id,
            "student_user_id": row.HomeworkSubmission.student_user_id,
            "student_name": row.full_name,
            "student_group": row.student_group,
            "text": row.HomeworkSubmission.text,
            "image_path": row.HomeworkSubmission.image_path,
            "status": row.HomeworkSubmission.status,
            "grade": row.HomeworkSubmission.grade,
            "teacher_feedback": row.HomeworkSubmission.teacher_feedback,
            "submitted_at": row.HomeworkSubmission.submitted_at.isoformat(),
            "graded_at": row.HomeworkSubmission.graded_at.isoformat() if row.HomeworkSubmission.graded_at else None
        }
        for row in rows
    ]

@router.get("/submissions/my")
async def get_my_submissions(student_user_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(HomeworkSubmission)
        .where(HomeworkSubmission.student_user_id == student_user_id)
    )
    result = await db.execute(stmt)
    submissions = result.scalars().all()
    
    return [
        {
            "id": sub.id,
            "homework_id": sub.homework_id,
            "student_user_id": sub.student_user_id,
            "text": sub.text,
            "image_path": sub.image_path,
            "status": sub.status,
            "grade": sub.grade,
            "teacher_feedback": sub.teacher_feedback,
            "submitted_at": sub.submitted_at.isoformat(),
            "graded_at": sub.graded_at.isoformat() if sub.graded_at else None
        }
        for sub in submissions
    ]

@router.post("/submissions/{submission_id}/grade")
async def grade_submission(submission_id: int, req: GradeRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(HomeworkSubmission).where(HomeworkSubmission.id == submission_id)
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Topshiriq javobi topilmadi")
        
    try:
        sub.status = req.status
        sub.grade = req.grade
        sub.teacher_feedback = req.teacher_feedback
        sub.graded_at = datetime.utcnow()

        # Notify the student that their homework was graded.
        try:
            hw_res = await db.execute(select(Homework).where(Homework.id == sub.homework_id))
            hw = hw_res.scalar_one_or_none()
            db.add(NotificationLog(
                user_id=sub.student_user_id,
                event_type="homework_graded",
                payload={
                    "title": hw.title if hw else "Vazifa",
                    "status": sub.status,
                    "grade": sub.grade,
                },
            ))
        except Exception:
            pass

        await db.commit()
        await db.refresh(sub)
        return {
            "status": "success",
            "submission": {
                "id": sub.id,
                "homework_id": sub.homework_id,
                "student_user_id": sub.student_user_id,
                "status": sub.status,
                "grade": sub.grade,
                "teacher_feedback": sub.teacher_feedback,
                "graded_at": sub.graded_at.isoformat()
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Baholashda xatolik: {str(e)}")
