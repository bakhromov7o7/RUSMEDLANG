"""Yordam bo'limi uchun boshlang'ich savol-javoblar.

    cd backend
    python3 scripts/seed_faq.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import FaqEntry  # noqa: E402

ENTRIES = [
    (
        "hisob",
        "Parolimni qanday o'zgartiraman?",
        "Profil > Xavfsizlik bo'limiga kiring va \"Parolni o'zgartirish\" "
        "tugmasini bosing. Joriy parolingizni va yangi parolni kiriting.",
        10,
    ),
    (
        "hisob",
        "Parolimni unutdim, nima qilaman?",
        "Ustozingizga yoki dekanatga murojaat qiling — ular sizga vaqtinchalik "
        "parol beradi. Birinchi kirishda uni o'zingiznikiga almashtirasiz.",
        20,
    ),
    (
        "hisob",
        "Ro'yxatdan o'tdim, lekin kira olmayapman.",
        "Arizangiz ustoz tomonidan tasdiqlanishi kerak. Tasdiqlangach login va "
        "parolingiz bilan kira olasiz. Odatda bu 1 ish kuni ichida bajariladi.",
        30,
    ),
    (
        "darslar",
        "Test natijam nega saqlanmadi?",
        "Testni yakunlash uchun \"Tugatish\" tugmasini bosish shart. Internet "
        "uzilgan bo'lsa natija yuborilmaydi — qayta ulanib, testni qaytadan "
        "yeching.",
        10,
    ),
    (
        "darslar",
        "AI yordamchiga kuniga nechta savol bera olaman?",
        "Kuniga 10 ta savol berish mumkin. Hisob har kuni Toshkent vaqti bilan "
        "yarim tunda yangilanadi.",
        20,
    ),
    (
        "darslar",
        "Mavzuni keyinroq o'qish uchun qanday saqlayman?",
        "Mavzu sahifasining yuqori o'ng burchagidagi xatcho'p belgisini bosing. "
        "Saqlangan mavzular Profil > Saqlanganlar bo'limida to'planadi.",
        30,
    ),
    (
        "vazifalar",
        "Uy vazifasini qanday topshiraman?",
        "Vazifalar bo'limidan kerakli vazifani tanlang, javob matnini yozing "
        "yoki rasm biriktiring va yuboring. Ustoz baholagach bildirishnoma "
        "keladi.",
        10,
    ),
    (
        "vazifalar",
        "Topshirgan javobimni o'zgartira olamanmi?",
        "Ha. Ustoz baholamaguncha javobni qayta yuborishingiz mumkin — yangi "
        "javob eskisining o'rnini egallaydi.",
        20,
    ),
    (
        "umumiy",
        "Ilova tilini qanday almashtiraman?",
        "Profil > Til / Language bo'limidan o'zbek yoki rus tilini tanlang. "
        "Tanlov mavzu tarjimasi, testlar va AI javoblarida ishlatiladi.",
        10,
    ),
    (
        "umumiy",
        "Ma'lumotnoma yoki ruxsatnoma qanday olaman?",
        "Profil > Mening so'rovlarim bo'limiga kiring, \"+\" tugmasini bosing "
        "va turini tanlab murojaat yuboring. Javob shu bo'limda ko'rinadi.",
        20,
    ),
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        existing = {
            row[0]
            for row in (await session.execute(select(FaqEntry.question))).all()
        }

        added = 0
        for category, question, answer, order in ENTRIES:
            if question in existing:
                continue
            session.add(FaqEntry(
                category=category,
                question=question,
                answer=answer,
                sort_order=order,
                is_active=True,
            ))
            added += 1

        await session.commit()
        print(
            f"{added} ta yangi savol qo'shildi "
            f"({len(ENTRIES) - added} tasi allaqachon mavjud edi)."
        )


if __name__ == "__main__":
    asyncio.run(main())
