import enum
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, String, Boolean, DateTime, Enum, 
    ForeignKey, Text, Integer, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base

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

class User(Base):
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    username = Column(String(255))
    role = Column(Enum(UserRole, name="user_role"), nullable=False)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True, nullable=False)
    phone_number = Column(String(50))
    student_group = Column(String(100))
    parent_name = Column(String(255))
    parent_phone = Column(String(50))
    birth_date = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    creator = relationship("User", remote_side=[id])
    topics = relationship("Topic", back_populates="employee")
    state = relationship("UserState", back_populates="user", uselist=False)
    session = relationship("StudentSession", back_populates="student", uselist=False)

class Subject(Base):
    __tablename__ = "subjects"
    
    id = Column(BigInteger, primary_key=True)
    title = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    topics = relationship("Topic", back_populates="subject", cascade="all, delete-orphan")

class Topic(Base):
    __tablename__ = "topics"
    
    id = Column(BigInteger, primary_key=True)
    employee_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    subject_id = Column(BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    topic_type = Column(String(50), default="leksika", nullable=False)
    status = Column(Enum(TopicStatus, name="topic_status"), default=TopicStatus.draft, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    employee = relationship("User", back_populates="topics")
    subject = relationship("Subject", back_populates="topics")
    materials = relationship("TopicMaterial", back_populates="topic")
    chunks = relationship("KnowledgeChunk", back_populates="topic")

class StudentTopicAccess(Base):
    __tablename__ = "student_topic_access"
    
    id = Column(BigInteger, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False)
    assigned_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('student_user_id', 'topic_id', name='_student_topic_uc'),)

class UserState(Base):
    __tablename__ = "user_states"
    
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pending_action = Column(String(100))
    pending_topic_id = Column(BigInteger, ForeignKey("topics.id"))
    pending_title = Column(String(255))
    pending_payload = Column(JSON, default={}, nullable=False)
    active_topic_id = Column(BigInteger, ForeignKey("topics.id"))
    preferred_language = Column(String(10), default="uz", nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="state")

class TopicMaterial(Base):
    __tablename__ = "topic_materials"
    
    id = Column(BigInteger, primary_key=True)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False)
    uploaded_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    material_type = Column(Enum(MaterialType, name="material_type"), nullable=False)
    title = Column(String(255))
    raw_text = Column(Text)
    processed_text = Column(Text)
    telegram_file_id = Column(Text)
    telegram_file_unique_id = Column(Text)
    source_url = Column(Text)
    source_chat_id = Column(BigInteger)
    source_message_id = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    topic = relationship("Topic", back_populates="materials")

class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    
    id = Column(BigInteger, primary_key=True)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False)
    material_id = Column(BigInteger, ForeignKey("topic_materials.id"))
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('topic_id', 'material_id', 'chunk_index', name='_topic_material_chunk_uc'),)
    
    topic = relationship("Topic", back_populates="chunks")

class StudentSession(Base):
    __tablename__ = "student_sessions"
    
    id = Column(BigInteger, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    topic_id = Column(BigInteger, ForeignKey("topics.id"))
    state = Column(Enum(SessionState, name="session_state"), default=SessionState.idle, nullable=False)
    active_quiz_attempt_id = Column(BigInteger)
    question_count = Column(Integer, default=0, nullable=False)
    last_user_message = Column(Text)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student = relationship("User", back_populates="session")

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    
    id = Column(BigInteger, primary_key=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    topic_id = Column(BigInteger, ForeignKey("topics.id"), nullable=False)
    employee_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    total_questions = Column(Integer, default=5, nullable=False)
    correct_answers = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True))
    report_sent_at = Column(DateTime(timezone=True))

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    
    id = Column(BigInteger, primary_key=True)
    quiz_attempt_id = Column(BigInteger, ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False)
    question_order = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    expected_answer = Column(Text)
    student_answer = Column(Text)
    is_correct = Column(Boolean)
    feedback_text = Column(Text)
    checked_at = Column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint('quiz_attempt_id', 'question_order', name='_quiz_question_uc'),)

class StudentApplication(Base):
    __tablename__ = "student_applications"
    
    id = Column(BigInteger, primary_key=True)
    telegram_user_id = Column(BigInteger, nullable=False)
    full_name = Column(String(255), nullable=False)
    username = Column(String(255))
    status = Column(Enum(ApplicationStatus, name="application_status"), default=ApplicationStatus.pending, nullable=False)
    reviewed_by_user_id = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime(timezone=True))

class Homework(Base):
    __tablename__ = "homeworks"
    
    id = Column(BigInteger, primary_key=True)
    title = Column(String(255))
    text = Column(Text)
    link = Column(Text)
    image_path = Column(Text)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    student = relationship("User", foreign_keys=[student_user_id])
