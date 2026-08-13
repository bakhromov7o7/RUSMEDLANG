import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso
from app.core.files import delete_upload, save_upload
from app.core.security import (
    ensure_can_access_user,
    get_current_user,
    is_staff,
    require_staff,
)
from app.database import get_db
from app.models import Homework, HomeworkSubmission, NotificationLog, Subject, User, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)


def _homework_public(hw: Homework) -> dict:
    return {
        "id": hw.id,
        "title": hw.title,
        "text": hw.text,
        "link": hw.link,
        "image_path": hw.image_path,
        "created_at": iso(hw.created_at),
        "created_by_user_id": hw.created_by_user_id,
        "student_user_id": hw.student_user_id,
        "subject_id": hw.subject_id,
    }


def _submission_public(sub: HomeworkSubmission, **extra) -> dict:
    data = {
        "id": sub.id,
        "homework_id": sub.homework_id,
        "student_user_id": sub.student_user_id,
        "text": sub.text,
        "image_path": sub.image_path,
        "status": sub.status,
        "grade": sub.grade,
        "teacher_feedback": sub.teacher_feedback,
        "submitted_at": iso(sub.submitted_at),
        "graded_at": iso(sub.graded_at),
    }
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Vazifalar (ustoz boshqaradi)
# ---------------------------------------------------------------------------

