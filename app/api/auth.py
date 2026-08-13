import logging
import re
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import (
    as_utc,
    duration_seconds,
    iso,
    load_ai_questions,
    tashkent_date,
)
from app.core.security import (
    create_access_token,
    ensure_can_access_user,
    get_current_user,
    hash_password,
    require_staff,
    require_superadmin,
    verify_password,
)
from app.database import get_db
from app.models import (
    ApplicationStatus,
    ClinicalArenaAttempt,
    ExcuseStatus,
    HomeworkSubmission,
    LessonSchedule,
    NotificationLog,
    QuizAttempt,
    QuizAttemptStatus,
    QuizQuestion,
    StudentApplication,
    StudentGroup,
    Subject,
    Topic,
    User,
    UserRole,
    utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)

LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,100}$")


def _normalize_login(value: str) -> str:
    return value.strip().lower()


def _validate_login(value: str) -> str:
    normalized = _normalize_login(value)
    if not LOGIN_PATTERN.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="Login 3-100 ta belgidan iborat bo'lib, faqat harf, raqam, nuqta, tire va pastki chiziqdan tashkil topishi kerak",
        )
    return normalized


def _user_public(user: User) -> dict:
    return {
        "id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "username": user.username,
        "role": user.role.value,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "phone_number": user.phone_number,
        "student_group": user.student_group or "",
        "parent_name": user.parent_name,
        "parent_phone": user.parent_phone,
        "birth_date": user.birth_date,
        "notes": user.notes,
        "avatar_path": user.avatar_path,
        "department": user.department,
        "degree": user.degree,
        "bio": user.bio,
        "preferred_language": user.preferred_language or "uz",
        "created_at": iso(user.created_at),
    }


async def _login_taken(
    db: AsyncSession,
    login: str,
    exclude_user_id: Optional[int] = None,
    exclude_application_id: Optional[int] = None,
) -> bool:
    stmt = select(User.id).where(User.login == login)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    if (await db.execute(stmt)).first():
        return True

    # Ko'rib chiqilmagan arizalar ham loginni band qiladi — tasdiqlanayotgan
    # arizaning o'zi bundan mustasno.
    pending_stmt = select(StudentApplication.id).where(
        StudentApplication.login == login,
        StudentApplication.status == ApplicationStatus.pending,
    )
    if exclude_application_id is not None:
        pending_stmt = pending_stmt.where(StudentApplication.id != exclude_application_id)
    return (await db.execute(pending_stmt)).first() is not None


