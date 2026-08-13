import logging
import os
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from app.api._shared import count_ai_questions_today, iso
from app.core import config
from app.core.security import get_current_user, require_staff
from app.database import get_db
from app.models import (
    KnowledgeChunk,
    LessonSchedule,
    MaterialType,
    MedicalTerm,
    NotificationLog,
    QuizAttempt,
    QuizQuestion,
    SessionState,
    StudentSession,
    StudentTopicAccess,
    Subject,
    SubjectMaterial,
    Topic,
    TopicMaterial,
    TopicStatus,
    User,
    UserRole,
)
from app.services.ai_service import AIService
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)
ai_service = AIService()
pdf_service = PDFService()

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _cleanup(path: str) -> BackgroundTask:
    """Javob yuborilgandan keyin vaqtinchalik PDF'ni o'chiradi."""

    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


# ---------------------------------------------------------------------------
# Pydantic sxemalari
# ---------------------------------------------------------------------------

class TopicCreateRequest(BaseModel):
    employee_id: Optional[int] = None  # tokendan olinadi, moslik uchun qoldirilgan
    subject_id: Optional[int] = None
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default="", max_length=5000)
    video_url: Optional[str] = Field(default="", max_length=2000)
    video_urls: Optional[List[str]] = Field(default_factory=list)
    topic_type: Optional[str] = Field(default="leksika", max_length=50)
    content: Optional[str] = ""  # eski format
    leksika_content: Optional[str] = ""
    grammatika_content: Optional[str] = ""


class SubjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default="", max_length=5000)


class TopicAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[int] = None  # e'tiborsiz qoldiriladi, tokendan olinadi
    language: str = Field(default="uz", max_length=10)


class SubjectMaterialCreateRequest(BaseModel):
    material_type: str = Field(default="pdf", max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    detail: Optional[str] = Field(default="", max_length=255)
    url: str = Field(..., min_length=1, max_length=2000)


class LessonScheduleCreateRequest(BaseModel):
    subject_id: int
    student_group: str = Field(..., min_length=1, max_length=100)
    day_of_week: int = Field(..., ge=1, le=7)
    start_time: str = Field(..., max_length=10)
    end_time: str = Field(..., max_length=10)
    room: str = Field(..., min_length=1, max_length=50)
    teacher_name: Optional[str] = Field(default="", max_length=255)
    # Dars o'tiladigan joy — davomatda joylashuvni tekshirish uchun.
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_meters: Optional[int] = Field(default=None, ge=20, le=5000)

    @field_validator("start_time", "end_time")
    @classmethod
    def _check_time(cls, v: str) -> str:
        if not TIME_PATTERN.match(v.strip()):
            raise ValueError("Vaqt HH:MM formatida bo'lishi kerak (masalan 09:30)")
        return v.strip()


class MedicalTermCreateRequest(BaseModel):
    word: str = Field(..., min_length=1, max_length=255)
    transcription: Optional[str] = Field(default=None, max_length=255)
    gender: Optional[str] = Field(default=None, max_length=100)
    translation: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    example_ru: Optional[str] = None
    example_uz: Optional[str] = None


# ---------------------------------------------------------------------------
# Fanlar
# ---------------------------------------------------------------------------

@router.get("/subjects")
async def list_subjects(
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subjects = (await db.execute(select(Subject).order_by(Subject.title))).scalars().all()

    # Talaba faqat o'z progressini ko'radi; xodim istalgan talabanikini.
    target_id = current_user.id if current_user.role == UserRole.student else user_id

    progress_by_subject: dict[int, float] = {}
    if target_id:
        # Fanlar bo'yicha aktiv mavzular soni — bitta so'rovda.
        totals = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(Topic.subject_id, func.count(Topic.id))
                    .where(Topic.subject_id.isnot(None), Topic.status == TopicStatus.active)
                    .group_by(Topic.subject_id)
                )
            ).all()
        }
        # Talaba tugatgan (finished) mavzular soni — yana bitta so'rovda.
        completed = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(Topic.subject_id, func.count(func.distinct(QuizAttempt.topic_id)))
                    .join(QuizAttempt, QuizAttempt.topic_id == Topic.id)
                    .where(
                        Topic.subject_id.isnot(None),
                        Topic.status == TopicStatus.active,
                        QuizAttempt.student_user_id == target_id,
                        QuizAttempt.finished_at.isnot(None),
                    )
                    .group_by(Topic.subject_id)
                )
            ).all()
        }
        for subject_id, total in totals.items():
            if total:
                progress_by_subject[subject_id] = completed.get(subject_id, 0) / total

    return [
        {
            "id": s.id,
            "title": s.title,
            "description": s.description or "",
            "created_at": iso(s.created_at),
            "progress": progress_by_subject.get(s.id, 0.0),
        }
        for s in subjects
    ]