@router.post("/")
async def create_homework(
    title: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    link: Optional[str] = Form(None),
    created_by_user_id: Optional[int] = Form(None),  # e'tiborsiz — tokendan olinadi
    student_user_id: Optional[int] = Form(None),
    subject_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if subject_id is not None:
        if not (await db.execute(select(Subject.id).where(Subject.id == subject_id))).first():
            raise HTTPException(status_code=404, detail="Fan topilmadi")
    if student_user_id is not None:
        if not (await db.execute(select(User.id).where(User.id == student_user_id))).first():
            raise HTTPException(status_code=404, detail="Talaba topilmadi")

    image_path = None
    if image and image.filename:
        image_path = await save_upload(image, prefix="hw_", allow_documents=True)

    try:
        homework = Homework(
            title=title,
            text=text,
            link=link,
            image_path=image_path,
            created_by_user_id=staff.id,
            student_user_id=student_user_id,
            subject_id=subject_id,
        )
        db.add(homework)
        await db.commit()
        await db.refresh(homework)
    except Exception:
        await db.rollback()
        delete_upload(image_path)
        raise

    return {"status": "success", "homework": _homework_public(homework)}


@router.get("/")
async def list_homeworks(
    student_user_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Homework)

    # Talaba faqat umumiy va o'ziga biriktirilgan vazifalarni ko'radi.
    target_id = student_user_id if is_staff(current_user) else current_user.id
    if target_id is not None:
        stmt = stmt.where(
            (Homework.student_user_id.is_(None)) | (Homework.student_user_id == target_id)
        )
    if subject_id:
        stmt = stmt.where(Homework.subject_id == subject_id)

    homeworks = (
        await db.execute(stmt.order_by(Homework.created_at.desc()))
    ).scalars().all()
    items = [_homework_public(hw) for hw in homeworks]

    if not is_staff(current_user) or not items:
        return items

    # Xodim uchun har bir vazifa yonida javoblar soni va nechtasi hali
    # tekshirilmagani ko'rsatiladi — panelda navbatni ko'rish uchun.
    counts = (
        await db.execute(
            select(
                HomeworkSubmission.homework_id,
                func.count(HomeworkSubmission.id),
                # FILTER o'rniga CASE — eski SQLite qurilmalarida ham ishlaydi.
                func.coalesce(
                    func.sum(case((HomeworkSubmission.status == "pending", 1), else_=0)),
                    0,
                ),
            )
            .where(HomeworkSubmission.homework_id.in_([hw.id for hw in homeworks]))
            .group_by(HomeworkSubmission.homework_id)
        )
    ).all()
    by_homework = {row[0]: (row[1], row[2]) for row in counts}

    for item in items:
        total, pending = by_homework.get(item["id"], (0, 0))
        item["submissions_count"] = total
        item["pending_count"] = pending
    return items


@router.put("/{homework_id}")
async def update_homework(
    homework_id: int,
    title: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    link: Optional[str] = Form(None),
    subject_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    homework = (
        await db.execute(select(Homework).where(Homework.id == homework_id))
    ).scalar_one_or_none()
    if not homework:
        raise HTTPException(status_code=404, detail="Vazifa topilmadi")

    old_image = homework.image_path
    new_image = None
    if image and image.filename:
        new_image = await save_upload(image, prefix="hw_", allow_documents=True)
        homework.image_path = new_image

    try:
        if title is not None:
            homework.title = title
        if text is not None:
            homework.text = text
        if link is not None:
            homework.link = link
        if subject_id is not None:
            homework.subject_id = subject_id

        await db.commit()
        await db.refresh(homework)
    except Exception:
        await db.rollback()
        delete_upload(new_image)
        raise

    if new_image:
        delete_upload(old_image)

    return {"status": "success", "homework": _homework_public(homework)}


@router.delete("/{homework_id}")
async def delete_homework(
    homework_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    homework = (
        await db.execute(select(Homework).where(Homework.id == homework_id))
    ).scalar_one_or_none()
    if not homework:
        raise HTTPException(status_code=404, detail="Vazifa topilmadi")

    # Talabalar yuklagan rasmlar ham o'chirilishi kerak — ilgari ular
    # diskda yetim bo'lib qolardi.
    submission_images = (
        await db.execute(
            select(HomeworkSubmission.image_path).where(
                HomeworkSubmission.homework_id == homework_id
            )
        )
    ).scalars().all()

    await db.delete(homework)
    await db.commit()

    delete_upload(homework.image_path)
    for path in submission_images:
        delete_upload(path)

    return {"status": "success", "message": "Vazifa muvaffaqiyatli o'chirildi"}


# ---------------------------------------------------------------------------
# Topshiriqlar
# ---------------------------------------------------------------------------

@router.post("/{homework_id}/submit")
async def submit_homework(
    homework_id: int,
    student_user_id: Optional[int] = Form(None),  # e'tiborsiz — tokendan olinadi
    text: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not (await db.execute(select(Homework.id).where(Homework.id == homework_id))).first():
        raise HTTPException(status_code=404, detail="Vazifa topilmadi")

    student_id = current_user.id
    image_path = None
    if image and image.filename:
        image_path = await save_upload(image, prefix="sub_", allow_documents=True)

    existing = (
        await db.execute(
            select(HomeworkSubmission).where(
                HomeworkSubmission.homework_id == homework_id,
                HomeworkSubmission.student_user_id == student_id,
            )
        )
    ).scalar_one_or_none()

    old_image = existing.image_path if existing else None

    try:
        if existing:
            existing.text = text
            if image_path:
                existing.image_path = image_path
            existing.status = "pending"
            existing.grade = None
            existing.teacher_feedback = None
            existing.graded_at = None
            existing.submitted_at = utcnow()
            submission = existing
        else:
            submission = HomeworkSubmission(
                homework_id=homework_id,
                student_user_id=student_id,
                text=text,
                image_path=image_path,
                status="pending",
            )
            db.add(submission)

        await db.commit()
        await db.refresh(submission)
    except IntegrityError:
        # Parallel ikkita so'rov — unique constraint ushlab qoldi.
        await db.rollback()
        delete_upload(image_path)
        raise HTTPException(
            status_code=409, detail="Javobingiz allaqachon yuborilgan. Sahifani yangilang."
        )
    except Exception:
        await db.rollback()
        delete_upload(image_path)
        raise

    if image_path and old_image:
        delete_upload(old_image)

    return {"status": "success", "submission": _submission_public(submission)}


@router.get("/submissions/my")
async def get_my_submissions(
    student_user_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_id = (
        student_user_id if (is_staff(current_user) and student_user_id) else current_user.id
    )
    ensure_can_access_user(current_user, target_id)

    # Vazifa sarlavhasi ham qaytariladi — ilova ro'yxatda uni ko'rsatadi,
    # aks holda har bir javob shunchaki "Vazifa" bo'lib chiqardi.
    rows = (
        await db.execute(
            select(HomeworkSubmission, Homework.title)
            .outerjoin(Homework, Homework.id == HomeworkSubmission.homework_id)
            .where(HomeworkSubmission.student_user_id == target_id)
            .order_by(HomeworkSubmission.submitted_at.desc())
        )
    ).all()
    return [
        _submission_public(row.HomeworkSubmission, homework_title=row.title or "Vazifa")
        for row in rows
    ]


@router.get("/{homework_id}/submissions")
async def list_homework_submissions(
    homework_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(HomeworkSubmission, User.full_name, User.student_group)
            .join(User, User.id == HomeworkSubmission.student_user_id)
            .where(HomeworkSubmission.homework_id == homework_id)
            .order_by(HomeworkSubmission.submitted_at.desc())
        )
    ).all()

    return [
        _submission_public(
            row.HomeworkSubmission,
            student_name=row.full_name,
            student_group=row.student_group,
        )
        for row in rows
    ]


class GradeRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]
    grade: Optional[str] = Field(default=None, max_length=50)
    teacher_feedback: Optional[str] = Field(default=None, max_length=2000)


@router.post("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: int,
    req: GradeRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    submission = (
        await db.execute(
            select(HomeworkSubmission).where(HomeworkSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="Topshiriq javobi topilmadi")

    submission.status = req.status
    submission.grade = req.grade
    submission.teacher_feedback = req.teacher_feedback
    submission.graded_at = utcnow()

    homework_title = (
        await db.execute(select(Homework.title).where(Homework.id == submission.homework_id))
    ).scalar_one_or_none()

    db.add(NotificationLog(
        user_id=submission.student_user_id,
        event_type="homework_graded",
        payload={
            "title": homework_title or "Vazifa",
            "status": submission.status,
            "grade": submission.grade,
        },
    ))

    await db.commit()
    await db.refresh(submission)
    return {"status": "success", "submission": _submission_public(submission)}