# ---------------------------------------------------------------------------
# Ro'yxatdan o'tish va kirish
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    login: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=72)
    full_name: str = Field(..., min_length=2, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    student_group: Optional[str] = Field(default=None, max_length=100)
    parent_name: Optional[str] = Field(default=None, max_length=255)
    parent_phone: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=72)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Talaba arizasi. Ustoz tasdiqlagunicha tizimga kira olmaydi."""
    login = _validate_login(req.login)

    if await _login_taken(db, login):
        raise HTTPException(status_code=400, detail="Bu login allaqachon band")

    application = StudentApplication(
        login=login,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        phone_number=req.phone_number,
        student_group=req.student_group,
        parent_name=req.parent_name,
        parent_phone=req.parent_phone,
        birth_date=req.birth_date,
        note=req.note,
        status=ApplicationStatus.pending,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    return {
        "status": "pending",
        "message": "Arizangiz qabul qilindi. Ustoz tasdiqlagach tizimga kira olasiz.",
        "application_id": application.id,
    }


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    login_value = _normalize_login(req.login)

    user = (
        await db.execute(select(User).where(User.login == login_value))
    ).scalar_one_or_none()

    if user is None:
        # Foydalanuvchi topilmasa — ehtimol ariza hali ko'rib chiqilmagan.
        application = (
            await db.execute(
                select(StudentApplication)
                .where(StudentApplication.login == login_value)
                .order_by(StudentApplication.created_at.desc())
            )
        ).scalars().first()

        if application and application.status == ApplicationStatus.pending:
            raise HTTPException(
                status_code=403,
                detail="Arizangiz ko'rib chiqilmoqda. Ustoz tasdiqlagach kirishingiz mumkin.",
            )
        if application and application.status == ApplicationStatus.rejected:
            reason = application.reject_reason or "sabab ko'rsatilmagan"
            raise HTTPException(status_code=403, detail=f"Arizangiz rad etilgan: {reason}")

        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri")

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Hisobingiz faolsizlantirilgan. Ustozingizga murojaat qiling.",
        )

    user.last_active = utcnow()
    db.add(NotificationLog(
        user_id=user.id,
        event_type="login",
        payload={"login": user.login},
        is_read=True,  # bu texnik yozuv, bildirishnoma emas
    ))
    await db.commit()

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": _user_public(user),
    }


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return _user_public(current_user)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=72)
    new_password: str = Field(..., min_length=6, max_length=72)


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri")

    current_user.password_hash = hash_password(req.new_password)
    current_user.must_change_password = False
    await db.commit()
    return {"status": "success", "message": "Parol yangilandi"}


# ---------------------------------------------------------------------------
# Arizalar (ustoz tasdiqlaydi)
# ---------------------------------------------------------------------------

def _application_public(app: StudentApplication) -> dict:
    return {
        "id": app.id,
        "login": app.login,
        "full_name": app.full_name,
        "phone_number": app.phone_number,
        "student_group": app.student_group,
        "parent_name": app.parent_name,
        "parent_phone": app.parent_phone,
        "birth_date": app.birth_date,
        "note": app.note,
        "status": app.status.value,
        "reject_reason": app.reject_reason,
        "created_at": iso(app.created_at),
        "reviewed_at": iso(app.reviewed_at),
        "created_user_id": app.created_user_id,
    }


@router.get("/applications")
async def list_applications(
    status_filter: Optional[str] = Query(default="pending", alias="status"),
    limit: int = Query(200, ge=1, le=500),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StudentApplication)
    if status_filter and status_filter != "all":
        try:
            stmt = stmt.where(StudentApplication.status == ApplicationStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Noto'g'ri status qiymati")

    rows = (
        await db.execute(stmt.order_by(StudentApplication.created_at.desc()).limit(limit))
    ).scalars().all()
    return [_application_public(a) for a in rows]


@router.get("/applications/pending-count")
async def pending_applications_count(
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(
            select(func.count(StudentApplication.id)).where(
                StudentApplication.status == ApplicationStatus.pending
            )
        )
    ).scalar() or 0
    return {"count": total}


@router.post("/applications/{application_id}/approve")
async def approve_application(
    application_id: int,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    application = (
        await db.execute(
            select(StudentApplication).where(StudentApplication.id == application_id)
        )
    ).scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Ariza topilmadi")
    if application.status != ApplicationStatus.pending:
        raise HTTPException(status_code=409, detail="Bu ariza allaqachon ko'rib chiqilgan")

    if await _login_taken(db, application.login, exclude_application_id=application.id):
        raise HTTPException(
            status_code=409,
            detail="Bu login band bo'lib qolgan. Talabadan boshqa login so'rang.",
        )

    student = User(
        login=application.login,
        password_hash=application.password_hash,
        full_name=application.full_name,
        username=application.username,
        role=UserRole.student,
        created_by_user_id=staff.id,
        phone_number=application.phone_number,
        student_group=application.student_group,
        parent_name=application.parent_name,
        parent_phone=application.parent_phone,
        birth_date=application.birth_date,
        telegram_user_id=application.telegram_user_id,
        is_active=True,
    )
    db.add(student)
    await db.flush()

    application.status = ApplicationStatus.approved
    application.reviewed_by_user_id = staff.id
    application.reviewed_at = utcnow()
    application.created_user_id = student.id

    await db.commit()
    await db.refresh(student)
    return {"status": "success", "student": _user_public(student)}


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/applications/{application_id}/reject")
async def reject_application(
    application_id: int,
    req: RejectRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    application = (
        await db.execute(
            select(StudentApplication).where(StudentApplication.id == application_id)
        )
    ).scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Ariza topilmadi")
    if application.status != ApplicationStatus.pending:
        raise HTTPException(status_code=409, detail="Bu ariza allaqachon ko'rib chiqilgan")

    application.status = ApplicationStatus.rejected
    application.reject_reason = req.reason
    application.reviewed_by_user_id = staff.id
    application.reviewed_at = utcnow()
    await db.commit()
    return {"status": "success", "message": "Ariza rad etildi"}


# ---------------------------------------------------------------------------
# Talabalar
# ---------------------------------------------------------------------------

@router.get("/students")
async def list_students(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.role == UserRole.student)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))

    students = (
        await db.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    # Sahifadagi barcha talabalar statistikasi bitta so'rovda (N+1 emas).
    student_ids = [s.id for s in students]
    quiz_map: dict[int, tuple[int, int, int]] = {}
    if student_ids:
        quiz_rows = await db.execute(
            select(
                QuizAttempt.student_user_id,
                func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                func.count(QuizAttempt.id),
            )
            .where(
                QuizAttempt.student_user_id.in_(student_ids),
                QuizAttempt.status == QuizAttemptStatus.finished,
            )
            .group_by(QuizAttempt.student_user_id)
        )
        quiz_map = {row[0]: (row[1], row[2], row[3]) for row in quiz_rows.all()}

    output = []
    for student in students:
        correct_answers, total_questions, total_attempts = quiz_map.get(student.id, (0, 0, 0))
        item = _user_public(student)
        item.update(
            attempts_count=total_attempts,
            questions_count=total_questions,
            correct_answers=correct_answers,
        )
        output.append(item)
    return output


@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    students = (
        await db.execute(
            select(User).where(User.role == UserRole.student, User.is_active.is_(True))
        )
    ).scalars().all()

    quiz_rows = await db.execute(
        select(
            QuizAttempt.student_user_id,
            func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
            func.coalesce(func.sum(QuizAttempt.total_questions), 0),
            func.count(QuizAttempt.id),
        )
        .where(QuizAttempt.status == QuizAttemptStatus.finished)
        .group_by(QuizAttempt.student_user_id)
    )
    quiz_map = {row[0]: (row[1], row[2], row[3]) for row in quiz_rows.all()}

    hw_rows = await db.execute(
        select(HomeworkSubmission.student_user_id, func.count(HomeworkSubmission.id))
        .where(HomeworkSubmission.status == "approved")
        .group_by(HomeworkSubmission.student_user_id)
    )
    hw_map = {row[0]: row[1] for row in hw_rows.all()}

    arena_rows = await db.execute(
        select(
            ClinicalArenaAttempt.student_user_id,
            func.coalesce(func.sum(ClinicalArenaAttempt.points_awarded), 0),
        ).group_by(ClinicalArenaAttempt.student_user_id)
    )
    arena_map = {row[0]: row[1] for row in arena_rows.all()}

    leaderboard = []
    for student in students:
        correct_answers, total_questions, attempts_count = quiz_map.get(student.id, (0, 0, 0))
        approved_subs = hw_map.get(student.id, 0)
        arena_points = arena_map.get(student.id, 0)

        points = (correct_answers * 10) + (approved_subs * 25) + arena_points
        accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0.0

        leaderboard.append({
            "id": student.id,
            "full_name": student.full_name,
            "student_group": student.student_group or "Noma'lum guruh",
            "username": student.username,
            "points": points,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "accuracy": round(accuracy, 1),
            "approved_homeworks": approved_subs,
            "attempts_count": attempts_count,
        })

    leaderboard.sort(key=lambda x: (x["points"], x["accuracy"]), reverse=True)
    for idx, item in enumerate(leaderboard):
        item["rank"] = idx + 1

    # O'rinlar butun ro'yxat bo'yicha beriladi, so'ng sahifa kesib olinadi.
    return leaderboard[offset:offset + limit]


@router.get("/analytics")
async def staff_analytics(
    weeks: int = Query(7, ge=2, le=26),
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Xodim paneli uchun haqiqiy ko'rsatkichlar.

    Ilgari panel grafigi qattiq kodlangan soxta massivdan chizilardi va
    "O'rtacha: 4.6 GPA" har doim bir xil turardi.
    """
    async def _count(model, *conditions) -> int:
        stmt = select(func.count(model.id))
        if conditions:
            stmt = stmt.where(*conditions)
        return (await db.execute(stmt)).scalar() or 0

    totals = {
        "students": await _count(User, User.role == UserRole.student, User.is_active.is_(True)),
        "subjects": await _count(Subject),
        "topics": await _count(Topic),
        "schedules": await _count(LessonSchedule),
        "pending_applications": await _count(
            StudentApplication, StudentApplication.status == ApplicationStatus.pending
        ),
        "pending_submissions": await _count(
            HomeworkSubmission, HomeworkSubmission.status == "pending"
        ),
    }

    # Davomat ko'rsatkichlari — aylanma importni oldini olish uchun shu yerda.
    from app.api.attendance import unmarked_lessons_today
    from app.models import AttendanceRecord, AttendanceStatus

    totals["unmarked_lessons_today"] = await unmarked_lessons_today(db)
    totals["pending_excuses"] = await _count(
        AttendanceRecord, AttendanceRecord.excuse_status == ExcuseStatus.pending
    )

    attendance_rows = (
        await db.execute(select(AttendanceRecord.status))
    ).scalars().all()
    attendance_total = len(attendance_rows)
    attendance_ok = sum(
        1
        for status in attendance_rows
        if status in (AttendanceStatus.present, AttendanceStatus.late, AttendanceStatus.excused)
    )
    attendance_overall = (
        round(attendance_ok / attendance_total * 100, 1) if attendance_total else 0.0
    )

    # Haftalik o'rtacha natija (5 ballik shkalada) — oxirgi `weeks` hafta.
    now = utcnow()
    window_start = now - timedelta(weeks=weeks)
    rows = (
        await db.execute(
            select(
                QuizAttempt.started_at,
                QuizAttempt.correct_answers,
                QuizAttempt.total_questions,
            ).where(
                QuizAttempt.status == QuizAttemptStatus.finished,
                QuizAttempt.started_at >= window_start,
            )
        )
    ).all()

    buckets: list[list[int]] = [[0, 0] for _ in range(weeks)]
    for started_at, correct, total in rows:
        started = as_utc(started_at)
        if not started or not total:
            continue
        index = weeks - 1 - int((now - started).days // 7)
        if 0 <= index < weeks:
            buckets[index][0] += correct or 0
            buckets[index][1] += total

    trend = [
        {
            "week": index + 1,
            "average": round(correct / total * 5.0, 2) if total else 0.0,
            "attempts_questions": total,
        }
        for index, (correct, total) in enumerate(buckets)
    ]

    overall_correct = sum(b[0] for b in buckets)
    overall_total = sum(b[1] for b in buckets)
    average_score = round(overall_correct / overall_total * 5.0, 2) if overall_total else 0.0

    # Eng faol talabalar — reyting bilan bir xil formula.
    quiz_rows = await db.execute(
        select(
            QuizAttempt.student_user_id,
            func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
            func.coalesce(func.sum(QuizAttempt.total_questions), 0),
        )
        .where(QuizAttempt.status == QuizAttemptStatus.finished)
        .group_by(QuizAttempt.student_user_id)
    )
    quiz_map = {row[0]: (row[1], row[2]) for row in quiz_rows.all()}

    students = (
        await db.execute(
            select(User).where(User.role == UserRole.student, User.is_active.is_(True))
        )
    ).scalars().all()

    top = []
    for student in students:
        correct, total = quiz_map.get(student.id, (0, 0))
        if not total:
            continue
        top.append({
            "id": student.id,
            "full_name": student.full_name,
            "student_group": student.student_group or "",
            "avatar_path": student.avatar_path,
            "correct_answers": correct,
            "questions_count": total,
            "accuracy": round(correct / total * 100, 1),
        })
    top.sort(key=lambda x: (x["accuracy"], x["correct_answers"]), reverse=True)

    return {
        "totals": totals,
        "average_score": average_score,
        "average_accuracy": (
            round(overall_correct / overall_total * 100, 1) if overall_total else 0.0
        ),
        "attendance_percent": attendance_overall,
        "trend": trend,
        "top_students": top[:5],
    }


class StudentCreateRequest(BaseModel):
    login: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=72)
    full_name: str = Field(..., min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)
    telegram_user_id: Optional[int] = Field(default=None, gt=0)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    student_group: Optional[str] = Field(default=None, max_length=100)
    parent_name: Optional[str] = Field(default=None, max_length=255)
    parent_phone: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.post("/students", status_code=status.HTTP_201_CREATED)
