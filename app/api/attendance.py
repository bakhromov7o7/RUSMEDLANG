"""Davomat — har bir dars uchun yo'qlama.

Davomat dars kesimida olinadi: sana + dars jadvalidagi juftlik. Shu sababli
fan bo'yicha foiz chiqadi va talaba aynan qaysi darsni qoldirganini ko'radi.

Qoidalar:

* belgilashni faqat xodim bajaradi, kelajakdagi sana rad etiladi;
* sana jadvaldagi hafta kuniga mos kelishi shart;
* talaba faqat o'z yozuvlarini ko'radi va faqat o'zi qoldirgan dars uchun
  sabab yubora oladi;
* sabab tasdiqlansa holat "sababli" ga o'tadi.
"""

import logging
import math
import os
from datetime import date as date_cls, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api._shared import as_utc, iso, tashkent_date
from app.core.security import (
    ensure_can_access_user,
    get_current_user,
    is_staff,
    require_staff,
)
from app.database import get_db
from app.core import config
from app.models import (
    AttendanceCheckIn,
    LocationViolation,
    ViolationStatus,
    AttendanceRecord,
    AttendanceStatus,
    ExcuseStatus,
    LocationStatus,
    LessonSchedule,
    NotificationLog,
    Subject,
    User,
    UserRole,
    utcnow,
)
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)
pdf_service = PDFService()

# Hisobot uchun eng uzun davr — juda katta oraliq PDF'ni ishlatib bo'lmas qiladi.
MAX_REPORT_DAYS = 120

_STATUS_LABELS = {
    AttendanceStatus.present: "Keldi",
    AttendanceStatus.absent: "Kelmadi",
    AttendanceStatus.late: "Kechikdi",
    AttendanceStatus.excused: "Sababli",
}

# Hisobot jadvalidagi qisqa belgilar
_STATUS_MARKS = {
    AttendanceStatus.present: "+",
    AttendanceStatus.absent: "-",
    AttendanceStatus.late: "K",
    AttendanceStatus.excused: "S",
}

# Foizga "kelgan" deb hisoblanadigan holatlar (sababli qoldirish jazolanmaydi).
_ATTENDED = (AttendanceStatus.present, AttendanceStatus.late, AttendanceStatus.excused)


def _cleanup(path: str) -> BackgroundTask:
    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


# ---------------------------------------------------------------------------
# Joylashuv
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6_371_000


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi masofa (metr).

    Yer sferasi bo'yicha hisoblanadi — bir necha kilometrlik masofalarda
    aniqligi yetarli.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def lesson_point(schedule: LessonSchedule) -> tuple[Optional[float], Optional[float], int]:
    """Dars nuqtasi va ruxsat etilgan radius.

    Jadvalda koordinata bo'lmasa, `.env` dagi umumiy kampus nuqtasi
    ishlatiladi. Ikkalasi ham bo'lmasa tekshiruv o'chadi.
    """
    radius = schedule.radius_meters or config.ATTENDANCE_RADIUS_METERS
    if schedule.latitude is not None and schedule.longitude is not None:
        return schedule.latitude, schedule.longitude, radius
    return config.CAMPUS_LATITUDE, config.CAMPUS_LONGITUDE, radius


def evaluate_location(
    schedule: LessonSchedule, latitude: float, longitude: float
) -> tuple[Optional[float], LocationStatus]:
    """Berilgan nuqta dars joyidami — masofa va holat qaytaradi."""
    point_lat, point_lon, radius = lesson_point(schedule)
    if point_lat is None or point_lon is None:
        # Dars joyi sozlanmagan — tekshirib bo'lmaydi.
        return None, LocationStatus.unknown
    distance = haversine_meters(point_lat, point_lon, latitude, longitude)
    status = LocationStatus.inside if distance <= radius else LocationStatus.outside
    return round(distance, 1), status


def _location_public(distance: Optional[float], status: LocationStatus) -> dict:
    return {
        "distance_meters": distance,
        "location_status": status.value,
        "location_label": {
            LocationStatus.inside: "Dars joyida",
            LocationStatus.outside: "Dars joyida emas",
            LocationStatus.unknown: "Tekshirilmadi",
        }[status],
    }


class AttendanceMarkItem(BaseModel):
    student_user_id: int
    status: str = Field(..., max_length=20)
    note: Optional[str] = Field(default=None, max_length=500)


