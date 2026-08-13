"""Markazlashtirilgan konfiguratsiya. Barcha env o'qish shu yerdan boradi."""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DEBUG = _bool("DEBUG", False)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

# --- Xavfsizlik ---------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = timedelta(minutes=_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7))

# Ishlab chiqarishda SECRET_KEY majburiy. DEBUG rejimida ishlab chiquvchini
# bloklamaslik uchun beqaror (har ishga tushishda o'zgaradigan) kalit beriladi.
if not SECRET_KEY:
    if DEBUG:
        import secrets

        SECRET_KEY = secrets.token_urlsafe(48)
    else:
        raise RuntimeError(
            "SECRET_KEY o'rnatilmagan. .env fayliga kuchli tasodifiy qiymat qo'shing: "
            "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )

# --- CORS ---------------------------------------------------------------
# Vergul bilan ajratilgan ro'yxat. Mobil ilova uchun origin yo'q, lekin
# Flutter web / admin panel uchun kerak bo'ladi.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = CORS_ORIGINS != ["*"]

# --- Fayl yuklash -------------------------------------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)  # 10 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf"}
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_DOCUMENT_MIME = {"application/pdf"}

# --- AI -----------------------------------------------------------------
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.groq.com/openai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b")
AI_TIMEOUT_SECONDS = _int("AI_TIMEOUT_SECONDS", 60)

# --- Biznes qoidalari ---------------------------------------------------
QUIZ_QUESTION_COUNT = _int("QUIZ_QUESTION_COUNT", 5)
AI_QUESTION_DAILY_LIMIT = _int("AI_QUESTION_DAILY_LIMIT", 10)
TOPIC_CONTEXT_CHUNK_LIMIT = _int("TOPIC_CONTEXT_CHUNK_LIMIT", 10)
CHAT_PAGE_SIZE = _int("CHAT_PAGE_SIZE", 100)

# O'zbekiston vaqti (UTC+5) — kunlik limit va streak hisobida ishlatiladi.
TASHKENT_OFFSET = timedelta(hours=5)
