import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core import config
from app.database import engine

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Sxema Alembic bilan boshqariladi (`alembic upgrade head`).
    # Bu yerda faqat ulanish ishlashini tekshiramiz.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Ma'lumotlar bazasiga ulanish muvaffaqiyatli.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Ma'lumotlar bazasiga ulanib bo'lmadi: %s", exc)

    yield

    await engine.dispose()
    logger.info("Ulanishlar yopildi.")


app = FastAPI(title="Ustoz AI API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=config.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Kutilmagan xatolar.

    Ilgari bu yerda `str(exc)` va exception turi klientga qaytarilardi —
    bu SQL matnlari, fayl yo'llari va ichki tuzilma haqida ma'lumot sizdirardi.
    """
    logger.error("Ishlov berilmagan xato: %s %s", request.method, request.url.path, exc_info=True)
    body = {"detail": "Serverda kutilmagan xatolik yuz berdi. Keyinroq urinib ko'ring."}
    if config.DEBUG:
        body.update(error=str(exc), type=type(exc).__name__, path=request.url.path)
    return JSONResponse(status_code=500, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.info("Validatsiya xatosi: %s %s -> %s", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": "Yuborilgan ma'lumot noto'g'ri", "errors": exc.errors()},
    )


@app.get("/", tags=["Service"])
async def root():
    return {"message": "Ustoz AI API is running", "version": app.version}


@app.get("/health", tags=["Service"])
async def health():
    """Deploy va monitoring uchun — DB bilan birga tekshiriladi."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Health tekshiruvi muvaffaqiyatsiz: %s", exc)
        raise HTTPException(status_code=503, detail="Ma'lumotlar bazasi mavjud emas")
    return {"status": "ok", "database": "ok"}


os.makedirs(config.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")

from app.api import (  # noqa: E402  — routerlar app yaratilgandan keyin ulanadi
    announcements,
    arena,
    auth,
    chat,
    exam,
    homework,
    notifications,
    profile,
    quiz,
    topics,
)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(topics.router, prefix="/api/topics", tags=["Topics"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
app.include_router(exam.router, prefix="/api/exam", tags=["Exam"])
app.include_router(homework.router, prefix="/api/homework", tags=["Homework"])
app.include_router(arena.router, prefix="/api/topics/arena", tags=["Clinical Arena"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(announcements.router, prefix="/api/announcements", tags=["Announcements"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
