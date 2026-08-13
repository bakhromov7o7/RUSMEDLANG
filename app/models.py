import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, BigInteger, String, Boolean, DateTime, Enum,
    ForeignKey, Text, Integer, JSON, UniqueConstraint, Float, Index
)
from sqlalchemy.orm import relationship

from app.database import Base

# SQLite'da BIGINT primary key avtoinkrement bo'lmaydi (faqat INTEGER PRIMARY KEY
# rowid bilan bog'lanadi). PostgreSQL'da esa BigInteger BIGSERIAL ga aylanadi.
# Variant orqali ikkala bazada ham to'g'ri ishlashini ta'minlaymiz.
PrimaryKey = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """Timezone-aware UTC vaqti.

    Ilgari `datetime.utcnow()` (naive) ishlatilardi, ustunlar esa
    `DateTime(timezone=True)` edi — natijada naive va aware qiymatlar
    aralashib, ayirish amallarida TypeError chiqardi.
    """
    return datetime.now(timezone.utc)

class UserRole(enum.Enum):
    superadmin = "superadmin"
    employee = "employee"
    student = "student"

class MaterialType(enum.Enum):
    video = "video"
    text = "text"
    document = "document"
    transcript = "transcript"

class TopicStatus(enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"

class SessionState(enum.Enum):
    idle = "idle"
    studying = "studying"
    asking = "asking"
    quiz_pending = "quiz_pending"
    quiz_active = "quiz_active"
    quiz_done = "quiz_done"

class ApplicationStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class QuizAttemptStatus(enum.Enum):
    in_progress = "in_progress"
    finished = "finished"

class User(Base):
    __tablename__ = "users"

    id = Column(PrimaryKey, primary_key=True)
    # Bot olib tashlangach Telegram ID majburiy emas — ilovada ro'yxatdan
    # o'tgan talabada u umuman bo'lmasligi mumkin.
    telegram_user_id = Column(BigInteger, unique=True, nullable=True)
    login = Column(String(100), unique=True, nullable=True, index=True)
    password_hash = Column(String(255))
    full_name = Column(String(255), nullable=False)
    username = Column(String(255))
    role = Column(Enum(UserRole, name="user_role"), nullable=False)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    phone_number = Column(String(50))
    student_group = Column(String(100), index=True)
    parent_name = Column(String(255))
    parent_phone = Column(String(50))
    birth_date = Column(String(100))
    notes = Column(Text)
    avatar_path = Column(String(255))
    # Ilova tili: "uz" | "ru"
    preferred_language = Column(String(10), default="uz", nullable=False)
    # Bildirishnoma sozlamalari: {"homework": true, "messages": true, ...}
    notification_prefs = Column(JSON, default=dict, nullable=False)
    # Xodim profili (professorlar ro'yxatida ko'rsatiladi)
    department = Column(String(255))
    degree = Column(String(255))
    bio = Column(Text)
    target_topics = Column(Integer, default=2, nullable=False)
    target_quizzes = Column(Integer, default=5, nullable=False)
    target_ai_questions = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    last_active = Column(DateTime(timezone=True), nullable=True)

    creator = relationship("User", remote_side=[id])
    topics = relationship("Topic", back_populates="employee")
    session = relationship("StudentSession", back_populates="student", uselist=False)

class Subject(Base):
    __tablename__ = "subjects"

    id = Column(PrimaryKey, primary_key=True)
    title = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    topics = relationship("Topic", back_populates="subject", cascade="all, delete-orphan")
    materials = relationship("SubjectMaterial", back_populates="subject", cascade="all, delete-orphan")

class Topic(Base):
    __tablename__ = "topics"

    id = Column(PrimaryKey, primary_key=True)
    employee_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    topic_type = Column(String(50), default="leksika", nullable=False)
    status = Column(Enum(TopicStatus, name="topic_status"), default=TopicStatus.draft, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("User", back_populates="topics")
    subject = relationship("Subject", back_populates="topics")
    materials = relationship("TopicMaterial", back_populates="topic")
    chunks = relationship("KnowledgeChunk", back_populates="topic")

class StudentTopicAccess(Base):
    __tablename__ = "student_topic_access"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False)
    assigned_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('student_user_id', 'topic_id', name='_student_topic_uc'),)

class TopicMaterial(Base):
    __tablename__ = "topic_materials"

    id = Column(PrimaryKey, primary_key=True)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False, index=True)
    uploaded_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    material_type = Column(Enum(MaterialType, name="material_type"), nullable=False)
    title = Column(String(255))
    raw_text = Column(Text)
    processed_text = Column(Text)
    source_url = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    topic = relationship("Topic", back_populates="materials")

class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(PrimaryKey, primary_key=True)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False, index=True)
    material_id = Column(BigInteger, ForeignKey("topic_materials.id"))
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('topic_id', 'material_id', 'chunk_index', name='_topic_material_chunk_uc'),)

    topic = relationship("Topic", back_populates="chunks")