@router.post("/subjects")
async def create_subject(
    req: SubjectCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    title = req.title.strip()
    if (await db.execute(select(Subject.id).where(Subject.title == title))).first():
        raise HTTPException(status_code=400, detail="Bunday fan allaqachon mavjud.")

    subject = Subject(title=title, description=req.description)
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return {
        "status": "success",
        "subject": {"id": subject.id, "title": subject.title, "description": subject.description},
    }


@router.put("/subjects/{subject_id}")
async def update_subject(
    subject_id: int,
    req: SubjectCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    subject = (
        await db.execute(select(Subject).where(Subject.id == subject_id))
    ).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Fan topilmadi")

    title = req.title.strip()
    duplicate = await db.execute(
        select(Subject.id).where(Subject.title == title, Subject.id != subject_id)
    )
    if duplicate.first():
        raise HTTPException(status_code=400, detail="Bunday nomli fan allaqachon mavjud.")

    subject.title = title
    subject.description = req.description
    await db.commit()
    return {
        "status": "updated",
        "subject": {"id": subject.id, "title": subject.title, "description": subject.description},
    }


@router.delete("/subjects/{subject_id}")
async def delete_subject(
    subject_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    subject = (
        await db.execute(select(Subject).where(Subject.id == subject_id))
    ).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Fan topilmadi")

    topic_ids = [
        row[0]
        for row in (
            await db.execute(select(Topic.id).where(Topic.subject_id == subject_id))
        ).all()
    ]
    if topic_ids:
        await _purge_topics(db, topic_ids)

    await db.delete(subject)
    await db.commit()
    return {"status": "deleted"}


@router.get("/subjects/{subject_id}/materials")
async def list_subject_materials(
    subject_id: int,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    materials = (
        await db.execute(
            select(SubjectMaterial)
            .where(SubjectMaterial.subject_id == subject_id)
            .order_by(SubjectMaterial.created_at.desc())
        )
    ).scalars().all()
    return [_material_public(m) for m in materials]


def _material_public(m: SubjectMaterial) -> dict:
    return {
        "id": m.id,
        "subject_id": m.subject_id,
        "material_type": m.material_type,
        "title": m.title,
        "detail": m.detail,
        "url": m.url,
        "created_at": iso(m.created_at),
    }


@router.post("/subjects/{subject_id}/materials")
async def create_subject_material(
    subject_id: int,
    req: SubjectMaterialCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if not (await db.execute(select(Subject.id).where(Subject.id == subject_id))).first():
        raise HTTPException(status_code=404, detail="Fan topilmadi")

    material = SubjectMaterial(
        subject_id=subject_id,
        material_type=req.material_type,
        title=req.title,
        detail=req.detail,
        url=req.url,
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    return {"status": "success", "material": _material_public(material)}


@router.put("/materials/{material_id}")
async def update_subject_material(
    material_id: int,
    req: SubjectMaterialCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    material = (
        await db.execute(select(SubjectMaterial).where(SubjectMaterial.id == material_id))
    ).scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material topilmadi")

    material.material_type = req.material_type
    material.title = req.title
    material.detail = req.detail
    material.url = req.url
    await db.commit()
    await db.refresh(material)
    return {"status": "success", "material": _material_public(material)}


@router.delete("/materials/{material_id}")
async def delete_subject_material(
    material_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    material = (
        await db.execute(select(SubjectMaterial).where(SubjectMaterial.id == material_id))
    ).scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material topilmadi")

    await db.delete(material)
    await db.commit()
    return {"status": "success", "message": "Material muvaffaqiyatli o'chirildi"}


# ---------------------------------------------------------------------------
# Dars jadvali
# ---------------------------------------------------------------------------

def _schedule_public(s: LessonSchedule) -> dict:
    return {
        "id": s.id,
        "subject_id": s.subject_id,
        "subject_title": s.subject.title if s.subject else "",
        "student_group": s.student_group,
        "day_of_week": s.day_of_week,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "room": s.room,
        "teacher_name": s.teacher_name,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "radius_meters": s.radius_meters,
        "created_at": iso(s.created_at),
    }


@router.get("/schedules/all")
async def list_all_schedules(
    student_group: Optional[str] = None,
    day_of_week: Optional[int] = Query(default=None, ge=1, le=7),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LessonSchedule).options(selectinload(LessonSchedule.subject))
    if student_group:
        stmt = stmt.where(LessonSchedule.student_group == student_group)
    if day_of_week:
        stmt = stmt.where(LessonSchedule.day_of_week == day_of_week)

    schedules = (
        await db.execute(
            stmt.order_by(LessonSchedule.day_of_week.asc(), LessonSchedule.start_time.asc())
        )
    ).scalars().all()
    return [_schedule_public(s) for s in schedules]


@router.post("/schedules")
async def create_schedule(
    req: LessonScheduleCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if not (await db.execute(select(Subject.id).where(Subject.id == req.subject_id))).first():
        raise HTTPException(status_code=404, detail="Fan topilmadi")
    if req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak")

    schedule = LessonSchedule(**req.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule, attribute_names=["subject"])
    return {"status": "success", "schedule": _schedule_public(schedule)}


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    req: LessonScheduleCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    schedule = (
        await db.execute(
            select(LessonSchedule)
            .options(selectinload(LessonSchedule.subject))
            .where(LessonSchedule.id == schedule_id)
        )
    ).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Dars jadvali topilmadi")
    if not (await db.execute(select(Subject.id).where(Subject.id == req.subject_id))).first():
        raise HTTPException(status_code=404, detail="Fan topilmadi")
    if req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak")

    for field, value in req.model_dump().items():
        setattr(schedule, field, value)
    await db.commit()
    await db.refresh(schedule, attribute_names=["subject"])
    return {"status": "success", "schedule": _schedule_public(schedule)}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    schedule = (
        await db.execute(select(LessonSchedule).where(LessonSchedule.id == schedule_id))
    ).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Dars jadvali topilmadi")

    await db.delete(schedule)
    await db.commit()
    return {"status": "success", "message": "Jadval muvaffaqiyatli o'chirildi"}


# ---------------------------------------------------------------------------
# Tibbiy lug'at
# ---------------------------------------------------------------------------

def _term_public(t: MedicalTerm) -> dict:
    return {
        "id": t.id,
        "word": t.word,
        "transcription": t.transcription or "",
        "gender": t.gender or "",
        "translation": t.translation,
        "category": t.category,
        "description": t.description or "",
        "exampleRu": t.example_ru or "",
        "exampleUz": t.example_uz or "",
    }


@router.get("/dictionary")
async def get_dictionary(
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=5000),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MedicalTerm)
    if category and category != "Barchasi":
        stmt = stmt.where(MedicalTerm.category == category)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            MedicalTerm.word.ilike(pattern) | MedicalTerm.translation.ilike(pattern)
        )
    terms = (
        await db.execute(stmt.order_by(MedicalTerm.word.asc()).limit(limit))
    ).scalars().all()
    return [_term_public(t) for t in terms]


@router.post("/dictionary")
async def create_dictionary_term(
    req: MedicalTermCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    word = req.word.strip()
    if (await db.execute(select(MedicalTerm.id).where(MedicalTerm.word == word))).first():
        raise HTTPException(status_code=400, detail="Bunday termin allaqachon mavjud")

    term = MedicalTerm(**{**req.model_dump(), "word": word})
    db.add(term)
    await db.commit()
    await db.refresh(term)
    return {"status": "success", "term": _term_public(term)}


@router.put("/dictionary/{term_id}")
async def update_dictionary_term(
    term_id: int,
    req: MedicalTermCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    term = (
        await db.execute(select(MedicalTerm).where(MedicalTerm.id == term_id))
    ).scalar_one_or_none()
    if not term:
        raise HTTPException(status_code=404, detail="Termin topilmadi")

    word = req.word.strip()
    duplicate = await db.execute(
        select(MedicalTerm.id).where(MedicalTerm.word == word, MedicalTerm.id != term_id)
    )
    if duplicate.first():
        raise HTTPException(status_code=400, detail="Bunday termin allaqachon mavjud")

    for field, value in req.model_dump().items():
        setattr(term, field, value)
    term.word = word
    await db.commit()
    await db.refresh(term)
    return {"status": "success", "term": _term_public(term)}


@router.delete("/dictionary/{term_id}")
async def delete_dictionary_term(
    term_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    term = (
        await db.execute(select(MedicalTerm).where(MedicalTerm.id == term_id))
    ).scalar_one_or_none()
    if not term:
        raise HTTPException(status_code=404, detail="Termin topilmadi")

    await db.delete(term)
    await db.commit()
    return {"status": "success", "message": "Termin muvaffaqiyatli o'chirildi"}


# ---------------------------------------------------------------------------
# Mavzular
# ---------------------------------------------------------------------------

def _split_materials(materials) -> tuple[str, str, list[str]]:
    """Materiallardan leksika/grammatika matni va video URL'larni ajratadi."""
    video_urls = [
        m.source_url for m in materials
        if m.material_type == MaterialType.video and m.source_url
    ]

    leksika = next(
        (m for m in materials if m.material_type == MaterialType.text and m.title == "Leksika"),
        None,
    )
    grammatika = next(
        (m for m in materials if m.material_type == MaterialType.text and m.title == "Grammatika"),
        None,
    )
    if not leksika and not grammatika:
        legacy = next((m for m in materials if m.material_type == MaterialType.text), None)
        if legacy:
            leksika = legacy

    # `raw_text` NULL bo'lishi mumkin — ilgari bu AttributeError berardi.
    return (
        (leksika.raw_text or "") if leksika else "",
        (grammatika.raw_text or "") if grammatika else "",
        video_urls,
    )


def _topic_public(topic: Topic) -> dict:
    leksika, grammatika, video_urls = _split_materials(topic.materials)
    return {
        "id": topic.id,
        "subject_id": topic.subject_id,
        "title": topic.title,
        "description": topic.description,
        "topic_type": topic.topic_type or "leksika",
        "status": topic.status.value if topic.status else "draft",
        "video_url": video_urls[0] if video_urls else None,
        "video_urls": video_urls,
        "leksika_content": leksika,
        "grammatika_content": grammatika,
        "content": leksika or grammatika or "",
    }


@router.get("/")
async def list_topics(
    subject_id: Optional[int] = None,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Topic).options(selectinload(Topic.materials))
    if subject_id:
        stmt = stmt.where(Topic.subject_id == subject_id)
    topics = (await db.execute(stmt.order_by(Topic.created_at.desc()))).scalars().all()
    return [_topic_public(t) for t in topics]


@router.post("/")
async def create_topic(
    req: TopicCreateRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if req.subject_id is not None:
        if not (await db.execute(select(Subject.id).where(Subject.id == req.subject_id))).first():
            raise HTTPException(status_code=404, detail="Fan topilmadi")

    topic = Topic(
        employee_user_id=staff.id,
        subject_id=req.subject_id,
        title=req.title.strip(),
        description=req.description,
        topic_type=req.topic_type or "leksika",
        status=TopicStatus.active,
    )
    db.add(topic)
    await db.flush()

    await _write_topic_materials(db, topic.id, staff.id, req)
    await db.commit()
    return {"status": "success", "topic_id": topic.id}


async def _write_topic_materials(
    db: AsyncSession, topic_id: int, uploader_id: int, req: TopicCreateRequest
) -> None:
    urls = [u for u in (req.video_urls or []) if u and u.strip()]
    if req.video_url and req.video_url.strip() and req.video_url not in urls:
        urls.insert(0, req.video_url.strip())

    for index, url in enumerate(urls):
        db.add(TopicMaterial(
            topic_id=topic_id,
            uploaded_by_user_id=uploader_id,
            material_type=MaterialType.video,
            title=f"{req.title} - Video {index + 1}",
            source_url=url.strip(),
        ))

    leksika = req.leksika_content or ""
    grammatika = req.grammatika_content or ""
    if not leksika and not grammatika and req.content:
        leksika = req.content

    for title, body in (("Leksika", leksika), ("Grammatika", grammatika)):
        if not body.strip():
            continue
        material = TopicMaterial(
            topic_id=topic_id,
            uploaded_by_user_id=uploader_id,
            material_type=MaterialType.text,
            title=title,
            raw_text=body.strip(),
        )
        db.add(material)
        await db.flush()

        for index, paragraph in enumerate(p.strip() for p in body.split("\n\n") if p.strip()):
            db.add(KnowledgeChunk(
                topic_id=topic_id,
                material_id=material.id,
                chunk_index=index,
                chunk_text=paragraph,
            ))


@router.get("/{topic_id}")
async def get_topic(
    topic_id: int,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    topic = (
        await db.execute(
            select(Topic).options(selectinload(Topic.materials)).where(Topic.id == topic_id)
        )
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")
    return _topic_public(topic)


@router.put("/{topic_id}")
async def update_topic(
    topic_id: int,
    req: TopicCreateRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    topic = (await db.execute(select(Topic).where(Topic.id == topic_id))).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")
    if req.subject_id is not None:
        if not (await db.execute(select(Subject.id).where(Subject.id == req.subject_id))).first():
            raise HTTPException(status_code=404, detail="Fan topilmadi")

    topic.title = req.title.strip()
    topic.description = req.description
    topic.subject_id = req.subject_id
    topic.topic_type = req.topic_type or "leksika"

    # Eski materiallar va bo'laklarni tozalab, qaytadan yozamiz.
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id == topic_id))
    await db.execute(delete(TopicMaterial).where(TopicMaterial.topic_id == topic_id))
    await _write_topic_materials(db, topic_id, staff.id, req)

    await db.commit()
    return {"status": "updated"}


async def _purge_topics(db: AsyncSession, topic_ids: list[int]) -> None:
    """Mavzularga bog'liq barcha yozuvlarni tozalaydi (FK xatolarining oldini oladi)."""
    # Avval test savollari — ON DELETE CASCADE ga tayanib bo'lmaydi (SQLite'da
    # u sukut bo'yicha o'chirilgan). Yetim qolgan savollar keyingi urinishda
    # unique constraint xatosiga olib kelardi.
    stale_attempts = select(QuizAttempt.id).where(QuizAttempt.topic_id.in_(topic_ids))
    await db.execute(
        delete(QuizQuestion).where(QuizQuestion.quiz_attempt_id.in_(stale_attempts))
    )
    await db.execute(delete(QuizAttempt).where(QuizAttempt.topic_id.in_(topic_ids)))
    await db.execute(
        update(StudentSession)
        .where(StudentSession.topic_id.in_(topic_ids))
        .values(topic_id=None)
    )
    await db.execute(
        delete(StudentTopicAccess).where(StudentTopicAccess.topic_id.in_(topic_ids))
    )
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.topic_id.in_(topic_ids)))
    await db.execute(delete(TopicMaterial).where(TopicMaterial.topic_id.in_(topic_ids)))
    await db.execute(delete(Topic).where(Topic.id.in_(topic_ids)))


@router.delete("/{topic_id}")
async def delete_topic(
    topic_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    topic = (await db.execute(select(Topic).where(Topic.id == topic_id))).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")

    await _purge_topics(db, [topic_id])
    await db.commit()
    return {"status": "deleted"}


async def _topic_content(db: AsyncSession, topic_id: int) -> tuple[Topic, str]:
    topic = (
        await db.execute(
            select(Topic).options(selectinload(Topic.materials)).where(Topic.id == topic_id)
        )
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")

    leksika, grammatika, _ = _split_materials(topic.materials)

    parts = []
    if leksika.strip():
        parts.append(f"## Leksika\n\n{leksika.strip()}")
    if grammatika.strip():
        parts.append(f"## Grammatika\n\n{grammatika.strip()}")

    return topic, ("\n\n".join(parts) if parts else (topic.description or ""))


@router.get("/{topic_id}/translation")
async def translate_topic(
    topic_id: int,
    language: str = "ru",
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    topic = (
        await db.execute(
            select(Topic).options(selectinload(Topic.materials)).where(Topic.id == topic_id)
        )
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Mavzu topilmadi")

    leksika, grammatika, _ = _split_materials(topic.materials)

    translated_title = topic.title
    translated_leksika = ""
    translated_grammatika = ""

    try:
        if leksika.strip():
            result = await ai_service.translate_topic(topic.title, leksika, language)
            translated_leksika = result["content"]
            translated_title = result["title"]

        if grammatika.strip():
            result = await ai_service.translate_topic(topic.title, grammatika, language)
            translated_grammatika = result["content"]
            if not translated_leksika:
                translated_title = result["title"]
    except Exception as exc:  # noqa: BLE001
        logger.error("Tarjima xatosi (topic=%s): %s", topic_id, exc, exc_info=True)
        raise HTTPException(
            status_code=502, detail="Tarjima xizmati hozir mavjud emas. Keyinroq urinib ko'ring."
        )

    return {
        "language": language,
        "title": translated_title,
        "leksika_content": translated_leksika,
        "grammatika_content": translated_grammatika,
        "content": translated_leksika or translated_grammatika or "",
    }


@router.get("/{topic_id}/pdf")
async def get_topic_pdf(
    topic_id: int,
    language: str = "uz",
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 404 ni tashqarida qoldiramiz — ilgari umumiy `except` uni 500 ga aylantirardi.
    topic, content = await _topic_content(db, topic_id)
    title = topic.title

    try:
        if language == "ru":
            translated = await ai_service.translate_topic(topic.title, content, language)
            title = translated["title"]
            content = translated["content"]

        filepath = pdf_service.generate_topic_pdf(title, content)
    except Exception as exc:  # noqa: BLE001
        logger.error("PDF yaratishda xatolik (topic=%s): %s", topic_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"Mavzu_{topic_id}.pdf",
        background=_cleanup(filepath),
    )


@router.post("/{topic_id}/ask")
async def ask_topic(
    topic_id: int,
    req: TopicAskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Savol matni bo'sh")

    topic, content = await _topic_content(db, topic_id)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Bu mavzu uchun material mavjud emas.")

    user_id = current_user.id
    limit = config.AI_QUESTION_DAILY_LIMIT

    used = await count_ai_questions_today(db, user_id)
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Kunlik savollar limiti tugadi (maksimal {limit} ta).",
                "limit": limit,
                "remaining": 0,
            },
        )

    try:
        answer = await ai_service.answer_topic_question(content, question, req.language)
    except Exception as exc:  # noqa: BLE001
        logger.error("AI javob xatosi (topic=%s): %s", topic_id, exc, exc_info=True)
        raise HTTPException(
            status_code=502, detail="Sun'iy intellekt hozir javob bera olmadi. Keyinroq urinib ko'ring."
        )

    session = (
        await db.execute(
            select(StudentSession).where(StudentSession.student_user_id == user_id)
        )
    ).scalar_one_or_none()
    if session is None:
        session = StudentSession(student_user_id=user_id, topic_id=topic.id, question_count=0)
        db.add(session)
    elif session.topic_id != topic.id:
        session.topic_id = topic.id
        session.question_count = 0

    session.state = SessionState.asking
    session.question_count += 1
    session.last_user_message = question

    db.add(NotificationLog(
        user_id=user_id,
        event_type="ai_question",
        payload={
            "topic_id": topic.id,
            "question": question,
            "answer": answer,
            "language": req.language,
        },
        is_read=True,  # o'z savoli — bildirishnoma sifatida ko'rsatilmaydi
    ))

    await db.commit()

    used += 1
    return {
        "answer": answer,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
    }