async def create_student(
    req: StudentCreateRequest,
    staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    login_value = _validate_login(req.login)
    if await _login_taken(db, login_value):
        raise HTTPException(status_code=400, detail="Bu login allaqachon band")

    if req.telegram_user_id is not None:
        existing = await db.execute(
            select(User.id).where(User.telegram_user_id == req.telegram_user_id)
        )
        if existing.first():
            raise HTTPException(
                status_code=400, detail="Bu Telegram ID ga ega foydalanuvchi allaqachon mavjud"
            )

    student = User(
        login=login_value,
        password_hash=hash_password(req.password),
        must_change_password=True,
        telegram_user_id=req.telegram_user_id,
        full_name=req.full_name.strip(),
        username=req.username.strip() if req.username else None,
        role=UserRole.student,
        created_by_user_id=staff.id,
        phone_number=req.phone_number,
        student_group=req.student_group,
        parent_name=req.parent_name,
        parent_phone=req.parent_phone,
        birth_date=req.birth_date,
        notes=req.notes,
        is_active=True,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return {"status": "success", "student": _user_public(student)}


class StudentUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    student_group: Optional[str] = Field(default=None, max_length=100)
    parent_name: Optional[str] = Field(default=None, max_length=255)
    parent_phone: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None


async def _get_user_or_404(db: AsyncSession, user_id: int, role: Optional[UserRole] = None) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or (role is not None and user.role != role):
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return user


@router.put("/students/{student_id}")
async def update_student(
    student_id: int,
    req: StudentUpdateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    student = await _get_user_or_404(db, student_id, UserRole.student)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    await db.commit()
    await db.refresh(student)
    return {"status": "success", "student": _user_public(student)}


@router.delete("/students/{student_id}")
async def deactivate_student(
    student_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Talabani o'chirmaydi, faqat faolsizlantiradi — natijalari saqlanib qoladi."""
    student = await _get_user_or_404(db, student_id, UserRole.student)
    student.is_active = False
    await db.commit()
    return {"status": "success", "message": "Talaba faolsizlantirildi"}


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=72)


@router.post("/students/{student_id}/reset-password")
async def reset_student_password(
    student_id: int,
    req: ResetPasswordRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    student = await _get_user_or_404(db, student_id, UserRole.student)
    student.password_hash = hash_password(req.new_password)
    student.must_change_password = True
    await db.commit()
    return {
        "status": "success",
        "message": "Vaqtinchalik parol o'rnatildi. Talaba birinchi kirishda uni o'zgartiradi.",
    }


@router.get("/students/{student_id}/overview")
async def student_overview(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_id)
    student = await _get_user_or_404(db, student_id)

    attempts = (
        await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.student_user_id == student_id,
                QuizAttempt.status == QuizAttemptStatus.finished,
            )
            .order_by(QuizAttempt.started_at.desc())
        )
    ).scalars().all()

    attempt_items = await _serialize_attempts(db, attempts)
    qa_items = await load_ai_questions(db, student_id)

    return {
        "student": _user_public(student),
        "summary": {
            "attempts_count": len(attempts),
            "questions_count": sum(a.total_questions for a in attempts),
            "correct_answers": sum(a.correct_answers for a in attempts),
            "ai_questions_count": len(qa_items),
        },
        "attempts": attempt_items,
        "ai_questions": qa_items,
    }


async def _serialize_attempts(db: AsyncSession, attempts) -> list[dict]:
    """Urinishlarni savollari bilan seriyalash — hammasi 2 ta so'rovda."""
    if not attempts:
        return []

    attempt_ids = [a.id for a in attempts]
    topic_ids = {a.topic_id for a in attempts}

    titles = {
        row[0]: row[1]
        for row in (
            await db.execute(select(Topic.id, Topic.title).where(Topic.id.in_(topic_ids)))
        ).all()
    }

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_attempt_id.in_(attempt_ids))
            .order_by(QuizQuestion.quiz_attempt_id, QuizQuestion.question_order)
        )
    ).scalars().all()

    by_attempt: dict[int, list] = {}
    for q in questions:
        by_attempt.setdefault(q.quiz_attempt_id, []).append(q)

    return [
        {
            "id": attempt.id,
            "topic_id": attempt.topic_id,
            "topic_title": titles.get(attempt.topic_id, "O'chirilgan mavzu"),
            "score": attempt.correct_answers,
            "total": attempt.total_questions,
            "date": iso(attempt.started_at),
            "finished_at": iso(attempt.finished_at),
            "duration_seconds": duration_seconds(attempt),
            "results": [
                {
                    "question": q.question_text,
                    "options": q.options or {},
                    "correct_option": q.expected_answer,
                    "user_answer": q.student_answer,
                    "is_correct": q.is_correct,
                    "explanation": q.feedback_text or "",
                }
                for q in by_attempt.get(attempt.id, [])
            ],
        }
        for attempt in attempts
    ]


