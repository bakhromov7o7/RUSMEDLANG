"""Test oqimini AI'siz tekshirish (offline).

Ilova ichida (ASGI) ishlaydi, AI javobi stub bilan almashtiriladi. Asosiy
maqsad — baholash server tomonda bo'lishini va soxta natija yuborish
ishlamasligini tasdiqlash.

    cd backend
    DATABASE_URL="sqlite+aiosqlite:///./_quizflow.db" SECRET_KEY=test-secret \
        python3 scripts/test_quiz_flow.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "offline-test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_quizflow.db")

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

FAKE_QUIZ = json.dumps({
    "questions": [
        {
            "question": f"Sinov savoli {i}: to'g'ri variant {chr(65 + i % 4)}?",
            "options": {"A": "Birinchi", "B": "Ikkinchi", "C": "Uchinchi", "D": "To'rtinchi"},
            "correct_option": chr(65 + i % 4),
            "explanation": f"{i}-savol izohi.",
        }
        for i in range(5)
    ]
}, ensure_ascii=False)

_results: list[tuple[bool, str]] = []


def check(condition: bool, label: str, detail: str = "") -> bool:
    _results.append((condition, label))
    mark = "\033[32mOK\033[0m" if condition else "\033[31mXATO\033[0m"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
    return condition


def prepare_schema() -> None:
    """Migratsiyalarni sinxron kontekstda bajaramiz.

    `alembic/env.py` o'zi `asyncio.run` chaqiradi, shuning uchun buni
    asosiy event loop ichidan chaqirib bo'lmaydi.
    """
    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command.upgrade(Config(os.path.join(root, "alembic.ini")), "head")


async def main() -> int:
    import main as app_module
    from app.api import quiz as quiz_api
    from app.core.security import hash_password
    from app.database import AsyncSessionLocal, engine
    from app.models import (
        KnowledgeChunk,
        MaterialType,
        QuizAttempt,
        QuizAttemptStatus,
        Topic,
        TopicMaterial,
        TopicStatus,
        User,
        UserRole,
    )

    # AI javobini stub bilan almashtiramiz.
    async def fake_generate_quiz(context, count=5, language="uz"):
        return FAKE_QUIZ

    quiz_api.ai_service.generate_quiz = fake_generate_quiz

    async with AsyncSessionLocal() as session:
        teacher = (
            await session.execute(select(User).where(User.login == "quizflow.ustoz"))
        ).scalar_one_or_none()
        if not teacher:
            teacher = User(
                login="quizflow.ustoz", password_hash=hash_password("Parol123"),
                full_name="Quiz Ustoz", role=UserRole.employee, is_active=True,
            )
            session.add(teacher)
            await session.flush()

        student = (
            await session.execute(select(User).where(User.login == "quizflow.talaba"))
        ).scalar_one_or_none()
        if not student:
            student = User(
                login="quizflow.talaba", password_hash=hash_password("Parol123"),
                full_name="Quiz Talaba", role=UserRole.student, is_active=True,
            )
            session.add(student)
            await session.flush()

        topic = (
            await session.execute(select(Topic).where(Topic.title == "Quiz sinov mavzusi"))
        ).scalar_one_or_none()
        if not topic:
            topic = Topic(
                employee_user_id=teacher.id, title="Quiz sinov mavzusi",
                topic_type="leksika", status=TopicStatus.active,
            )
            session.add(topic)
            await session.flush()
            material = TopicMaterial(
                topic_id=topic.id, uploaded_by_user_id=teacher.id,
                material_type=MaterialType.text, title="Leksika", raw_text="Sinov matni.",
            )
            session.add(material)
            await session.flush()
            session.add(KnowledgeChunk(
                topic_id=topic.id, material_id=material.id, chunk_index=0,
                chunk_text="Yurak — Сердце. Jigar — Печень. Bu sinov uchun material.",
            ))
        await session.commit()
        topic_id, student_id = topic.id, student.id

    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/auth/login",
                              json={"login": "quizflow.talaba", "password": "Parol123"})
        if not check(r.status_code == 200, "talaba login", f"{r.status_code} {r.text[:200]}"):
            return _summary()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        print("\n1. Test generatsiyasi")
        r = await client.post("/api/quiz/generate", headers=headers,
                              json={"topic_id": topic_id, "language": "uz"})
        if not check(r.status_code == 200, "generate = 200", f"{r.status_code} {r.text[:300]}"):
            return _summary()
        payload = r.json()
        check("attempt_id" in payload, "javobda attempt_id bor")
        check(len(payload["questions"]) == 5, "5 ta savol qaytdi")

        raw = json.dumps(payload)
        check("correct_option" not in raw, "to'g'ri javob klientga YUBORILMAYDI")
        check("explanation" not in raw, "izoh klientga YUBORILMAYDI")

        attempt_id = payload["attempt_id"]
        questions = payload["questions"]

        print("\n2. Soxta natija yuborish ishlamaydi")
        # Hammasiga "A" javob beramiz; kutilgan to'g'ri javoblar A,B,C,D,A -> 2 ta.
        r = await client.post("/api/quiz/submit", headers=headers, json={
            "attempt_id": attempt_id,
            "answers": [{"question_id": q["id"], "selected_option": "A"} for q in questions],
            "elapsed_seconds": 42,
            # Eski klient maydonlari — server e'tibor bermasligi kerak:
            "score": 5, "is_correct": True,
        })
        if not check(r.status_code == 200, "submit = 200", f"{r.status_code} {r.text[:300]}"):
            return _summary()
        body = r.json()
        check(body["score"] == 2, "server o'zi hisobladi (kutilgan 2)", f"score={body['score']}")
        check(body["total"] == 5, "jami savollar 5")
        check(body["elapsed_seconds"] == 42, "vaqt saqlandi")
        check(all("explanation" in item for item in body["results"]),
              "natijada izohlar qaytadi")

        print("\n3. Qayta topshirish bloklanadi")
        r = await client.post("/api/quiz/submit", headers=headers, json={
            "attempt_id": attempt_id,
            "answers": [{"question_id": q["id"], "selected_option": "A"} for q in questions],
        })
        check(r.status_code == 409, "takroriy submit = 409", str(r.status_code))

        print("\n4. Boshqa talabaning urinishiga tegib bo'lmaydi")
        r2 = await client.post("/api/auth/login",
                               json={"login": "quizflow.ustoz", "password": "Parol123"})
        staff_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
        r = await client.post("/api/quiz/submit", headers=staff_headers,
                              json={"attempt_id": attempt_id, "answers": []})
        check(r.status_code in (403, 409), "begona urinishga submit rad etildi", str(r.status_code))

        print("\n5. Natija tarixda va PDF'da ko'rinadi")
        r = await client.get(f"/api/quiz/history/{student_id}", headers=headers)
        check(r.status_code == 200 and any(a["id"] == attempt_id for a in r.json()),
              "urinish tarixda bor")

        r = await client.get("/api/quiz/report/pdf", params={"attempt_id": attempt_id},
                             headers=headers)
        check(r.status_code == 200 and r.content[:4] == b"%PDF", "natija PDF yaratildi",
              f"{r.status_code} {r.text[:150]}")

        print("\n6. Tugallanmagan urinish statistikani buzmaydi")
        r = await client.post("/api/quiz/generate", headers=headers,
                              json={"topic_id": topic_id, "language": "uz"})
        check(r.status_code == 200, "ikkinchi generate = 200")
        r = await client.get(f"/api/quiz/history/{student_id}", headers=headers)
        check(len(r.json()) == 1, "tugallanmagan urinish tarixda ko'rinmaydi",
              f"{len(r.json())} ta")

    async with AsyncSessionLocal() as session:
        pending = (
            await session.execute(
                select(QuizAttempt).where(QuizAttempt.status == QuizAttemptStatus.in_progress)
            )
        ).scalars().all()
        check(len(pending) == 1, "faqat bitta ochiq urinish qoldi", f"{len(pending)} ta")

    await engine.dispose()
    return _summary()


def _summary() -> int:
    passed = sum(1 for ok, _ in _results if ok)
    print(f"\n{'=' * 60}\nNatija: {passed}/{len(_results)} test o'tdi")
    failed = [label for ok, label in _results if not ok]
    for label in failed:
        print(f"  - {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    prepare_schema()
    sys.exit(asyncio.run(main()))