class AttendanceMarkRequest(BaseModel):
    schedule_id: int
    lesson_date: date_cls
    records: List[AttendanceMarkItem] = Field(..., min_length=1, max_length=200)
    # Ustozning yo'qlama paytidagi joylashuvi (ixtiyoriy — ruxsat berilmasa
    # yuborilmaydi). Bloklamaydi, faqat yozib qo'yiladi.
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class CheckInRequest(BaseModel):
    """Talabaning "Men keldim" belgisi."""

    schedule_id: int
    lesson_date: date_cls
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ExcuseCreateRequest(BaseModel):
    record_id: int
    reason: str = Field(..., min_length=3, max_length=2000)


class ExcuseReviewRequest(BaseModel):
    approve: bool
    comment: Optional[str] = Field(default=None, max_length=500)


def _parse_status(value: str) -> AttendanceStatus:
    try:
        return AttendanceStatus(str(value).strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Holat noto'g'ri. Ruxsat etilganlari: present, absent, late, excused",
        )


def _record_public(record: AttendanceRecord, subject_title: Optional[str] = None) -> dict:
    return {
        "id": record.id,
        "student_user_id": record.student_user_id,
        "schedule_id": record.schedule_id,
        "subject_id": record.subject_id,
        "subject_title": subject_title,
        "student_group": record.student_group,
        "date": record.lesson_date.isoformat() if record.lesson_date else None,
        "status": record.status.value,
        "status_label": _STATUS_LABELS.get(record.status, record.status.value),
        "note": record.note,
        "excuse_status": record.excuse_status.value,
        "excuse_reason": record.excuse_reason,
        "excuse_reviewed_at": iso(record.excuse_reviewed_at),
        "created_at": iso(record.created_at),
    }


async def _load_schedule(db: AsyncSession, schedule_id: int) -> LessonSchedule:
    schedule = (
        await db.execute(select(LessonSchedule).where(LessonSchedule.id == schedule_id))
    ).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Dars jadvalda topilmadi")
    return schedule


def _ensure_markable(schedule: LessonSchedule, lesson_date: date_cls) -> None:
    """Sana kelajakda emasligini va hafta kuniga mos kelishini tekshiradi."""
    if lesson_date > date_cls.today():
        raise HTTPException(
            status_code=400, detail="Kelajakdagi dars uchun davomat belgilab bo'lmaydi"
        )
    if lesson_date.isoweekday() != schedule.day_of_week:
        raise HTTPException(
            status_code=400,
            detail="Tanlangan sana bu darsning hafta kuniga to'g'ri kelmaydi",
        )


async def _group_students(db: AsyncSession, student_group: str) -> List[User]:
    return (
        await db.execute(
            select(User)
            .where(
                User.role == UserRole.student,
                User.is_active.is_(True),
                User.student_group == student_group,
            )
            .order_by(User.full_name)
        )
    ).scalars().all()


# ---------------------------------------------------------------------------
# Xodim: darslar, ro'yxat va belgilash
# ---------------------------------------------------------------------------

