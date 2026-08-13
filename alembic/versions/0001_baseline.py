"""Baseline: yetishmayotgan jadvallarni yaratish.

Loyihada ilgari migratsiya tarixi bo'lmagan (jadvallar `create_all` va qo'lbola
`ALTER TABLE` bilan yaratilgan). Shu sababli bu revizioniya himoyalangan:
mavjud jadvallarga tegmaydi, faqat yo'qlarini yaratadi. Shu tufayli uni ham
toza bazada, ham ishlab turgan bazada bemalol ishga tushirish mumkin.

Revision ID: 0001_baseline
Revises:
"""
from typing import Sequence, Union

from alembic import op

from app.database import Base
import app.models  # noqa: F401 — modellarni Base.metadata ga ro'yxatdan o'tkazadi

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst=True — allaqachon mavjud jadvallar chetlab o'tiladi.
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
