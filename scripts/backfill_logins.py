"""Mavjud foydalanuvchilarga login va vaqtinchalik parol beradi.

Bot olib tashlanganidan keyin kirish login+parol orqali amalga oshiriladi.
Bazadagi eski foydalanuvchilarda bu maydonlar bo'sh — bu skript ularni
to'ldiradi va ro'yxatni chop etadi (ustoz talabalarga tarqatishi uchun).

Ishlatish:
    cd backend
    python3 scripts/backfill_logins.py            # ko'rish (hech narsa yozilmaydi)
    python3 scripts/backfill_logins.py --apply    # saqlash
    python3 scripts/backfill_logins.py --apply --csv parollar.csv
"""

import argparse
import asyncio
import csv
import os
import re
import secrets
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import User  # noqa: E402

_ALPHABET = string.ascii_lowercase + string.digits
_SAFE = re.compile(r"[^a-z0-9._-]+")


def _generate_password(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _candidate_login(user: User) -> str:
    for source in (user.username, user.phone_number, user.full_name):
        if not source:
            continue
        candidate = _SAFE.sub("", str(source).strip().lower().replace(" ", "."))
        if len(candidate) >= 3:
            return candidate[:90]
    return f"user{user.id}"


async def main(apply: bool, csv_path: str) -> None:
    async with AsyncSessionLocal() as session:
        users = (
            await session.execute(select(User).order_by(User.id))
        ).scalars().all()

        taken = {u.login for u in users if u.login}
        rows = []

        for user in users:
            if user.login and user.password_hash:
                continue

            login = user.login or _candidate_login(user)
            base = login
            suffix = 2
            while login in taken:
                login = f"{base}{suffix}"
                suffix += 1
            taken.add(login)

            password = _generate_password()
            rows.append((user.id, user.full_name, user.role.value, login, password))

            if apply:
                user.login = login
                user.password_hash = hash_password(password)
                user.must_change_password = True

        if apply:
            await session.commit()

        if not rows:
            print("Hamma foydalanuvchida login va parol allaqachon bor — o'zgarish kerak emas.")
            return

        header = f"{'ID':>5}  {'Ism':<28} {'Rol':<11} {'Login':<24} Parol"
        print(header)
        print("-" * len(header))
        for user_id, full_name, role, login, password in rows:
            print(f"{user_id:>5}  {full_name[:28]:<28} {role:<11} {login:<24} {password}")

        print(
            f"\n{len(rows)} ta foydalanuvchi "
            + ("YANGILANDI." if apply else "yangilanishi kerak (--apply berilmagan, hech narsa saqlanmadi).")
        )
        print("Har bir foydalanuvchi birinchi kirishda parolni o'zgartirishi so'raladi.")

        if apply and csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", "full_name", "role", "login", "password"])
                writer.writerows(rows)
            print(f"CSV saqlandi: {csv_path} — tarqatgandan keyin faylni o'chiring!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eski foydalanuvchilarga login/parol berish")
    parser.add_argument("--apply", action="store_true", help="O'zgarishlarni bazaga saqlash")
    parser.add_argument("--csv", default="", help="Parollarni CSV faylga yozish")
    parsed = parser.parse_args()
    asyncio.run(main(parsed.apply, parsed.csv))