@router.get("/lessons")
async def lessons_for_date(
    lesson_date: date_cls = Query(..., alias="date"),
    student_group: Optional[str] = None,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Berilgan sanadagi darslar va ularning belgilanish holati."""
    stmt = select(LessonSchedule, Subject.title).outerjoin(
        Subject, Subject.id == LessonSchedule.subject_id
    ).where(LessonSchedule.day_of_week == lesson_date.isoweekday())
    if student_group:
        stmt = stmt.where(LessonSchedule.student_group == student_group)

    rows = (await db.execute(stmt.order_by(LessonSchedule.start_time))).all()
    if not rows:
        return []

    schedule_ids = [row.LessonSchedule.id for row in rows]
    marked_rows = (
        await db.execute(
            select(AttendanceRecord.schedule_id, func.count(AttendanceRecord.id))
            .where(
                AttendanceRecord.schedule_id.in_(schedule_ids),
                AttendanceRecord.lesson_date == lesson_date,
            )
            .group_by(AttendanceRecord.schedule_id)
        )
    ).all()
    marked = {row[0]: row[1] for row in marked_rows}

    counts_rows = (
        await db.execute(
            select(User.student_group, func.count(User.id))
            .where(User.role == UserRole.student, User.is_active.is_(True))
            .group_by(User.student_group)
        )
    ).all()
    group_sizes = {row[0]: row[1] for row in counts_rows}

    return [
        {
            "schedule_id": row.LessonSchedule.id,
            "subject_id": row.LessonSchedule.subject_id,
            "subject_title": row.title or "Dars",
            "student_group": row.LessonSchedule.student_group,
            "start_time": row.LessonSchedule.start_time,
            "end_time": row.LessonSchedule.end_time,
            "room": row.LessonSchedule.room,
            "teacher_name": row.LessonSchedule.teacher_name,
            "student_count": group_sizes.get(row.LessonSchedule.student_group, 0),
            "marked_count": marked.get(row.LessonSchedule.id, 0),
            "is_marked": marked.get(row.LessonSchedule.id, 0) > 0,
        }
        for row in rows
    ]


@router.get("/roster")
async def lesson_roster(
    schedule_id: int,
    lesson_date: date_cls = Query(..., alias="date"),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Dars uchun talabalar ro'yxati va ularning joriy holati."""
    schedule = await _load_schedule(db, schedule_id)
    subject_title = (
        await db.execute(select(Subject.title).where(Subject.id == schedule.subject_id))
    ).scalar_one_or_none()

    students = await _group_students(db, schedule.student_group)
    existing = {
        record.student_user_id: record
        for record in (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.schedule_id == schedule_id,
                    AttendanceRecord.lesson_date == lesson_date,
                )
            )
        ).scalars().all()
    }
    # Talabalarning "Men keldim" belgisi va joylashuvi.
    check_ins = {
        item.student_user_id: item
        for item in (
            await db.execute(
                select(AttendanceCheckIn).where(
                    AttendanceCheckIn.schedule_id == schedule_id,
                    AttendanceCheckIn.lesson_date == lesson_date,
                )
            )
        ).scalars().all()
    }
    point_lat, point_lon, radius = lesson_point(schedule)

    return {
        "schedule_id": schedule.id,
        "subject_id": schedule.subject_id,
        "subject_title": subject_title or "Dars",
        "student_group": schedule.student_group,
        "date": lesson_date.isoformat(),
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "room": schedule.room,
        # Dars joyi sozlanganmi — ilova shunga qarab ogohlantiradi.
        "location_configured": point_lat is not None and point_lon is not None,
        "radius_meters": radius,
        # Ilova shu ro'yxatni to'g'ridan-to'g'ri ko'rsatadi: holat `null` bo'lsa
        # talaba hali belgilanmagan.
        "students": [
            {
                "student_user_id": student.id,
                "full_name": student.full_name,
                "avatar_path": student.avatar_path,
                "status": existing[student.id].status.value if student.id in existing else None,
                "note": existing[student.id].note if student.id in existing else None,
                "excuse_status": (
                    existing[student.id].excuse_status.value if student.id in existing else "none"
                ),
                "record_id": existing[student.id].id if student.id in existing else None,
                **(
                    {
                        **_location_public(
                            check_ins[student.id].distance_meters,
                            check_ins[student.id].status,
                        ),
                        "checked_in_at": iso(check_ins[student.id].created_at),
                    }
                    if student.id in check_ins
                    else {
                        "distance_meters": None,
                        "location_status": None,
                        "location_label": "Belgilanmagan",
                        "checked_in_at": None,
                    }
                ),
            }
            for student in students
        ],
    }


