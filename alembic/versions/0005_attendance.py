"""Davomat: har bir dars uchun yo'qlama va sabab so'rovlari.

Oldingi revizioniyalar kabi himoyalangan — mavjud jadval qayta yaratilmaydi.

Revision ID: 0005_attendance
Revises: 0004_exam_mode
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import Base
import app.models  # noqa: F401  — modellarni ro'yxatdan o'tkazadi

revision: str = "0005_attendance"
down_revision: Union[str, None] = "0004_exam_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = ("attendance_records",)


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    tables = set(_inspector().get_table_names())
    missing = [Base.metadata.tables[name] for name in NEW_TABLES if name not in tables]
    if missing:
        Base.metadata.create_all(bind=op.get_bind(), tables=missing, checkfirst=True)


def downgrade() -> None:
    tables = set(_inspector().get_table_names())
    for name in reversed(NEW_TABLES):
        if name in tables:
            op.drop_table(name)