class StudentSession(Base):
    __tablename__ = "student_sessions"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    topic_id = Column(BigInteger, ForeignKey("topics.id"))
    state = Column(Enum(SessionState, name="session_state"), default=SessionState.idle, nullable=False)
    active_quiz_attempt_id = Column(BigInteger)
    question_count = Column(Integer, default=0, nullable=False)
    last_user_message = Column(Text)
    started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    student = relationship("User", back_populates="session")

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False, index=True)
    employee_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    status = Column(
        Enum(QuizAttemptStatus, name="quiz_attempt_status"),
        default=QuizAttemptStatus.in_progress,
        nullable=False,
    )
    language = Column(String(10), default="uz", nullable=False)
    total_questions = Column(Integer, default=5, nullable=False)
    correct_answers = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True))
    report_sent_at = Column(DateTime(timezone=True))

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(PrimaryKey, primary_key=True)
    quiz_attempt_id = Column(BigInteger, ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_order = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    # {"A": "...", "B": "...", ...} — hisobot PDF va tarixda variantlarni
    # ko'rsatish uchun saqlanadi.
    options = Column(JSON, default=dict, nullable=False)
    expected_answer = Column(Text)
    student_answer = Column(Text)
    is_correct = Column(Boolean)
    feedback_text = Column(Text)
    checked_at = Column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint('quiz_attempt_id', 'question_order', name='_quiz_question_uc'),)

class StudentApplication(Base):
    """Talabaning ro'yxatdan o'tish arizasi — ustoz tasdiqlagachgina User yaratiladi."""

    __tablename__ = "student_applications"

    id = Column(PrimaryKey, primary_key=True)
    telegram_user_id = Column(BigInteger, nullable=True)
    login = Column(String(100), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    username = Column(String(255))
    phone_number = Column(String(50))
    student_group = Column(String(100))
    parent_name = Column(String(255))
    parent_phone = Column(String(50))
    birth_date = Column(String(100))
    note = Column(Text)
    status = Column(Enum(ApplicationStatus, name="application_status"), default=ApplicationStatus.pending, nullable=False, index=True)
    reject_reason = Column(Text)
    reviewed_by_user_id = Column(BigInteger, ForeignKey("users.id"))
    created_user_id = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at = Column(DateTime(timezone=True))

class Homework(Base):
    __tablename__ = "homeworks"

    id = Column(PrimaryKey, primary_key=True)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255))
    text = Column(Text)
    link = Column(Text)
    image_path = Column(Text)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    student = relationship("User", foreign_keys=[student_user_id])
    subject = relationship("Subject")

class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"

    id = Column(PrimaryKey, primary_key=True)
    homework_id = Column(BigInteger, ForeignKey("homeworks.id", ondelete="CASCADE"), nullable=False, index=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text)
    image_path = Column(Text)
    status = Column(String(50), default="pending", nullable=False)  # pending, approved, rejected
    grade = Column(String(50))  # score/rating
    teacher_feedback = Column(Text)
    submitted_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    graded_at = Column(DateTime(timezone=True))

    # Bir talaba bitta vazifaga faqat bitta javob beradi (yangilash mumkin).
    # Ilgari constraint yo'q edi va parallel so'rovlarda dublikat yaratilardi.
    __table_args__ = (
        UniqueConstraint('homework_id', 'student_user_id', name='_homework_student_uc'),
    )

    homework = relationship("Homework")
    student = relationship("User", foreign_keys=[student_user_id])

class ClinicalArenaAttempt(Base):
    __tablename__ = "clinical_arena_attempts"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(50), nullable=False)  # case, duel
    status = Column(String(20), default="finished", nullable=False)  # issued, finished
    scenario_or_opponent = Column(String(255), nullable=False)
    # Duelda: berilgan savollar indeksi va raqib — submit'da server shu asosda baholaydi.
    issued_payload = Column(JSON)
    score = Column(Integer, nullable=False, default=0)
    is_winner = Column(Boolean, default=False)
    points_awarded = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True))

    student = relationship("User", foreign_keys=[student_user_id])

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(PrimaryKey, primary_key=True)
    sender_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_text = Column(Text, nullable=False)
    image_path = Column(String, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_chat_messages_pair", "sender_id", "recipient_id", "created_at"),
    )

    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

class GroupChatMessage(Base):
    __tablename__ = "group_chat_messages"

    id = Column(PrimaryKey, primary_key=True)
    group_name = Column(String(100), nullable=False, index=True)
    sender_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_text = Column(Text, nullable=False)
    image_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    sender = relationship("User", foreign_keys=[sender_id])

class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(PrimaryKey, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_notification_logs_user_event", "user_id", "event_type", "created_at"),
    )

