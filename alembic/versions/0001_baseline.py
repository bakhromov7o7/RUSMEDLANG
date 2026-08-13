"""Baseline: yetishmayotgan jadval va ustunlarni yaratish.

Loyihada ilgari migratsiya tarixi bo'lmagan (jadvallar `create_all` va qo'lbola
`ALTER TABLE` bilan yaratilgan). Shu sababli bu revizioniya himoyalangan:
mavjud ma'lumotga tegmaydi, faqat yetishmayotganini qo'shadi. Shu tufayli uni
ham toza bazada, ham ishlab turgan bazada bemalol ishga tushirish mumkin.

Diqqat: `create_all` faqat **jadval** darajasida ishlaydi — allaqachon mavjud
jadvalga yangi ustun qo'shmaydi. Eski bazada (masalan `db/schema.sql` dan
yaratilgan) `users` jadvali bor, lekin unda `student_group` kabi keyinroq
qo'shilgan ustunlar yo'q edi. Natijada keyingi revizioniya indeks yaratishda
yiqilardi. Shuning uchun jadvallardan keyin ustunlar ham solishtiriladi.

Revision ID: 0001_baseline
Revises:
"""
import enum
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.database import Base
import app.models  # noqa: F401  — modellarni Base.metadata ga ro'yxatdan o'tkazadi

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _default_literal(column) -> Union[str, None]:
    """Modeldagi standart qiymatni SQL literaliga aylantiradi.

    Qiymat bo'lmasa yoki u funksiya bo'lsa (masalan `utcnow`) — `None`.
    """
    default = getattr(column.default, "arg", None)
    if default is None or callable(default):
        return None

    # Enum a'zosi uchun uning qiymati kerak: `QuizAttemptStatus.finished`
    # emas, `finished`.
    if isinstance(default, enum.Enum):
        default = default.value

    if isinstance(default, bool):
        return "TRUE" if default else "FALSE"
    if isinstance(default, (int, float)):
        return str(default)
    if isinstance(default, dict):
        return "'{}'"
    if isinstance(default, list):
        return "'[]'"
    escaped = str(default).replace("'", "''")
    return f"'{escaped}'"


def _sync_columns(bind) -> None:
    """Mavjud jadvallarni model bilan moslaydi.

    Ikki ish qilinadi:

    1. Yetishmayotgan ustunlar qo'shiladi. Ular har doim NULL ruxsat bilan
       qo'shiladi — eski satrlarda qiymat yo'q. Modelda standart qiymat
       bo'lsa, mavjud satrlar shu qiymat bilan to'ldiriladi.
    2. Modelda ixtiyoriy, lekin bazada NOT NULL bo'lgan ustunlardan cheklov
       olib tashlanadi. Masalan `student_applications.telegram_user_id`:
       bot davrida majburiy edi, endi ilovadan ro'yxatdan o'tgan talabada
       umuman bo'lmaydi. Cheklovni yumshatish hech qachon ma'lumot
       yo'qotmaydi.
    """
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # yangi jadval — create_all uni to'liq yaratgan

        db_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        present = set(db_columns)

        # SQLite ALTER COLUMN ni qo'llab-quvvatlamaydi; u yerda bazalar
        # baribir modeldan yaratilgani uchun mos keladi.
        if dialect != "sqlite":
            for column in table.columns:
                info = db_columns.get(column.name)
                if info is None or not column.nullable:
                    continue
                if info.get("nullable", True):
                    continue
                op.alter_column(table.name, column.name, nullable=True)
                logger.info(
                    "NOT NULL cheklovi olib tashlandi: %s.%s",
                    table.name, column.name,
                )

        for column in table.columns:
            if column.name in present:
                continue

            column_type = column.type
            # Enum ustun uchun avval tipni yaratamiz (checkfirst — mavjud
            # bo'lsa o'tkazib yuboradi), so'ng ustun qo'shishda uni qayta
            # yaratishga urinmaymiz. Aks holda PostgreSQL'da "type already
            # exists" xatosi chiqishi mumkin.
            if isinstance(column_type, sa.Enum):
                column_type.create(bind, checkfirst=True)
                if bind.dialect.name == "postgresql":
                    column_type = postgresql.ENUM(
                        *column_type.enums,
                        name=column_type.name,
                        create_type=False,
                    )

            # Yangi ustun har doim NULL ruxsat bilan qo'shiladi — eski
            # satrlarda qiymat yo'q.
            op.add_column(
                table.name,
                sa.Column(column.name, column_type, nullable=True),
            )
            logger.info("Ustun qo'shildi: %s.%s", table.name, column.name)

            value = _default_literal(column)
            if value is not None:
                op.execute(
                    f"UPDATE {table.name} SET {column.name} = {value} "
                    f"WHERE {column.name} IS NULL"
                )


def upgrade() -> None:
    bind = op.get_bind()
    # 1. Yetishmayotgan jadvallar (checkfirst — mavjudlari chetlab o'tiladi).
    Base.metadata.create_all(bind=bind, checkfirst=True)
    # 2. Mavjud jadvallarni model bilan moslash (ustunlar va NULL cheklovi).
    _sync_columns(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