@router.get("/students/{student_id}/academic-stats")
async def student_academic_stats(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_id)
    await _get_user_or_404(db, student_id)

    quiz_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(QuizAttempt.correct_answers), 0),
                func.coalesce(func.sum(QuizAttempt.total_questions), 0),
                func.count(QuizAttempt.id),
            ).where(
                QuizAttempt.student_user_id == student_id,
                QuizAttempt.status == QuizAttemptStatus.finished,
            )
        )
    ).one()
    sum_correct, sum_total, total_quizzes = quiz_row
    quiz_avg = round((sum_correct / sum_total * 5.0), 2) if sum_total > 0 else 0.0

    hw_grades_raw = (
        await db.execute(
            select(HomeworkSubmission.grade).where(
                HomeworkSubmission.student_user_id == student_id,
                HomeworkSubmission.status == "approved",
                HomeworkSubmission.grade.isnot(None),
            )
        )
    ).scalars().all()

    hw_grades = []
    for raw in hw_grades_raw:
        try:
            hw_grades.append(float(raw))
        except (TypeError, ValueError):
            continue
    hw_avg = round(sum(hw_grades) / len(hw_grades), 2) if hw_grades else 0.0

    arena_attempts = (
        await db.execute(
            select(ClinicalArenaAttempt).where(
                ClinicalArenaAttempt.student_user_id == student_id,
                ClinicalArenaAttempt.status == "finished",
            )
        )
    ).scalars().all()

    arena_duels_won = sum(1 for a in arena_attempts if a.mode == "duel" and a.is_winner)
    arena_duels_lost = sum(1 for a in arena_attempts if a.mode == "duel" and not a.is_winner)
    arena_cases_solved = sum(1 for a in arena_attempts if a.mode == "case" and a.is_winner)

    combined = 0.0
    metrics = 0
    if sum_total > 0:
        combined += quiz_avg
        metrics += 1
    if hw_grades:
        combined += hw_avg
        metrics += 1

    gpa = combined / metrics if metrics else 0.0
    if gpa >= 4.5:
        standing = "A'lochi / Excellent"
    elif gpa >= 3.8:
        standing = "Yaxshi / Good"
    elif gpa >= 3.0:
        standing = "Qoniqarli / Satisfactory"
    else:
        standing = "Qoniqarsiz / Needs Improvement" if metrics else "Noma'lum / No grades yet"

    # Davomat — aylanma importni oldini olish uchun shu yerda.
    from app.api.attendance import attendance_percent

    att_percent, att_attended, att_total = await attendance_percent(db, student_id)

    return {
        "student_id": student_id,
        "quiz_avg": quiz_avg,
        "homework_avg": hw_avg,
        "arena_duels_won": arena_duels_won,
        "arena_duels_lost": arena_duels_lost,
        "arena_cases_solved": arena_cases_solved,
        "standing": standing,
        "total_quizzes_taken": total_quizzes,
        "total_homeworks_graded": len(hw_grades),
        "attendance_percent": att_percent,
        "attendance_present": att_attended,
        "attendance_total": att_total,
    }


