from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core import config

DATABASE_URL = config.DATABASE_URL

if DATABASE_URL.startswith("postgresql://"):
    # Sinxron drayverni async drayverga aylantiramiz.
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

_engine_kwargs = {"echo": False, "pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    # Uzoq turgan ulanish server tomonda uzilib qolsa 500 beradi —
    # pool_recycle bilan ulanishlar muntazam yangilanadi.
    _engine_kwargs.update(pool_recycle=1800, pool_size=10, max_overflow=20)

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    # SQLite tashqi kalitlarni sukut bo'yicha tekshirmaydi — ON DELETE CASCADE
    # ishlamaydi va bog'liq yozuvlar yetim bo'lib qoladi. Lokal ishlab chiqish
    # PostgreSQL bilan bir xil ishlashi uchun yoqib qo'yamiz.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # Xatolik yuz berganda ochiq tranzaksiyani yopib qo'yamiz, aks holda
            # ulanish pool'ga buzuq holatda qaytadi.
            await session.rollback()
            raise
