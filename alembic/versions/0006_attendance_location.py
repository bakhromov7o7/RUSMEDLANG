"""Davomatda joylashuv tekshiruvi va dars vaqtidagi buzilishlar.

Dars jadvaliga koordinata va radius, davomat yozuviga ustozning yo'qlama
paytidagi joylashuvi, hamda talabaning "Men keldim" belgisi uchun yangi
jadval qo'shiladi.

Oldingi revizioniyalar kabi himoyalangan — mavjud ustun/jadval qayta
yaratilmaydi.

Revision ID: 0006_attendance_location
Revises: 0005_attendance
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import Base
import app.models  # noqa: F401  — modellarni ro'yxatdan o'tkazadi

revision: str = "0006_attendance_location"
down_revision: Union[str, None] = "0005_attendance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = [
    ("lesson_schedules", "latitude", sa.Float(), {"nullable": True}),
    ("lesson_schedules", "longitude", sa.Float(), {"nullable": True}),
    ("lesson_schedules", "radius_meters", sa.Integer(), {"nullable": True}),
    ("attendance_records", "marked_latitude", sa.Float(), {"nullable": True}),
    ("attendance_records", "marked_longitude", sa.Float(), {"nullable": True}),
    ("attendance_records", "marked_distance_meters", sa.Float(), {"nullable": True}),
]

NEW_TABLES = ("attendance_check_ins", "location_violations")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names())

    for table, column, coltype, kwargs in NEW_COLUMNS:
        if table not in tables:
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        op.add_column(table, sa.Column(column, coltype, **kwargs))

    tables = set(_inspector().get_table_names())
    missing = [Base.metadata.tables[name] for name in NEW_TABLES if name not in tables]
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
