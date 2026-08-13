"""Superadmin yaratish yoki uning parolini yangilash.

Ishlatish:
    cd backend
    SUPERADMIN_LOGIN=admin SUPERADMIN_PASSWORD='kuchli-parol' python3 scripts/create_superadmin.py
yoki
    python3 scripts/create_superadmin.py admin 'kuchli-parol' "Admin Adminov"
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import User, UserRole  # noqa: E402


async def main(login: str, password: str, full_name: str) -> None:
    login = login.strip().lower()
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.login == login))
        ).scalar_one_or_none()

        if user:
            user.password_hash = hash_password(password)
            user.role = UserRole.superadmin
            user.is_active = True
            user.must_change_password = False
            action = "yangilandi"
        else:
            user = User(
                login=login,
                password_hash=hash_password(password),
                full_name=full_name,
                role=UserRole.superadmin,
                is_active=True,
                must_change_password=False,
            )
            session.add(user)
            action = "yaratildi"

        await session.commit()
        await session.refresh(user)
        print(f"Superadmin {action}: login='{user.login}', id={user.id}, ism='{user.full_name}'")


if __name__ == "__main__":
    args = sys.argv[1:]
    login_arg = args[0] if len(args) > 0 else os.getenv("SUPERADMIN_LOGIN", "")
    password_arg = args[1] if len(args) > 1 else os.getenv("SUPERADMIN_PASSWORD", "")
    name_arg = args[2] if len(args) > 2 else os.getenv("SUPERADMIN_NAME", "Superadmin")

    if not login_arg or not password_arg:
        print(
            "Xatolik: login va parol kerak.\n"
            "  SUPERADMIN_LOGIN=admin SUPERADMIN_PASSWORD='...' python3 scripts/create_superadmin.py\n"
            "  yoki: python3 scripts/create_superadmin.py admin '...' 'Admin Adminov'"
        )
        raise SystemExit(1)
    if len(password_arg) < 6:
        print("Xatolik: parol kamida 6 ta belgidan iborat bo'lishi kerak.")
        raise SystemExit(1)

    asyncio.run(main(login_arg, password_arg, name_arg))