@router.post("/mark")
async def mark_attendance(
    req: AttendanceMarkRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Bir darsning davomatini saqlaydi (mavjud yozuvlar yangilanadi)."""
    schedule = await _load_schedule(db, req.schedule_id)
    _ensure_markable(schedule, req.lesson_date)

    students = {s.id: s for s in await _group_students(db, schedule.student_group)}
    unknown = [item.student_user_id for item in req.records if item.student_user_id not in students]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Ro'yxatda bu guruhga tegishli bo'lmagan talaba bor",
        )

    existing = {
        record.student_user_id: record
        for record in (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.schedule_id == schedule.id,
                    AttendanceRecord.lesson_date == req.lesson_date,
                )
            )
        ).scalars().all()
    }

    subject_title = (
        await db.execute(select(Subject.title).where(Subject.id == schedule.subject_id))
    ).scalar_one_or_none() or "Dars"

    # Ustozning yo'qlama paytidagi joylashuvi — bloklamaydi, faqat yoziladi.
    teacher_distance: Optional[float] = None
    teacher_status = LocationStatus.unknown
    if req.latitude is not None and req.longitude is not None:
        teacher_distance, teacher_status = evaluate_location(
            schedule, req.latitude, req.longitude
        )

    saved = 0
    for item in req.records:
        status = _parse_status(item.status)
        record = existing.get(item.student_user_id)
        previous = record.status if record else None

        if record is None:
            record = AttendanceRecord(
                student_user_id=item.student_user_id,
                schedule_id=schedule.id,
                subject_id=schedule.subject_id,
                student_group=schedule.student_group,
                lesson_date=req.lesson_date,
            )
            db.add(record)

        record.status = status
        record.note = item.note
        record.marked_by_user_id = staff.id
        record.marked_latitude = req.latitude
        record.marked_longitude = req.longitude
        record.marked_distance_meters = teacher_distance
        # Qo'lda "sababli" qilinsa, kutilayotgan so'rov yopiladi.
        if status == AttendanceStatus.excused and record.excuse_status == ExcuseStatus.pending:
            record.excuse_status = ExcuseStatus.approved
            record.excuse_reviewed_by_user_id = staff.id
            record.excuse_reviewed_at = utcnow()
        saved += 1

        # Bildirishnoma faqat holat o'zgarganda va faqat qoldirilgan darsda.
        if status in (AttendanceStatus.absent, AttendanceStatus.late) and previous != status:
            db.add(NotificationLog(
                user_id=item.student_user_id,
                event_type="attendance_absent",
                payload={
                    "subject": subject_title,
                    "date": req.lesson_date.isoformat(),
                    "status": status.value,
                    "status_label": _STATUS_LABELS[status],
                    "start_time": schedule.start_time,
                },
            ))

    await db.commit()
    return {
        "status": "success",
        "saved": saved,
        "schedule_id": schedule.id,
        "date": req.lesson_date.isoformat(),
        "teacher_location": _location_public(teacher_distance, teacher_status),
    }


# ---------------------------------------------------------------------------
# Talaba: o'z davomati
# ---------------------------------------------------------------------------

def _summarize(records: List[AttendanceRecord], titles: dict) -> dict:
    total = len(records)
    attended = sum(1 for r in records if r.status in _ATTENDED)
    by_subject: dict = {}
    for record in records:
        key = record.subject_id or 0
        bucket = by_subject.setdefault(
            key,
            {
                "subject_id": record.subject_id,
                "subject_title": titles.get(record.subject_id, "Boshqa"),
                "total": 0,
                "attended": 0,
                "absent": 0,
                "late": 0,
                "excused": 0,
            },
        )
        bucket["total"] += 1
        if record.status in _ATTENDED:
            bucket["attended"] += 1
        if record.status == AttendanceStatus.absent:
            bucket["absent"] += 1
        elif record.status == AttendanceStatus.late:
            bucket["late"] += 1
        elif record.status == AttendanceStatus.excused:
            bucket["excused"] += 1

    subjects = sorted(
        (
            {**bucket, "percent": round(bucket["attended"] / bucket["total"] * 100, 1)}
            for bucket in by_subject.values()
            if bucket["total"]
        ),
        key=lambda x: x["percent"],
    )

    return {
        "total": total,
        "attended": attended,
        "absent": sum(1 for r in records if r.status == AttendanceStatus.absent),
        "late": sum(1 for r in records if r.status == AttendanceStatus.late),
        "excused": sum(1 for r in records if r.status == AttendanceStatus.excused),
        "percent": round(attended / total * 100, 1) if total else 0.0,
        "subjects": subjects,
    }


async def _records_for_student(
    db: AsyncSession,
    student_id: int,
    date_from: Optional[date_cls],
    date_to: Optional[date_cls],
) -> tuple[List[AttendanceRecord], dict]:
    stmt = select(AttendanceRecord).where(AttendanceRecord.student_user_id == student_id)
    if date_from:
        stmt = stmt.where(AttendanceRecord.lesson_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceRecord.lesson_date <= date_to)

    records = (
        await db.execute(stmt.order_by(AttendanceRecord.lesson_date.desc()))
    ).scalars().all()

    titles: dict = {}
    subject_ids = {r.subject_id for r in records if r.subject_id}
    if subject_ids:
        rows = await db.execute(
            select(Subject.id, Subject.title).where(Subject.id.in_(subject_ids))
        )
        titles = {row[0]: row[1] for row in rows.all()}
    return records, titles


@router.get("/my")
async def my_attendance(
    date_from: Optional[date_cls] = Query(default=None, alias="from"),
    date_to: Optional[date_cls] = Query(default=None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    records, titles = await _records_for_student(db, current_user.id, date_from, date_to)
    return {
        "summary": _summarize(records, titles),
        "records": [_record_public(r, titles.get(r.subject_id)) for r in records],
    }


@router.get("/summary/{student_id}")
async def student_summary(
    student_id: int,
    date_from: Optional[date_cls] = Query(default=None, alias="from"),
    date_to: Optional[date_cls] = Query(default=None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_id)
    records, titles = await _records_for_student(db, student_id, date_from, date_to)
    return {"student_id": student_id, "summary": _summarize(records, titles)}


# ---------------------------------------------------------------------------
# Talaba joylashuvi: "Men keldim" va dars vaqtidagi tekshiruv
# ---------------------------------------------------------------------------

# Tushuntirish yuborish uchun beriladigan vaqt.
EXPLAIN_WINDOW_HOURS = 12


def _now_hhmm() -> str:
    """Toshkent vaqti bo'yicha joriy soat (HH:MM)."""
    local = utcnow() + config.TASHKENT_OFFSET
    return local.strftime("%H:%M")


async def _current_lesson(db: AsyncSession, student: User) -> Optional[LessonSchedule]:
    """Talabaning guruhida hozir ketayotgan dars (bo'lsa)."""
    group = (student.student_group or "").strip()
    if not group:
        return None

    today = tashkent_date(utcnow()) or date_cls.today()
    now = _now_hhmm()
    return (
        await db.execute(
            select(LessonSchedule)
            .where(
                LessonSchedule.student_group == group,
                LessonSchedule.day_of_week == today.isoweekday(),
                LessonSchedule.start_time <= now,
                LessonSchedule.end_time >= now,
            )
            .order_by(LessonSchedule.start_time)
        )
    ).scalars().first()


def _violation_public(violation: LocationViolation, subject_title: Optional[str] = None) -> dict:
    remaining = (
        as_utc(violation.explain_deadline) - utcnow()
        if violation.explain_deadline
        else None
    )
    return {
        "id": violation.id,
        "student_user_id": violation.student_user_id,
        "schedule_id": violation.schedule_id,
        "subject_id": violation.subject_id,
        "subject_title": subject_title,
        "date": violation.lesson_date.isoformat() if violation.lesson_date else None,
        "detected_at": iso(violation.detected_at),
        "distance_meters": violation.distance_meters,
        "status": violation.status.value,
        "explain_deadline": iso(violation.explain_deadline),
        "hours_left": (
            max(round(remaining.total_seconds() / 3600, 1), 0) if remaining else 0
        ),
        "explanation": violation.explanation,
        "explained_at": iso(violation.explained_at),
        "review_comment": violation.review_comment,
    }


async def _expire_overdue(db: AsyncSession) -> None:
    """Muddati o'tgan, javobsiz qolgan ogohlantirishlarni yopadi."""
    overdue = (
        await db.execute(
            select(LocationViolation).where(
                LocationViolation.status == ViolationStatus.pending,
                LocationViolation.explain_deadline < utcnow(),
            )
        )
    ).scalars().all()
    if not overdue:
        return
    for violation in overdue:
        violation.status = ViolationStatus.expired
    await db.commit()


@router.post("/check-in")
async def check_in(
    req: CheckInRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Talaba "Men keldim" deb belgilaydi va joylashuvini yuboradi.

    Bu davomatni avtomatik qo'ymaydi — ustoz ro'yxatida talabaning dars
    joyida ekani ko'rinadi va qarorni ustoz qabul qiladi.
    """
    schedule = await _load_schedule(db, req.schedule_id)
    if (current_user.student_group or "").strip() != schedule.student_group:
        raise HTTPException(status_code=403, detail="Bu dars sizning guruhingizga tegishli emas")
    if req.lesson_date > date_cls.today():
        raise HTTPException(status_code=400, detail="Kelajakdagi dars uchun belgilab bo'lmaydi")

    distance, status = evaluate_location(schedule, req.latitude, req.longitude)

    existing = (
        await db.execute(
            select(AttendanceCheckIn).where(
                AttendanceCheckIn.student_user_id == current_user.id,
                AttendanceCheckIn.schedule_id == schedule.id,
                AttendanceCheckIn.lesson_date == req.lesson_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = AttendanceCheckIn(
            student_user_id=current_user.id,
            schedule_id=schedule.id,
            lesson_date=req.lesson_date,
        )
        db.add(existing)

    existing.latitude = req.latitude
    existing.longitude = req.longitude
    existing.distance_meters = distance
    existing.status = status
    existing.created_at = utcnow()

    await db.commit()
    return {"status": "success", **_location_public(distance, status)}


@router.post("/location-ping")
async def location_ping(
    req: CheckInRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dars vaqtidagi joylashuv tekshiruvi.

    Ilova dars davomida (ochiq bo'lganda yoki hududdan chiqish hodisasida)
    shu endpointga joylashuvni yuboradi. Talaba dars joyidan tashqarida
    bo'lsa, unga ogohlantirish yuboriladi va 12 soat ichida tushuntirish
    berish so'raladi.

    `schedule_id` 0 bo'lsa, server joriy darsni jadvaldan o'zi topadi.
    """
    schedule: Optional[LessonSchedule] = None
    if req.schedule_id:
        schedule = await _load_schedule(db, req.schedule_id)
    else:
        schedule = await _current_lesson(db, current_user)

    if schedule is None:
        # Hozir dars yo'q — tekshiradigan narsa ham yo'q.
        return {"status": "no_lesson", "violation": None}

    distance, status = evaluate_location(schedule, req.latitude, req.longitude)
    lesson_date = tashkent_date(utcnow()) or date_cls.today()

    if status != LocationStatus.outside:
        return {"status": status.value, "violation": None, **_location_public(distance, status)}

    # Shu dars uchun ogohlantirish allaqachon berilganmi?
    existing = (
        await db.execute(
            select(LocationViolation).where(
                LocationViolation.student_user_id == current_user.id,
                LocationViolation.schedule_id == schedule.id,
                LocationViolation.lesson_date == lesson_date,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "status": "already_reported",
            "violation": _violation_public(existing),
            **_location_public(distance, status),
        }

    subject_title = (
        await db.execute(select(Subject.title).where(Subject.id == schedule.subject_id))
    ).scalar_one_or_none() or "Dars"

    deadline = utcnow() + timedelta(hours=EXPLAIN_WINDOW_HOURS)
    violation = LocationViolation(
        student_user_id=current_user.id,
        schedule_id=schedule.id,
        subject_id=schedule.subject_id,
        lesson_date=lesson_date,
        latitude=req.latitude,
        longitude=req.longitude,
        distance_meters=distance,
        status=ViolationStatus.pending,
        explain_deadline=deadline,
    )
    db.add(violation)

    db.add(NotificationLog(
        user_id=current_user.id,
        event_type="location_violation",
        payload={
            "subject": subject_title,
            "date": lesson_date.isoformat(),
            "distance_meters": distance,
            "deadline": deadline.isoformat(),
            "message": (
                f"Dars vaqtida ({subject_title}) o'quv binosida emasligingiz "
                f"aniqlandi. {EXPLAIN_WINDOW_HOURS} soat ichida sababini "
                "tushuntirib so'rov yuborishingiz kerak."
            ),
        },
    ))

    await db.commit()
    await db.refresh(violation)
    return {
        "status": "violation",
        "violation": _violation_public(violation, subject_title),
        **_location_public(distance, status),
    }


class ViolationExplainRequest(BaseModel):
    explanation: str = Field(..., min_length=3, max_length=2000)


class ViolationReviewRequest(BaseModel):
    accept: bool
    comment: Optional[str] = Field(default=None, max_length=500)


@router.get("/violations")
async def list_violations(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=300),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ogohlantirishlar. Talaba o'zinikini, xodim hammasini ko'radi."""
    await _expire_overdue(db)

    stmt = (
        select(LocationViolation, User.full_name, User.student_group, Subject.title)
        .join(User, User.id == LocationViolation.student_user_id)
        .outerjoin(Subject, Subject.id == LocationViolation.subject_id)
    )
    if not is_staff(current_user):
        stmt = stmt.where(LocationViolation.student_user_id == current_user.id)
    if status_filter:
        try:
            stmt = stmt.where(LocationViolation.status == ViolationStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Noto'g'ri status qiymati")

    rows = (
        await db.execute(stmt.order_by(LocationViolation.detected_at.desc()).limit(limit))
    ).all()

    return [
        {
            **_violation_public(row.LocationViolation, row.title),
            "student_name": row.full_name,
            "student_group_name": row.student_group,
        }
        for row in rows
    ]


@router.get("/violations/pending-count")
async def violations_pending_count(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _expire_overdue(db)
    total = (
        await db.execute(
            select(func.count(LocationViolation.id)).where(
                LocationViolation.status == ViolationStatus.submitted
            )
        )
    ).scalar() or 0
    return {"count": total}


@router.post("/violations/{violation_id}/explain")
async def explain_violation(
    violation_id: int,
    req: ViolationExplainRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Talaba 12 soat ichida sababini tushuntiradi."""
    violation = (
        await db.execute(select(LocationViolation).where(LocationViolation.id == violation_id))
    ).scalar_one_or_none()
    if not violation:
        raise HTTPException(status_code=404, detail="Ogohlantirish topilmadi")
    if violation.student_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu ogohlantirish sizga tegishli emas")
    if violation.status not in (ViolationStatus.pending, ViolationStatus.rejected):
        raise HTTPException(status_code=409, detail="Bu ogohlantirish allaqachon ko'rib chiqilgan")
    if as_utc(violation.explain_deadline) < utcnow():
        violation.status = ViolationStatus.expired
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail=f"Tushuntirish muddati ({EXPLAIN_WINDOW_HOURS} soat) o'tib ketdi",
        )

    violation.explanation = req.explanation.strip()
    violation.explained_at = utcnow()
    violation.status = ViolationStatus.submitted
    await db.commit()
    await db.refresh(violation)
    return {"status": "success", "violation": _violation_public(violation)}


@router.post("/violations/{violation_id}/review")
async def review_violation(
    violation_id: int,
    req: ViolationReviewRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Xodim tushuntirishni qabul qiladi yoki rad etadi."""
    violation = (
        await db.execute(select(LocationViolation).where(LocationViolation.id == violation_id))
    ).scalar_one_or_none()
    if not violation:
        raise HTTPException(status_code=404, detail="Ogohlantirish topilmadi")
    if violation.status not in (ViolationStatus.submitted, ViolationStatus.expired):
        raise HTTPException(status_code=409, detail="Bu ogohlantirish ko'rib chiqishga tayyor emas")

    violation.status = (
        ViolationStatus.accepted if req.accept else ViolationStatus.rejected
    )
    violation.reviewed_by_user_id = staff.id
    violation.reviewed_at = utcnow()
    violation.review_comment = req.comment

    db.add(NotificationLog(
        user_id=violation.student_user_id,
        event_type="violation_reviewed",
        payload={
            "accepted": bool(req.accept),
            "comment": req.comment,
            "date": violation.lesson_date.isoformat() if violation.lesson_date else None,
        },
    ))

    await db.commit()
    await db.refresh(violation)
    return {"status": "success", "violation": _violation_public(violation)}


# ---------------------------------------------------------------------------
# Sabab (excuse)
# ---------------------------------------------------------------------------

@router.post("/excuses", status_code=201)
async def submit_excuse(
    req: ExcuseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Talaba qoldirgan darsi uchun sabab yuboradi."""
    record = (
        await db.execute(select(AttendanceRecord).where(AttendanceRecord.id == req.record_id))
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Davomat yozuvi topilmadi")
    if record.student_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu yozuv sizga tegishli emas")
    if record.status not in (AttendanceStatus.absent, AttendanceStatus.late):
        raise HTTPException(
            status_code=400, detail="Sabab faqat qoldirilgan yoki kechikilgan dars uchun yuboriladi"
        )
    if record.excuse_status == ExcuseStatus.pending:
        raise HTTPException(status_code=409, detail="Bu dars uchun sabab allaqachon yuborilgan")
    if record.excuse_status == ExcuseStatus.approved:
        raise HTTPException(status_code=409, detail="Bu dars uchun sabab allaqachon tasdiqlangan")

    record.excuse_status = ExcuseStatus.pending
    record.excuse_reason = req.reason.strip()
    record.excuse_reviewed_by_user_id = None
    record.excuse_reviewed_at = None
    await db.commit()
    await db.refresh(record)
    return {"status": "success", "record": _record_public(record)}


@router.get("/excuses")
async def list_excuses(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(200, ge=1, le=500),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AttendanceRecord, User.full_name, User.student_group, Subject.title)
        .join(User, User.id == AttendanceRecord.student_user_id)
        .outerjoin(Subject, Subject.id == AttendanceRecord.subject_id)
    )
    if status_filter and status_filter != "all":
        try:
            stmt = stmt.where(AttendanceRecord.excuse_status == ExcuseStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Noto'g'ri status qiymati")
    else:
        stmt = stmt.where(AttendanceRecord.excuse_status != ExcuseStatus.none)

    rows = (
        await db.execute(stmt.order_by(AttendanceRecord.lesson_date.desc()).limit(limit))
    ).all()

    return [
        {
            **_record_public(row.AttendanceRecord, row.title),
            "student_name": row.full_name,
            "student_group_name": row.student_group,
        }
        for row in rows
    ]


@router.get("/excuses/pending-count")
async def pending_excuses_count(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(
            select(func.count(AttendanceRecord.id)).where(
                AttendanceRecord.excuse_status == ExcuseStatus.pending
            )
        )
    ).scalar() or 0
    return {"count": total}


@router.post("/excuses/{record_id}/review")
async def review_excuse(
    record_id: int,
    req: ExcuseReviewRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Xodim sababni tasdiqlaydi yoki rad etadi."""
    record = (
        await db.execute(select(AttendanceRecord).where(AttendanceRecord.id == record_id))
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Davomat yozuvi topilmadi")
    if record.excuse_status != ExcuseStatus.pending:
        raise HTTPException(status_code=409, detail="Bu sabab allaqachon ko'rib chiqilgan")

    subject_title = (
        await db.execute(select(Subject.title).where(Subject.id == record.subject_id))
    ).scalar_one_or_none() or "Dars"

    if req.approve:
        record.excuse_status = ExcuseStatus.approved
        record.status = AttendanceStatus.excused
    else:
        record.excuse_status = ExcuseStatus.rejected
    record.excuse_reviewed_by_user_id = staff.id
    record.excuse_reviewed_at = utcnow()
    if req.comment:
        record.note = req.comment

    db.add(NotificationLog(
        user_id=record.student_user_id,
        event_type="excuse_reviewed",
        payload={
            "subject": subject_title,
            "date": record.lesson_date.isoformat() if record.lesson_date else None,
            "approved": bool(req.approve),
            "comment": req.comment,
        },
    ))

    await db.commit()
    await db.refresh(record)
    return {"status": "success", "record": _record_public(record, subject_title)}


# ---------------------------------------------------------------------------
# Guruh hisoboti
# ---------------------------------------------------------------------------

async def _group_report(
    db: AsyncSession, student_group: str, date_from: date_cls, date_to: date_cls
) -> dict:
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="Tugash sanasi boshlanish sanasidan oldin")
    if (date_to - date_from).days > MAX_REPORT_DAYS:
        raise HTTPException(
            status_code=400, detail=f"Davr juda uzun (maksimal {MAX_REPORT_DAYS} kun)"
        )

    students = await _group_students(db, student_group)
    records = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.student_group == student_group,
                AttendanceRecord.lesson_date >= date_from,
                AttendanceRecord.lesson_date <= date_to,
            )
        )
    ).scalars().all()

    dates = sorted({r.lesson_date for r in records})
    by_student: dict = {}
    for record in records:
        by_student.setdefault(record.student_user_id, {})[record.lesson_date] = record.status

    rows = []
    for student in students:
        marks = by_student.get(student.id, {})
        total = len(marks)
        attended = sum(1 for status in marks.values() if status in _ATTENDED)
        rows.append({
            "student_user_id": student.id,
            "full_name": student.full_name,
            "total": total,
            "attended": attended,
            "absent": sum(1 for s in marks.values() if s == AttendanceStatus.absent),
            "percent": round(attended / total * 100, 1) if total else 0.0,
            "marks": {d.isoformat(): _STATUS_MARKS[marks[d]] for d in marks},
        })

    overall_total = sum(row["total"] for row in rows)
    overall_attended = sum(row["attended"] for row in rows)

    return {
        "student_group": student_group,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "students": rows,
        "percent": (
            round(overall_attended / overall_total * 100, 1) if overall_total else 0.0
        ),
        "legend": {mark: _STATUS_LABELS[status] for status, mark in _STATUS_MARKS.items()},
    }


@router.get("/group")
async def group_report(
    student_group: str,
    date_from: date_cls = Query(..., alias="from"),
    date_to: date_cls = Query(..., alias="to"),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    return await _group_report(db, student_group, date_from, date_to)


@router.get("/group/report/pdf")
async def group_report_pdf(
    student_group: str,
    date_from: date_cls = Query(..., alias="from"),
    date_to: date_cls = Query(..., alias="to"),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    report = await _group_report(db, student_group, date_from, date_to)
    try:
        filepath = pdf_service.generate_attendance_report(report)
    except Exception as exc:  # noqa: BLE001
        logger.error("Davomat PDF xatosi (%s): %s", student_group, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF yaratishda xatolik yuz berdi")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"Davomat_{student_group}.pdf",
        background=_cleanup(filepath),
    )


# ---------------------------------------------------------------------------
# Boshqa modullar uchun yordamchi
# ---------------------------------------------------------------------------

async def attendance_percent(db: AsyncSession, student_id: int) -> tuple[float, int, int]:
    """Talabaning umumiy davomat foizi — akademik statistikada ishlatiladi."""
    rows = (
        await db.execute(
            select(AttendanceRecord.status).where(
                AttendanceRecord.student_user_id == student_id
            )
        )
    ).scalars().all()
    total = len(rows)
    attended = sum(1 for status in rows if status in _ATTENDED)
    percent = round(attended / total * 100, 1) if total else 0.0
    return percent, attended, total


async def unmarked_lessons_today(db: AsyncSession) -> int:
    """Bugun bo'lib o'tgan, lekin davomati belgilanmagan darslar soni."""
    today = date_cls.today()
    schedules = (
        await db.execute(
            select(LessonSchedule.id).where(LessonSchedule.day_of_week == today.isoweekday())
        )
    ).scalars().all()
    if not schedules:
        return 0

    marked = (
        await db.execute(
            select(AttendanceRecord.schedule_id)
            .where(
                AttendanceRecord.schedule_id.in_(schedules),
                AttendanceRecord.lesson_date == today,
            )
            .distinct()
        )
    ).scalars().all()
    return max(len(schedules) - len(set(marked)), 0)


def default_report_range() -> tuple[date_cls, date_cls]:
    """Sukut bo'yicha oxirgi 30 kun — ilova hisobotni shu oraliqda ochadi."""
    today = date_cls.today()
    return today - timedelta(days=30), today