class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(PrimaryKey, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    announcement_type = Column(String(50), default="umumiy", nullable=False)
    views = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

class SubjectMaterial(Base):
    __tablename__ = "subject_materials"

    id = Column(PrimaryKey, primary_key=True)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    material_type = Column(String(50), default="pdf", nullable=False)
    title = Column(String(255), nullable=False)
    detail = Column(String(255))
    url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    subject = relationship("Subject", back_populates="materials")

class LessonSchedule(Base):
    __tablename__ = "lesson_schedules"

    id = Column(PrimaryKey, primary_key=True)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    student_group = Column(String(100), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    room = Column(String(50), nullable=False)
    teacher_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_lesson_schedules_group_day", "student_group", "day_of_week"),
    )

    subject = relationship("Subject")

class StudentGrade(Base):
    __tablename__ = "student_grades"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    score = Column(Float, nullable=False)
    grade_label = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('student_user_id', 'subject_id', name='_student_subject_grade_uc'),
    )

    student = relationship("User")
    subject = relationship("Subject")

class StudentGroup(Base):
    __tablename__ = "student_groups"

    id = Column(PrimaryKey, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

class MedicalTerm(Base):
    __tablename__ = "medical_terms"

    id = Column(PrimaryKey, primary_key=True)
    word = Column(String(255), nullable=False, unique=True)
    transcription = Column(String(255))
    gender = Column(String(100))
    translation = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    example_ru = Column(Text)
    example_uz = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class SavedItemType(enum.Enum):
    topic = "topic"
    material = "material"
    term = "term"
    announcement = "announcement"


class SavedItem(Base):
    """Foydalanuvchi saqlab qo'ygan mavzu / material / termin / e'lon."""

    __tablename__ = "saved_items"

    id = Column(PrimaryKey, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(Enum(SavedItemType, name="saved_item_type"), nullable=False)
    item_id = Column(BigInteger, nullable=False)
    # Manba o'chirilsa ham ro'yxat ma'noli qolishi uchun nusxa saqlanadi.
    title = Column(String(255), nullable=False)
    subtitle = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="_saved_item_uc"),
    )


class RequestStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    resolved = "resolved"
    rejected = "rejected"


class StudentRequest(Base):
    """Talabaning ma'muriyatga murojaati (ma'lumotnoma, ruxsat, texnik yordam...)."""

    __tablename__ = "student_requests"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    request_type = Column(String(50), nullable=False)  # ma'lumotnoma, ruxsat, texnik, boshqa
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(Enum(RequestStatus, name="request_status"), default=RequestStatus.pending, nullable=False, index=True)
    response = Column(Text)
    responded_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    student = relationship("User", foreign_keys=[student_user_id])


class FaqEntry(Base):
    """Yordam bo'limidagi savol-javoblar (xodimlar boshqaradi)."""

    __tablename__ = "faq_entries"

    id = Column(PrimaryKey, primary_key=True)
    category = Column(String(100), default="umumiy", nullable=False, index=True)
    question = Column(String(500), nullable=False)
    answer = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class ExamStatus(enum.Enum):
    in_progress = "in_progress"
    finished = "finished"
    expired = "expired"


class ExamAttempt(Base):
    """Imtihon — bir nechta mavzudan yig'ma test, vaqt chegarasi bilan.

    Oddiy testdan (`QuizAttempt`) farqi: savollar bir necha mavzudan olinadi,
    vaqt cheklangan va urinishni yarim yo'lda tashlab, keyin davom ettirish
    mumkin.
    """

    __tablename__ = "exam_attempts"

    id = Column(PrimaryKey, primary_key=True)
    student_user_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="SET NULL"), index=True)
    title = Column(String(255), nullable=False)
    # Savollar olingan mavzular: [12, 15, 20]
    topic_ids = Column(JSON, default=list, nullable=False)
    status = Column(
        Enum(ExamStatus, name="exam_status"),
        default=ExamStatus.in_progress,
        nullable=False,
        index=True,
    )
    language = Column(String(10), default="uz", nullable=False)
    total_questions = Column(Integer, default=0, nullable=False)
    correct_answers = Column(Integer, default=0, nullable=False)
    # Berilgan vaqt (soniya). 0 bo'lsa cheklov yo'q.
    duration_seconds = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    finished_at = Column(DateTime(timezone=True))

    questions = relationship(
        "ExamQuestion",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="ExamQuestion.question_order",
    )


class ExamQuestion(Base):
    """Imtihon savoli. To'g'ri javob faqat shu yerda saqlanadi."""

    __tablename__ = "exam_questions"

    id = Column(PrimaryKey, primary_key=True)
    exam_attempt_id = Column(
        BigInteger, ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Savol qaysi mavzudan olingani — yakunda mavzular kesimida tahlil uchun.
    topic_id = Column(BigInteger, ForeignKey("topics.id", ondelete="SET NULL"), index=True)
    question_order = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    options = Column(JSON, default=dict, nullable=False)
    expected_answer = Column(Text)
    student_answer = Column(Text)
    is_correct = Column(Boolean)
    feedback_text = Column(Text)
    answered_at = Column(DateTime(timezone=True))

    attempt = relationship("ExamAttempt", back_populates="questions")

    __table_args__ = (
        UniqueConstraint("exam_attempt_id", "question_order", name="_exam_question_uc"),
    )