@router.get("/students/{student_id}/gamification")
async def student_gamification(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """XP, daraja, kunlik seriya va bugungi maqsad — mavjud faoliyatdan hisoblanadi."""
    ensure_can_access_user(current_user, student_id)
    student = await _get_user_or_404(db, student_id)

    quiz_rows = (await db.execute(
        select(QuizAttempt.correct_answers, QuizAttempt.started_at)
        .where(
            QuizAttempt.student_user_id == student_id,
            QuizAttempt.status == QuizAttemptStatus.finished,
        )
    )).all()
    hw_rows = (await db.execute(
        select(HomeworkSubmission.status, HomeworkSubmission.submitted_at)
        .where(HomeworkSubmission.student_user_id == student_id)
    )).all()
    arena_rows = (await db.execute(
        select(ClinicalArenaAttempt.points_awarded, ClinicalArenaAttempt.created_at)
        .where(ClinicalArenaAttempt.student_user_id == student_id)
    )).all()

    correct = sum((r[0] or 0) for r in quiz_rows)
    approved = sum(1 for r in hw_rows if r[0] == "approved")
    arena_points = sum((r[0] or 0) for r in arena_rows)
    xp = correct * 10 + approved * 25 + arena_points

    # Daraja egri chizig'i: n-daraja uchun kerakli XP = 50*(n-1)^2
    level = int((xp / 50) ** 0.5) + 1
    floor_current = 50 * (level - 1) ** 2
    floor_next = 50 * level ** 2
    xp_in_level = xp - floor_current
    xp_for_next = floor_next - floor_current
    progress = round(xp_in_level / xp_for_next, 3) if xp_for_next > 0 else 0.0

    active_days = set()
    for rows in (quiz_rows, hw_rows, arena_rows):
        for row in rows:
            day = tashkent_date(row[1])
            if day:
                active_days.add(day)

    today = tashkent_date(utcnow())
    cursor = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    done_today = sum(1 for r in quiz_rows if tashkent_date(r[1]) == today)
    daily_target = student.target_quizzes

    return {
        "student_id": student_id,
        "xp": xp,
        "level": level,
        "xp_in_level": xp_in_level,
        "xp_for_next": xp_for_next,
        "progress": progress,
        "streak": streak,
        "daily_goal": {
            "target": daily_target,
            "done_today": done_today,
            "completed": done_today >= daily_target,
        },
        "target_topics": student.target_topics,
        "target_quizzes": student.target_quizzes,
        "target_ai_questions": student.target_ai_questions,
    }


class StudentTargetsUpdateRequest(BaseModel):
    target_topics: int = Field(..., ge=0, le=100)
    target_quizzes: int = Field(..., ge=0, le=100)
    target_ai_questions: int = Field(..., ge=0, le=100)


@router.post("/students/{student_id}/targets")
async def update_student_targets(
    student_id: int,
    req: StudentTargetsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_access_user(current_user, student_id)
    student = await _get_user_or_404(db, student_id)

    student.target_topics = req.target_topics
    student.target_quizzes = req.target_quizzes
    student.target_ai_questions = req.target_ai_questions
    await db.commit()
    return {
        "status": "success",
        "targets": {
            "target_topics": student.target_topics,
            "target_quizzes": student.target_quizzes,
            "target_ai_questions": student.target_ai_questions,
        },
    }


# ---------------------------------------------------------------------------
# Xodimlar (faqat superadmin)
# ---------------------------------------------------------------------------

class EmployeeCreateRequest(BaseModel):
    login: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=72)
    full_name: str = Field(..., min_length=1, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=255)
    degree: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(default="employee")

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ("employee", "superadmin"):
            raise ValueError("role faqat 'employee' yoki 'superadmin' bo'lishi mumkin")
        return v


class EmployeeUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=255)
    degree: Optional[str] = Field(default=None, max_length=255)
    bio: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None
    new_password: Optional[str] = Field(default=None, min_length=6, max_length=72)


