"""Parol xeshlash, JWT va autentifikatsiya dependency'lari."""

import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.database import get_db
from app.models import User, UserRole

logger = logging.getLogger(__name__)

# bcrypt parolning faqat dastlabki 72 baytini hisobga oladi va undan uzunida
# xato beradi, shuning uchun kesib qo'yamiz (Pydantic ham 72 bilan cheklaydi).
_BCRYPT_MAX_BYTES = 72

# auto_error=False — token yo'qligida FastAPI 403 emas, biz 401 qaytaramiz.
_bearer = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Avtorizatsiya talab qilinadi yoki token yaroqsiz",
    headers={"WWW-Authenticate": "Bearer"},
)


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_truncate(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + config.ACCESS_TOKEN_EXPIRE).timestamp()),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except JWTError as exc:
        logger.debug("Token dekodlanmadi: %s", exc)
        raise CREDENTIALS_ERROR


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_ERROR

    payload = decode_token(credentials.credentials)
    subject = payload.get("sub")
    if not subject:
        raise CREDENTIALS_ERROR

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise CREDENTIALS_ERROR

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise CREDENTIALS_ERROR
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hisobingiz faolsizlantirilgan. Ustozingizga murojaat qiling.",
        )
    return user


def require_roles(*roles: UserRole):
    """Berilgan rollardan biri bo'lishini talab qiluvchi dependency yaratadi."""
    allowed = set(roles)

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu amal uchun ruxsatingiz yo'q",
            )
        return current_user

    return _dependency


# Eng ko'p ishlatiladigan kombinatsiyalar.
require_staff = require_roles(UserRole.employee, UserRole.superadmin)
require_superadmin = require_roles(UserRole.superadmin)


def is_staff(user: User) -> bool:
    return user.role in (UserRole.employee, UserRole.superadmin)


def resolve_target_user_id(current_user: User, requested_user_id: Optional[int]) -> int:
    """Talaba faqat o'z ma'lumotini ko'ra oladi, xodim istalganini.

    Klient yuborgan `user_id` ga hech qachon ishonmaymiz: talaba uchun u
    e'tiborsiz qoldiriladi va tokendagi id qaytariladi.
    """
    if is_staff(user=current_user):
        return requested_user_id if requested_user_id is not None else current_user.id
    return current_user.id


def ensure_can_access_user(current_user: User, target_user_id: int) -> None:
    """Talaba boshqa foydalanuvchi resursiga tegishga urinsa 403."""
    if not is_staff(current_user) and current_user.id != target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Boshqa foydalanuvchi ma'lumotiga kirish mumkin emas",
        )
