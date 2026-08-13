"""Auth (login/parol), server tomonda baholash, indeks va constraintlar.

Bu revizioniya ham himoyalangan: har bir ustun/indeks qo'shishdan oldin
mavjudligi tekshiriladi. Toza bazada 0001 hammasini yangi ko'rinishda
yaratgan bo'ladi va bu yerdagi amallar tashlab ketiladi; ishlab turgan
bazada esa faqat yetishmayotgani qo'shiladi.

Revision ID: 0002_auth_and_grading
Revises: 0001_baseline
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_auth_and_grading"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (jadval, ustun, tur, qo'shimcha kwargs)
NEW_COLUMNS = [
    ("users", "login", sa.String(length=100), {"nullable": True}),
    ("users", "password_hash", sa.String(length=255), {"nullable": True}),
    ("users", "must_change_password", sa.Boolean(), {"nullable": True}),
    ("users", "last_active", sa.DateTime(timezone=True), {"nullable": True}),
    ("quiz_attempts", "language", sa.String(length=10), {"nullable": True}),
    ("quiz_questions", "options", sa.JSON(), {"nullable": True}),
    ("notification_logs", "is_read", sa.Boolean(), {"nullable": True}),
    ("clinical_arena_attempts", "status", sa.String(length=20), {"nullable": True}),
    ("clinical_arena_attempts", "issued_payload", sa.JSON(), {"nullable": True}),
    ("clinical_arena_attempts", "finished_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("student_applications", "login", sa.String(length=100), {"nullable": True}),
    ("student_applications", "password_hash", sa.String(length=255), {"nullable": True}),
    ("student_applications", "phone_number", sa.String(length=50), {"nullable": True}),
    ("student_applications", "student_group", sa.String(length=100), {"nullable": True}),
    ("student_applications", "parent_name", sa.String(length=255), {"nullable": True}),
    ("student_applications", "parent_phone", sa.String(length=50), {"nullable": True}),
    ("student_applications", "birth_date", sa.String(length=100), {"nullable": True}),
    ("student_applications", "note", sa.Text(), {"nullable": True}),
    ("student_applications", "reject_reason", sa.Text(), {"nullable": True}),
    ("student_applications", "created_user_id", sa.BigInteger(), {"nullable": True}),
]

NEW_INDEXES = [
    ("ix_users_login", "users", ["login"], True),
    ("ix_users_student_group", "users", ["student_group"], False),
    ("ix_topics_subject_id", "topics", ["subject_id"], False),
    ("ix_topics_employee_user_id", "topics", ["employee_user_id"], False),
    ("ix_topic_materials_topic_id", "topic_materials", ["topic_id"], False),
    ("ix_knowledge_chunks_topic_id", "knowledge_chunks", ["topic_id"], False),
    ("ix_quiz_attempts_student_user_id", "quiz_attempts", ["student_user_id"], False),
    ("ix_quiz_attempts_topic_id", "quiz_attempts", ["topic_id"], False),
    ("ix_quiz_questions_quiz_attempt_id", "quiz_questions", ["quiz_attempt_id"], False),
    ("ix_homeworks_subject_id", "homeworks", ["subject_id"], False),
    ("ix_homeworks_student_user_id", "homeworks", ["student_user_id"], False),
    ("ix_homework_submissions_homework_id", "homework_submissions", ["homework_id"], False),
    ("ix_homework_submissions_student_user_id", "homework_submissions", ["student_user_id"], False),
    ("ix_student_grades_student_user_id", "student_grades", ["student_user_id"], False),
    ("ix_subject_materials_subject_id", "subject_materials", ["subject_id"], False),
    ("ix_clinical_arena_attempts_student_user_id", "clinical_arena_attempts", ["student_user_id"], False),
    ("ix_student_applications_status", "student_applications", ["status"], False),
    ("ix_student_applications_login", "student_applications", ["login"], False),
    ("ix_medical_terms_category", "medical_terms", ["category"], False),
    ("ix_chat_messages_pair", "chat_messages", ["sender_id", "recipient_id", "created_at"], False),
    ("ix_notification_logs_user_event", "notification_logs", ["user_id", "event_type", "created_at"], False),
    ("ix_lesson_schedules_group_day", "lesson_schedules", ["student_group", "day_of_week"], False),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _tables(insp) -> set:
    return set(insp.get_table_names())


def _columns(insp, table: str) -> set:
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(insp, table: str) -> set:
    names = {i["name"] for i in insp.get_indexes(table)}
    names |= {u["name"] for u in insp.get_unique_constraints(table)}
    return {n for n in names if n}


def _unique_column_sets(insp, table: str) -> set:
    """Mavjud unique constraint/indekslarning ustun to'plamlari.

    SQLite'da CREATE TABLE ichida e'lon qilingan constraint nomsiz qaytadi,
    shuning uchun nom bo'yicha emas, ustunlar bo'yicha solishtiramiz.
    """
    result = set()
    for unique in insp.get_unique_constraints(table):
        result.add(frozenset(unique.get("column_names") or []))
    for index in insp.get_indexes(table):
        if index.get("unique"):
            result.add(frozenset(index.get("column_names") or []))
    return result


def upgrade() -> None:
    insp = _inspector()
    tables = _tables(insp)
    dialect = op.get_bind().dialect.name

    # 1. Yangi ustunlar -----------------------------------------------------
    for table, column, coltype, kwargs in NEW_COLUMNS:
        if table not in tables:
            continue
        if column in _columns(insp, table):
            continue
        op.add_column(table, sa.Column(column, coltype, **kwargs))

    insp = _inspector()

    # 2. Standart qiymatlarni to'ldirib, NOT NULL qilamiz --------------------
    if "users" in tables and "must_change_password" in _columns(insp, "users"):
        op.execute("UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL")
    if "notification_logs" in tables and "is_read" in _columns(insp, "notification_logs"):
        op.execute("UPDATE notification_logs SET is_read = FALSE WHERE is_read IS NULL")
    if "quiz_attempts" in tables and "language" in _columns(insp, "quiz_attempts"):
        op.execute("UPDATE quiz_attempts SET language = 'uz' WHERE language IS NULL")
    if "clinical_arena_attempts" in tables and "status" in _columns(insp, "clinical_arena_attempts"):
        op.execute("UPDATE clinical_arena_attempts SET status = 'finished' WHERE status IS NULL")

    # 3. quiz_attempts.status (enum) ---------------------------------------
    if "quiz_attempts" in tables:
        if "status" not in _columns(insp, "quiz_attempts"):
            if dialect == "postgresql":
                op.execute(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'quiz_attempt_status') THEN "
                    "CREATE TYPE quiz_attempt_status AS ENUM ('in_progress', 'finished'); "
                    "END IF; END $$;"
                )
                op.execute(
                    "ALTER TABLE quiz_attempts ADD COLUMN status quiz_attempt_status "
                    "NOT NULL DEFAULT 'finished'"
                )
            else:
                op.add_column(
                    "quiz_attempts",
                    sa.Column("status", sa.String(length=20), nullable=True),
                )
                op.execute("UPDATE quiz_attempts SET status = 'finished'")

        # Tugallangan sanasi bor urinish — yakunlangan. Bu tekshiruv ustun
        # shu revizioniyada qo'shilganidan qat'i nazar bajariladi: eski
        # bazada ustun 0001 tomonidan standart qiymat ('in_progress') bilan
        # qo'shilgan bo'lishi mumkin va u holda tarix statistikadan
        # yo'qolib ketardi.
        op.execute(
            "UPDATE quiz_attempts SET status = 'finished' "
            "WHERE finished_at IS NOT NULL AND status <> 'finished'"
        )

    # 4. telegram_user_id endi majburiy emas --------------------------------
    if "users" in tables and dialect != "sqlite":
        op.alter_column("users", "telegram_user_id", existing_type=sa.BigInteger(), nullable=True)

    # 5. Bot bilan bog'liq keraksiz tuzilmalar ------------------------------
    if "user_states" in tables:
        op.drop_table("user_states")
    if "topic_materials" in tables and dialect != "sqlite":
        for legacy in ("telegram_file_id", "telegram_file_unique_id", "source_chat_id", "source_message_id"):
            if legacy in _columns(insp, "topic_materials"):
                op.drop_column("topic_materials", legacy)

    # 6. Dublikatlarni tozalab, unique constraintlar qo'shamiz --------------
    if "homework_submissions" in tables:
        op.execute(
            "DELETE FROM homework_submissions WHERE id NOT IN ("
            "SELECT MAX(id) FROM homework_submissions GROUP BY homework_id, student_user_id)"
        )
    if "student_grades" in tables:
        op.execute(
            "DELETE FROM student_grades WHERE id NOT IN ("
            "SELECT MAX(id) FROM student_grades GROUP BY student_user_id, subject_id)"
        )
    if "medical_terms" in tables:
        op.execute(
            "DELETE FROM medical_terms WHERE id NOT IN ("
            "SELECT MIN(id) FROM medical_terms GROUP BY word)"
        )

    insp = _inspector()
    for name, table, columns in [
        ("_homework_student_uc", "homework_submissions", ["homework_id", "student_user_id"]),
        ("_student_subject_grade_uc", "student_grades", ["student_user_id", "subject_id"]),
        ("uq_medical_terms_word", "medical_terms", ["word"]),
    ]:
        if table not in tables:
            continue
        if name in _indexes(insp, table) or frozenset(columns) in _unique_column_sets(insp, table):
            continue
        if dialect == "sqlite":
            # SQLite ALTER bilan constraint qo'shishni qo'llab-quvvatlamaydi;
            # bu yerga faqat eski sqlite bazasida tushiladi — unique indeks yetarli.
            op.create_index(name, table, columns, unique=True)
        else:
            op.create_unique_constraint(name, table, columns)

    # 7. Indekslar ----------------------------------------------------------
    #
    # Diqqat: bu yerda `try/except` ga tayanib bo'lmaydi. PostgreSQL'da
    # muvaffaqiyatsiz buyruq butun tranzaksiyani bekor qiladi va Python
    # tomonda xatoni ushlab qolish yordam bermaydi — keyingi har bir so'rov
    # "current transaction is aborted" bilan yiqiladi. Shuning uchun indeks
    # yaratishdan oldin ustunlar mavjudligini tekshiramiz.
    insp = _inspector()
    for name, table, columns, unique in NEW_INDEXES:
        if table not in tables:
            continue
        if name in _indexes(insp, table):
            continue
        available = _columns(insp, table)
        missing = [c for c in columns if c not in available]
        if missing:
            continue
        op.create_index(name, table, columns, unique=unique)


def downgrade() -> None:
    insp = _inspector()
    tables = _tables(insp)

    for name, table, _columns_, _unique in NEW_INDEXES:
        if table in tables and name in _indexes(insp, table):
            try:
                op.drop_index(name, table_name=table)
            except Exception:  # noqa: BLE001
                pass

    for table, column, _type, _kwargs in NEW_COLUMNS:
        if table in tables and column in _columns(insp, table):
            try:
                op.drop_column(table, column)
            except Exception:  # noqa: BLE001
                pass
