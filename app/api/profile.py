"""Foydalanuvchi profili: shaxsiy ma'lumot, sozlamalar, saqlanganlar,
murojaatlar va yordam bo'limi.

Ilovadagi profil menyusining barcha bo'limlari shu modul orqali ishlaydi.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso
from app.core.files import delete_upload, save_upload
from app.core.security import get_current_user, is_staff, require_staff
from app.database import get_db
from app.models import (
    Announcement,
    FaqEntry,
    MedicalTerm,
    NotificationLog,
    RequestStatus,
    SavedItem,
    SavedItemType,
    StudentRequest,
    SubjectMaterial,
    Topic,
    User,
    UserRole,
    utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)

DEFAULT_NOTIFICATION_PREFS = {
    "homework_graded": True,
    "new_message": True,
    "group_message": True,
    "announcements": True,
    "schedule_changes": True,
}

REQUEST_TYPES = ("ma'lumotnoma", "ruxsat", "akademik", "texnik", "boshqa")


# ---------------------------------------------------------------------------
# Shaxsiy ma'lumotlar
# ---------------------------------------------------------------------------

def _profile_public(user: User) -> dict:
    return {
        "id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "username": user.username,
        "role": user.role.value,
        "phone_number": user.phone_number,
        "student_group": user.student_group or "",
        "parent_name": user.parent_name,
        "parent_phone": user.parent_phone,
        "birth_date": user.birth_date,
        "avatar_path": user.avatar_path,
        "department": user.department,
        "degree": user.degree,
        "bio": user.bio,
        "preferred_language": user.preferred_language or "uz",
        "must_change_password": user.must_change_password,
        "created_at": iso(user.created_at),
        "last_active": iso(user.last_active),
    }


class ProfileUpdateRequest(BaseModel):
    """Foydalanuvchi o'zi tahrirlashi mumkin bo'lgan maydonlar.

    `full_name`, `student_group` va rol kabi maydonlar bu yerda yo'q —
    ularni faqat ustoz o'zgartira oladi.
    """

    phone_number: Optional[str] = Field(default=None, max_length=50)
    parent_name: Optional[str] = Field(default=None, max_length=255)
    parent_phone: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = Field(default=None, max_length=100)
    # Xodimlar uchun
    department: Optional[str] = Field(default=None, max_length=255)
    degree: Optional[str] = Field(default=None, max_length=255)
    bio: Optional[str] = Field(default=None, max_length=2000)


@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    return _profile_public(current_user)


@router.patch("/me")
async def update_profile(
    req: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = req.model_dump(exclude_unset=True)

    # Kafedra/daraja/bio faqat xodim profiliga tegishli.
    if not is_staff(current_user):
        for field in ("department", "degree", "bio"):
            data.pop(field, None)

    for field, value in data.items():
        setattr(current_user, field, value)

    await db.commit()
    await db.refresh(current_user)
    return {"status": "success", "profile": _profile_public(current_user)}


@router.post("/me/avatar")
async def upload_avatar(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    old = current_user.avatar_path
    current_user.avatar_path = await save_upload(image, prefix="avatar_")
    await db.commit()
    delete_upload(old)
    return {"status": "success", "avatar_path": current_user.avatar_path}


@router.delete("/me/avatar")
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    old = current_user.avatar_path
    current_user.avatar_path = None
    await db.commit()
    delete_upload(old)
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Sozlamalar: til va bildirishnomalar
# ---------------------------------------------------------------------------

class SettingsUpdateRequest(BaseModel):
    preferred_language: Optional[Literal["uz", "ru"]] = None
    notification_prefs: Optional[dict] = None


def _merged_prefs(user: User) -> dict:
    stored = user.notification_prefs if isinstance(user.notification_prefs, dict) else {}
    return {**DEFAULT_NOTIFICATION_PREFS, **stored}


@router.get("/me/settings")
async def get_settings(current_user: User = Depends(get_current_user)):
    return {
        "preferred_language": current_user.preferred_language or "uz",
        "notification_prefs": _merged_prefs(current_user),
        "available_languages": [
            {"code": "uz", "label": "O'zbekcha"},
            {"code": "ru", "label": "Русский"},
        ],
    }


@router.put("/me/settings")
async def update_settings(
    req: SettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.preferred_language is not None:
        current_user.preferred_language = req.preferred_language

    if req.notification_prefs is not None:
        # Faqat ma'lum kalitlar saqlanadi — klient ixtiyoriy maydon yubora olmaydi.
        merged = _merged_prefs(current_user)
        for key, value in req.notification_prefs.items():
            if key in DEFAULT_NOTIFICATION_PREFS:
                merged[key] = bool(value)
        current_user.notification_prefs = merged

    await db.commit()
    await db.refresh(current_user)
    return {
        "status": "success",
        "preferred_language": current_user.preferred_language,
        "notification_prefs": _merged_prefs(current_user),
    }


@router.get("/me/security")
async def security_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Xavfsizlik bo'limi uchun qisqa ma'lumot."""
    last_login = (
        await db.execute(
            select(NotificationLog.created_at)
            .where(
                NotificationLog.user_id == current_user.id,
                NotificationLog.event_type == "login",
            )
            .order_by(NotificationLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "login": current_user.login,
        "must_change_password": current_user.must_change_password,
        "last_active": iso(current_user.last_active),
        "last_login": iso(last_login),
        "account_created": iso(current_user.created_at),
    }


# ---------------------------------------------------------------------------
# Saqlanganlar (bookmark)
# ---------------------------------------------------------------------------

class SavedItemCreateRequest(BaseModel):
    item_type: Literal["topic", "material", "term", "announcement"]
    item_id: int
    title: Optional[str] = Field(default=None, max_length=255)
    subtitle: Optional[str] = Field(default=None, max_length=255)


def _saved_public(item: SavedItem) -> dict:
    return {
        "id": item.id,
        "item_type": item.item_type.value,
        "item_id": item.item_id,
        "title": item.title,
        "subtitle": item.subtitle,
        "created_at": iso(item.created_at),
    }


async def _resolve_title(
    db: AsyncSession, item_type: str, item_id: int
) -> tuple[Optional[str], Optional[str]]:
    """Sarlavha klientdan kelmasa bazadan olamiz."""
    if item_type == "topic":
        row = (
            await db.execute(select(Topic.title, Topic.description).where(Topic.id == item_id))
        ).first()
        return (row[0], row[1]) if row else (None, None)
    if item_type == "material":
        row = (
            await db.execute(
                select(SubjectMaterial.title, SubjectMaterial.detail).where(
                    SubjectMaterial.id == item_id
                )
            )
        ).first()
        return (row[0], row[1]) if row else (None, None)
    if item_type == "term":
        row = (
            await db.execute(
                select(MedicalTerm.word, MedicalTerm.translation).where(
                    MedicalTerm.id == item_id
                )
            )
        ).first()
        return (row[0], row[1]) if row else (None, None)
    if item_type == "announcement":
        row = (
            await db.execute(
                select(Announcement.title, Announcement.announcement_type).where(
                    Announcement.id == item_id
                )
            )
        ).first()
        return (row[0], row[1]) if row else (None, None)
    return (None, None)


@router.get("/saved")
async def list_saved(
    item_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SavedItem).where(SavedItem.user_id == current_user.id)
    if item_type:
        try:
            stmt = stmt.where(SavedItem.item_type == SavedItemType(item_type))
        except ValueError:
            raise HTTPException(status_code=400, detail="Noto'g'ri item_type")

    rows = (
        await db.execute(stmt.order_by(SavedItem.created_at.desc()))
    ).scalars().all()
    return [_saved_public(r) for r in rows]


@router.post("/saved", status_code=status.HTTP_201_CREATED)
async def create_saved(
    req: SavedItemCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item_type = SavedItemType(req.item_type)

    # Takroriy bosishda xato ko'rsatmaymiz — mavjudini qaytaramiz.
    existing = (
        await db.execute(
            select(SavedItem).where(
                SavedItem.user_id == current_user.id,
                SavedItem.item_type == item_type,
                SavedItem.item_id == req.item_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"status": "exists", "item": _saved_public(existing)}

    title, subtitle = req.title, req.subtitle
    if not title:
        title, subtitle = await _resolve_title(db, req.item_type, req.item_id)
    if not title:
        raise HTTPException(status_code=404, detail="Saqlanayotgan element topilmadi")

    item = SavedItem(
        user_id=current_user.id,
        item_type=item_type,
        item_id=req.item_id,
        title=title[:255],
        subtitle=(subtitle or "")[:255] or None,
    )

    # Poyga holatida unique constraint ishlaydi. Savepoint ichida yozamiz —
    # aks holda flush ichidagi xato butun sessiyani buzadi.
    try:
        async with db.begin_nested():
            db.add(item)
    except IntegrityError:
        existing = (
            await db.execute(
                select(SavedItem).where(
                    SavedItem.user_id == current_user.id,
                    SavedItem.item_type == item_type,
                    SavedItem.item_id == req.item_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return {"status": "exists", "item": _saved_public(existing)}
        raise HTTPException(status_code=409, detail="Elementni saqlab bo'lmadi")

    await db.commit()
    await db.refresh(item)
    return {"status": "success", "item": _saved_public(item)}


@router.delete("/saved/{item_type}/{item_id}")
async def delete_saved_by_target(
    item_type: str,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manba bo'yicha o'chirish — ekranda "saqlash" tugmasini almashtirish uchun."""
    try:
        parsed = SavedItemType(item_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Noto'g'ri item_type")

    result = await db.execute(
        delete(SavedItem).where(
            SavedItem.user_id == current_user.id,
            SavedItem.item_type == parsed,
            SavedItem.item_id == item_id,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Saqlangan element topilmadi")
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Murojaatlar
# ---------------------------------------------------------------------------

class RequestCreate(BaseModel):
    request_type: str = Field(..., max_length=50)
    subject: str = Field(..., min_length=3, max_length=255)
    message: str = Field(..., min_length=5, max_length=4000)


class RequestRespond(BaseModel):
    status: Literal["pending", "in_progress", "resolved", "rejected"]
    response: Optional[str] = Field(default=None, max_length=4000)


def _request_public(item: StudentRequest, student_name: Optional[str] = None) -> dict:
    data = {
        "id": item.id,
        "student_user_id": item.student_user_id,
        "request_type": item.request_type,
        "subject": item.subject,
        "message": item.message,
        "status": item.status.value,
        "response": item.response,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }
    if student_name is not None:
        data["student_name"] = student_name
    return data


@router.get("/requests/types")
async def request_types(_user: User = Depends(get_current_user)):
    return [{"value": t, "label": t.capitalize()} for t in REQUEST_TYPES]


@router.get("/requests")
async def list_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Talaba o'z murojaatlarini, xodim esa hammasini ko'radi."""
    stmt = select(StudentRequest, User.full_name).join(
        User, User.id == StudentRequest.student_user_id
    )
    if not is_staff(current_user):
        stmt = stmt.where(StudentRequest.student_user_id == current_user.id)
    if status_filter:
        try:
            stmt = stmt.where(StudentRequest.status == RequestStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Noto'g'ri status")

    rows = (
        await db.execute(stmt.order_by(StudentRequest.created_at.desc()).limit(limit))
    ).all()
    return [_request_public(row[0], row[1]) for row in rows]


@router.get("/requests/pending-count")
async def pending_requests_count(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(
            select(func.count(StudentRequest.id)).where(
                StudentRequest.status == RequestStatus.pending
            )
        )
    ).scalar() or 0
    return {"count": total}


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_request(
    req: RequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request_type = req.request_type if req.request_type in REQUEST_TYPES else "boshqa"

    item = StudentRequest(
        student_user_id=current_user.id,
        request_type=request_type,
        subject=req.subject.strip(),
        message=req.message.strip(),
        status=RequestStatus.pending,
    )
    db.add(item)

    # Xodimlarga bildirishnoma.
    staff_ids = (
        await db.execute(
            select(User.id).where(
                User.role.in_([UserRole.employee, UserRole.superadmin]),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    for staff_id in staff_ids:
        db.add(NotificationLog(
            user_id=staff_id,
            event_type="new_request",
            payload={
                "student_name": current_user.full_name,
                "subject": item.subject,
                "request_type": request_type,
            },
        ))

    await db.commit()
    await db.refresh(item)
    return {"status": "success", "request": _request_public(item)}


@router.post("/requests/{request_id}/respond")
async def respond_request(
    request_id: int,
    req: RequestRespond,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(select(StudentRequest).where(StudentRequest.id == request_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Murojaat topilmadi")

    item.status = RequestStatus(req.status)
    if req.response is not None:
        item.response = req.response.strip() or None
    item.responded_by_user_id = staff.id
    item.updated_at = utcnow()

    db.add(NotificationLog(
        user_id=item.student_user_id,
        event_type="request_answered",
        payload={"subject": item.subject, "status": item.status.value},
    ))

    await db.commit()
    await db.refresh(item)
    return {"status": "success", "request": _request_public(item)}


@router.delete("/requests/{request_id}")
async def delete_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(select(StudentRequest).where(StudentRequest.id == request_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Murojaat topilmadi")
    if item.student_user_id != current_user.id and not is_staff(current_user):
        raise HTTPException(status_code=403, detail="Bu murojaat sizga tegishli emas")
    if item.status != RequestStatus.pending and not is_staff(current_user):
        raise HTTPException(
            status_code=409, detail="Ko'rib chiqilgan murojaatni o'chirib bo'lmaydi"
        )

    await db.delete(item)
    await db.commit()
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Yordam / FAQ
# ---------------------------------------------------------------------------

class FaqCreate(BaseModel):
    category: str = Field(default="umumiy", max_length=100)
    question: str = Field(..., min_length=3, max_length=500)
    answer: str = Field(..., min_length=3, max_length=5000)
    sort_order: int = Field(default=0, ge=0, le=1000)
    is_active: bool = True


def _faq_public(item: FaqEntry) -> dict:
    return {
        "id": item.id,
        "category": item.category,
        "question": item.question,
        "answer": item.answer,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
    }


@router.get("/faq")
async def list_faq(
    category: Optional[str] = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FaqEntry)
    if category:
        stmt = stmt.where(FaqEntry.category == category)
    if not (include_inactive and is_staff(current_user)):
        stmt = stmt.where(FaqEntry.is_active.is_(True))

    rows = (
        await db.execute(stmt.order_by(FaqEntry.sort_order, FaqEntry.id))
    ).scalars().all()
    return [_faq_public(r) for r in rows]


@router.post("/faq", status_code=status.HTTP_201_CREATED)
async def create_faq(
    req: FaqCreate,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    item = FaqEntry(**req.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"status": "success", "faq": _faq_public(item)}


@router.put("/faq/{faq_id}")
async def update_faq(
    faq_id: int,
    req: FaqCreate,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(select(FaqEntry).where(FaqEntry.id == faq_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Savol topilmadi")

    for field, value in req.model_dump().items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return {"status": "success", "faq": _faq_public(item)}


@router.delete("/faq/{faq_id}")
async def delete_faq(
    faq_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(select(FaqEntry).where(FaqEntry.id == faq_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Savol topilmadi")

    await db.delete(item)
    await db.commit()
    return {"status": "success"}