@router.get("/teachers")
async def list_teachers(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Professor-o'qituvchilar ro'yxati.

    Talabalar chat va "Professorlar" ekranida ishlatadi, shu sababli
    `/employees` dan farqli o'laroq superadmin talab qilinmaydi va
    faqat ochiq profil maydonlari qaytariladi.
    """
    rows = (
        await db.execute(
            select(User)
            .where(
                User.role.in_([UserRole.employee, UserRole.superadmin]),
                User.is_active.is_(True),
            )
            .order_by(User.full_name)
        )
    ).scalars().all()

    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "role": u.role.value,
            "department": u.department,
            "degree": u.degree,
            "bio": u.bio,
            "avatar_path": u.avatar_path,
            "phone_number": u.phone_number,
            "last_active": iso(u.last_active),
        }
        for u in rows
    ]


@router.get("/employees")
async def list_employees(
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(User)
            .where(User.role.in_([UserRole.employee, UserRole.superadmin]))
            .order_by(User.created_at.desc())
        )
    ).scalars().all()
    return [_user_public(u) for u in rows]


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def create_employee(
    req: EmployeeCreateRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    login_value = _validate_login(req.login)
    if await _login_taken(db, login_value):
        raise HTTPException(status_code=400, detail="Bu login allaqachon band")

    employee = User(
        login=login_value,
        password_hash=hash_password(req.password),
        must_change_password=True,
        full_name=req.full_name.strip(),
        phone_number=req.phone_number,
        department=req.department,
        degree=req.degree,
        role=UserRole[req.role],
        created_by_user_id=admin.id,
        is_active=True,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return {"status": "success", "employee": _user_public(employee)}


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    req: EmployeeUpdateRequest,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    employee = await _get_user_or_404(db, employee_id)
    if employee.role == UserRole.student:
        raise HTTPException(status_code=404, detail="Xodim topilmadi")

    data = req.model_dump(exclude_unset=True)
    new_password = data.pop("new_password", None)
    for field, value in data.items():
        setattr(employee, field, value)
    if new_password:
        employee.password_hash = hash_password(new_password)
        employee.must_change_password = True

    await db.commit()
    await db.refresh(employee)
    return {"status": "success", "employee": _user_public(employee)}


@router.delete("/employees/{employee_id}")
async def deactivate_employee(
    employee_id: int,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    if employee_id == admin.id:
        raise HTTPException(status_code=400, detail="O'zingizni faolsizlantira olmaysiz")

    employee = await _get_user_or_404(db, employee_id)
    if employee.role == UserRole.student:
        raise HTTPException(status_code=404, detail="Xodim topilmadi")

    employee.is_active = False
    await db.commit()
    return {"status": "success", "message": "Xodim faolsizlantirildi"}


# ---------------------------------------------------------------------------
# Guruhlar
# ---------------------------------------------------------------------------

class StudentGroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class StudentGroupAssignRequest(BaseModel):
    group_name: str = Field(default="", max_length=100)


@router.get("/groups")
@router.get("/groups/")
async def list_groups(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    groups = (await db.execute(select(StudentGroup).order_by(StudentGroup.name))).scalars().all()
    return [
        {"id": g.id, "name": g.name, "created_at": iso(g.created_at)}
        for g in groups
    ]


@router.post("/groups")
@router.post("/groups/")
async def create_group(
    req: StudentGroupCreateRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    name = req.name.strip()
    exists = await db.execute(select(StudentGroup.id).where(StudentGroup.name == name))
    if exists.first():
        raise HTTPException(status_code=400, detail="Bunday guruh allaqachon mavjud.")

    group = StudentGroup(name=name)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return {
        "status": "success",
        "group": {"id": group.id, "name": group.name, "created_at": iso(group.created_at)},
    }


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: int,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    group = (
        await db.execute(select(StudentGroup).where(StudentGroup.id == group_id))
    ).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi")

    # Guruh o'chirilganda talabalardagi yopishib qolgan nomni ham tozalaymiz.
    await db.execute(
        update(User).where(User.student_group == group.name).values(student_group=None)
    )
    await db.delete(group)
    await db.commit()
    return {"status": "success", "message": "Guruh muvaffaqiyatli o'chirildi"}


@router.post("/students/{student_id}/assign-group")
async def assign_group(
    student_id: int,
    req: StudentGroupAssignRequest,
    _staff: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    student = await _get_user_or_404(db, student_id, UserRole.student)

    group_name = (req.group_name or "").strip()
    if group_name:
        exists = await db.execute(
            select(StudentGroup.id).where(StudentGroup.name == group_name)
        )
        if not exists.first():
            raise HTTPException(status_code=404, detail="Bunday guruh mavjud emas")
        student.student_group = group_name
        message = "Talaba guruhga qo'shildi"
    else:
        student.student_group = None
        message = "Talaba guruhdan chiqarildi"

    await db.commit()
    return {"status": "success", "message": message}
