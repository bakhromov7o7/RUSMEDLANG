"""Profil bo'limlari: til, bildirishnoma sozlamalari, saqlanganlar,
murojaatlar, FAQ va o'qituvchi profili.

Oldingi revizioniyalar kabi himoyalangan — mavjud ustun/jadval qayta
yaratilmaydi.

Revision ID: 0003_profile_features
Revises: 0002_auth_and_grading
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import Base
import app.models  # noqa: F401 — modellarni ro'yxatdan o'tkazadi

revision: str = "0003_profile_features"
down_revision: Union[str, None] = "0002_auth_and_grading"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COLUMNS = [
    ("users", "avatar_path", sa.String(length=255), {"nullable": True}),
    ("users", "preferred_language", sa.String(length=10), {"nullable": True}),
    ("users", "notification_prefs", sa.JSON(), {"nullable": True}),
    ("users", "department", sa.String(length=255), {"nullable": True}),
    ("users", "degree", sa.String(length=255), {"nullable": True}),
    ("users", "bio", sa.Text(), {"nullable": True}),
]

NEW_TABLES = ("saved_items", "student_requests", "faq_entries")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names())

    # 1. Yangi ustunlar
    for table, column, coltype, kwargs in NEW_COLUMNS:
        if table not in tables:
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        op.add_column(table, sa.Column(column, coltype, **kwargs))

    # 2. Standart qiymatlar
    insp = _inspector()
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "preferred_language" in cols:
            op.execute(
                "UPDATE users SET preferred_language = 'uz' "
                "WHERE preferred_language IS NULL"
            )

    # 3. Yangi jadvallar — faqat yo'qlarini yaratamiz
    missing = [
        Base.metadata.tables[name] for name in NEW_TABLES if name not in tables
    ]
    if missing:
        Base.metadata.create_all(bind=op.get_bind(), tables=missing, checkfirst=True)


def downgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names())

    for name in reversed(NEW_TABLES):
        if name in tables:
            op.drop_table(name)

    insp = _inspector()
    for table, column, _type, _kwargs in NEW_COLUMNS:
        if table in tables and column in {c["name"] for c in insp.get_columns(table)}:
            try:
                op.drop_column(table, column)
            except Exception:  # noqa: BLE001
                pass
