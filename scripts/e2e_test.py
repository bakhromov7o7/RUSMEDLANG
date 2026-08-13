"""To'liq uchidan-uchiga tekshiruv: xodim va talabaning BARCHA oqimlari.

`smoke_test.py` auth va ruxsatlarni tekshiradi; bu skript esa ilovadagi har bir
ekran chaqiradigan endpointni haqiqiy ma'lumot bilan bosib chiqadi:
fan/mavzu/material/jadval/lug'at/e'lon/vazifa/guruh CRUD, baholash, chat,
bildirishnomalar, arena, profil va hisobotlar.

    cd backend
    uvicorn main:app --port 8000 &
    python3 scripts/e2e_test.py --base-url http://127.0.0.1:8000 \
        --admin-login admin --admin-password 'Parol123!'

AI kaliti bo'lmasa AI'ga bog'liq testlar o'tkazib yuboriladi (xatolik emas).
"""

import argparse
import base64
from datetime import date, timedelta
import sys
import time
import uuid

import httpx

PASS = "\033[32mOK\033[0m"
FAIL = "\033[31mXATO\033[0m"
SKIP = "\033[33mO'TKAZILDI\033[0m"

_results: list[tuple[bool, str]] = []
_skipped: list[str] = []

# AI test generatsiyasi mazmunli matn talab qiladi — takrorlanuvchi to'ldiruvchi
# matndan model yaroqli savol tuza olmaydi va tekshiruv bejiz qizil bo'lardi.
TOPIC_CONTENT = (
    "Yurak — qon aylanish tizimining markaziy a'zosi bo'lib, ko'krak qafasida, "
    "o'pkalar orasida joylashgan. U to'rt kamerali: o'ng va chap bo'lmachalar "
    "hamda o'ng va chap qorinchalar.\n\n"
    "O'ng bo'lmachaga yuqori va pastki kavak venalar orqali venoz qon keladi. "
    "Chap qorincha aortaga arterial qon haydaydi va uning devori eng qalin.\n\n"
    "Yurak devori uch qavatdan iborat: endokard, miokard va epikard. Yurak "
    "qisqarishi sistola, bo'shashishi esa diastola deb ataladi.\n\n"
    "Yurakni qon bilan ta'minlovchi tomirlar koronar arteriyalar deyiladi. "
    "Ularning torayishi ishemik kasallikka olib keladi."
)

# Eng kichik yaroqli PNG (1x1 piksel) — rasm yuklashni tekshirish uchun.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def check(condition: bool, label: str, detail: str = "") -> bool:
    _results.append((bool(condition), label))
    mark = PASS if condition else FAIL
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
    return bool(condition)


def skip(label: str, reason: str) -> None:
    _skipped.append(label)
    print(f"  [{SKIP}] {label} — {reason}")


def _body(r: httpx.Response, limit: int = 200) -> str:
    return f"{r.status_code} {r.text[:limit]}"


def run(base_url: str, admin_login: str, admin_password: str) -> int:  # noqa: C901
    client = httpx.Client(base_url=base_url, timeout=60.0)
    suffix = uuid.uuid4().hex[:8]

    # ---------------------------------------------------------------- admin
    print("\n1. Xodim kirishi")
    r = client.post("/api/auth/login", json={"login": admin_login, "password": admin_password})
    if not check(r.status_code == 200, "admin login = 200", _body(r)):
        print("\nAdmin kira olmadi — qolgan testlar bajarilmadi.")
        return 1
    A = {"Authorization": f"Bearer {r.json()['access_token']}"}
    admin_id = r.json()["user"]["id"]

    # ------------------------------------------------------------- talabalar
    print("\n2. Xodim to'g'ridan-to'g'ri talaba yaratadi")
    stud_login = f"e2e.talaba.{suffix}"
    stud_pass = "Talaba12345"
    r = client.post("/api/auth/students", headers=A, json={
        "login": stud_login, "password": stud_pass, "full_name": "E2E Talaba",
        "phone_number": "+998901112233", "student_group": f"G-{suffix[:4]}",
    })
    check(r.status_code in (200, 201), "POST /api/auth/students = 2xx", _body(r))
    student_id = (r.json().get("user") or r.json()).get("id") if r.status_code < 300 else None

    r = client.post("/api/auth/login", json={"login": stud_login, "password": stud_pass})
    if not check(r.status_code == 200, "yangi talaba kira oladi", _body(r)):
        return _summary()
    S = {"Authorization": f"Bearer {r.json()['access_token']}"}
    student_id = r.json()["user"]["id"]
    must_change = r.json()["user"].get("must_change_password")
    check(must_change is True, "birinchi kirishda parol almashtirish talab qilinadi",
          f"must_change_password={must_change}")

    # Ikkinchi talaba — chat va reyting uchun kerak.
    stud2_login = f"e2e.talaba2.{suffix}"
    r = client.post("/api/auth/students", headers=A, json={
        "login": stud2_login, "password": stud_pass, "full_name": "E2E Talaba 2",
    })
    check(r.status_code in (200, 201), "ikkinchi talaba yaratildi", _body(r))
    r = client.post("/api/auth/login", json={"login": stud2_login, "password": stud_pass})
    S2 = {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else None
    student2_id = r.json()["user"]["id"] if r.status_code == 200 else None
    check(S2 is not None, "ikkinchi talaba kira oladi", _body(r))

    # ------------------------------------------------------------------ fan
    print("\n3. Fan CRUD (xodim)")
    r = client.post("/api/topics/subjects", headers=A,
                    json={"title": f"E2E Fan {suffix}", "description": "Sinov fani"})
    check(r.status_code in (200, 201), "fan yaratildi", _body(r))
    subject_id = _extract_id(r, "subject")
    check(subject_id is not None, "javobda fan id bor", _body(r))

    r = client.put(f"/api/topics/subjects/{subject_id}", headers=A,
                   json={"title": f"E2E Fan {suffix} (yangilandi)", "description": "yangi izoh"})
    check(r.status_code == 200, "fan yangilandi", _body(r))

    r = client.get("/api/topics/subjects", headers=S)
    check(r.status_code == 200 and any(x["id"] == subject_id for x in r.json()),
          "talaba fanlar ro'yxatida yangi fanni ko'radi", _body(r))

    # ---------------------------------------------------------------- mavzu
    print("\n4. Mavzu CRUD (xodim)")
    r = client.post("/api/topics/", headers=A, json={
        "subject_id": subject_id, "title": f"E2E Mavzu {suffix}",
        "description": "Sinov mavzusi",
        "content": TOPIC_CONTENT,
        "topic_type": "lecture", "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    })
    check(r.status_code in (200, 201), "mavzu yaratildi", _body(r))
    topic_id = _extract_id(r, "topic")
    check(topic_id is not None, "javobda mavzu id bor", _body(r))

    r = client.get(f"/api/topics/{topic_id}", headers=S)
    check(r.status_code == 200, "talaba mavzuni ochadi", _body(r))

    r = client.get("/api/topics/", headers=S, params={"subject_id": subject_id})
    check(r.status_code == 200 and any(x["id"] == topic_id for x in r.json()),
          "fan bo'yicha mavzular ro'yxati", _body(r))

    r = client.put(f"/api/topics/{topic_id}", headers=A, json={
        "subject_id": subject_id, "title": f"E2E Mavzu {suffix} (yangi)",
        # Matn mazmunli bo'lishi kerak — pastda shu mavzu bo'yicha AI test
        # generatsiyasi tekshiriladi.
        "content": TOPIC_CONTENT,
    })
    check(r.status_code == 200, "mavzu yangilandi", _body(r))

    r = client.get(f"/api/topics/{topic_id}/pdf", headers=S)
    check(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"),
          "mavzu PDF yuklandi", _body(r, 120))

    # -------------------------------------------------------------- material
    print("\n5. Material CRUD (xodim)")
    r = client.post(f"/api/topics/subjects/{subject_id}/materials", headers=A, json={
        "material_type": "book", "title": f"E2E Qo'llanma {suffix}",
        "detail": "PDF qo'llanma", "url": "https://example.com/kitob.pdf",
    })
    check(r.status_code in (200, 201), "material qo'shildi", _body(r))
    material_id = _extract_id(r, "material")

    r = client.get(f"/api/topics/subjects/{subject_id}/materials", headers=S)
    check(r.status_code == 200 and any(x["id"] == material_id for x in r.json()),
          "talaba materiallarni ko'radi", _body(r))

    r = client.put(f"/api/topics/materials/{material_id}", headers=A, json={
        "material_type": "book", "title": "Yangilangan qo'llanma",
        "url": "https://example.com/yangi.pdf",
    })
    check(r.status_code == 200, "material yangilandi", _body(r))

    # ---------------------------------------------------------------- jadval
    print("\n6. Dars jadvali CRUD (xodim)")
    group_name = f"G-{suffix[:4]}"
    r = client.post("/api/topics/schedules", headers=A, json={
        "subject_id": subject_id, "student_group": group_name, "day_of_week": 1,
        "start_time": "09:00", "end_time": "10:30", "room": "204-xona",
        "teacher_name": "Superadmin",
    })
    check(r.status_code in (200, 201), "jadval qo'shildi", _body(r))
    schedule_id = _extract_id(r, "schedule")

    r = client.get("/api/topics/schedules/all", headers=S, params={"student_group": group_name})
    check(r.status_code == 200 and any(x["id"] == schedule_id for x in r.json()),
          "talaba o'z guruhi jadvalini ko'radi", _body(r))

    r = client.put(f"/api/topics/schedules/{schedule_id}", headers=A, json={
        "subject_id": subject_id, "student_group": group_name, "day_of_week": 2,
        "start_time": "11:00", "end_time": "12:30", "room": "301-xona",
    })
    check(r.status_code == 200, "jadval yangilandi", _body(r))

    # ---------------------------------------------------------------- lug'at
    print("\n7. Tibbiy lug'at CRUD (xodim)")
    r = client.post("/api/topics/dictionary", headers=A, json={
        "word": f"Сердце{suffix[:3]}", "transcription": "[serdtse]", "gender": "sr",
        "translation": "Yurak", "category": "anatomiya",
        "example_ru": "Сердце бьётся.", "example_uz": "Yurak uradi.",
    })
    check(r.status_code in (200, 201), "termin qo'shildi", _body(r))
    term_id = _extract_id(r, "term")

    r = client.get("/api/topics/dictionary", headers=S, params={"query": suffix[:3]})
    check(r.status_code == 200, "talaba lug'atdan qidiradi", _body(r))

    r = client.put(f"/api/topics/dictionary/{term_id}", headers=A, json={
        "word": f"Сердце{suffix[:3]}", "translation": "Yurak (yangilandi)",
        "category": "anatomiya",
    })
    check(r.status_code == 200, "termin yangilandi", _body(r))

    # ----------------------------------------------------------------- guruh
    print("\n8. Guruhlar (xodim)")
    r = client.post("/api/auth/groups", headers=A, json={"name": group_name})
    check(r.status_code in (200, 201, 400), "guruh yaratildi yoki mavjud", _body(r))
    r = client.get("/api/auth/groups", headers=A)
    check(r.status_code == 200, "guruhlar ro'yxati", _body(r))
    groups = r.json() if r.status_code == 200 else []
    group_id = next((g["id"] for g in groups if isinstance(g, dict) and g.get("name") == group_name), None)

    r = client.post(f"/api/auth/students/{student2_id}/assign-group", headers=A,
                    json={"group_name": group_name})
    check(r.status_code == 200, "talaba guruhga biriktirildi", _body(r))

    # ------------------------------------------------------------------ e'lon
    print("\n9. E'lonlar (xodim yaratadi, talaba ko'radi)")
    r = client.post("/api/announcements/", headers=A, json={
        "title": f"E2E E'lon {suffix}", "content": "Ertaga dars bo'lmaydi.",
        "announcement_type": "umumiy",
    })
    check(r.status_code in (200, 201), "e'lon yaratildi", _body(r))
    ann_id = _extract_id(r, "announcement")

    r = client.get("/api/announcements/", headers=S)
    check(r.status_code == 200 and any(x["id"] == ann_id for x in r.json()),
          "talaba e'lonni ko'radi", _body(r))

    r = client.post(f"/api/announcements/{ann_id}/view", headers=S)
    check(r.status_code == 200, "e'lon o'qildi deb belgilandi", _body(r))

    r = client.put(f"/api/announcements/{ann_id}", headers=A,
                   json={"title": "Yangilangan e'lon"})
    check(r.status_code == 200, "e'lon yangilandi", _body(r))

    r = client.post("/api/announcements/", headers=S,
                    json={"title": "Ruxsatsiz", "content": "..."})
    check(r.status_code == 403, "talaba e'lon yarata olmaydi", _body(r))

    # ---------------------------------------------------------------- vazifa
    print("\n10. Uy vazifasi: yaratish -> topshirish -> baholash")
    r = client.post("/api/homework/", headers=A,
                    data={"title": f"E2E Vazifa {suffix}", "text": "5 ta savolga javob yozing.",
                          "subject_id": str(subject_id)},
                    files={"image": ("vazifa.png", PNG_1X1, "image/png")})
    check(r.status_code in (200, 201), "vazifa yaratildi (rasm bilan)", _body(r))
    homework_id = _extract_id(r, "homework")

    r = client.get("/api/homework/", headers=S)
    check(r.status_code == 200 and any(x["id"] == homework_id for x in r.json()),
          "talaba vazifani ko'radi", _body(r))

    r = client.post(f"/api/homework/{homework_id}/submit", headers=S,
                    data={"text": "Mening javobim."},
                    files={"image": ("javob.png", PNG_1X1, "image/png")})
    check(r.status_code in (200, 201), "talaba vazifani topshirdi", _body(r))
    submission_id = _extract_id(r, "submission")

    r = client.post(f"/api/homework/{homework_id}/submit", headers=S,
                    data={"text": "Qayta topshirdim."})
    check(r.status_code in (200, 201), "qayta topshirish ishlaydi (yangilanadi)", _body(r))

    r = client.get("/api/homework/submissions/my", headers=S)
    mine = next((x for x in r.json() if x["id"] == submission_id), {}) if r.status_code == 200 else {}
    check(bool(mine), "talaba o'z topshiriqlarini ko'radi", _body(r))
    check(mine.get("homework_title") == "Yangilangan vazifa" or "E2E Vazifa" in str(mine.get("homework_title")),
          "topshiriqda vazifa sarlavhasi bor", str(mine)[:200])

    r = client.get("/api/homework/", headers=A)
    hw_row = next((x for x in r.json() if x["id"] == homework_id), {}) if r.status_code == 200 else {}
    check(hw_row.get("submissions_count") == 1 and hw_row.get("pending_count") == 1,
          "xodim ro'yxatida javoblar soni ko'rinadi", str(hw_row)[:220])

    r = client.get("/api/homework/", headers=S)
    student_row = next((x for x in r.json() if x["id"] == homework_id), {}) if r.status_code == 200 else {}
    check("pending_count" not in student_row,
          "talabaga tekshiruv sanoqlari yuborilmaydi", str(student_row)[:200])

    r = client.get(f"/api/homework/{homework_id}/submissions", headers=A)
    check(r.status_code == 200 and any(x["id"] == submission_id for x in r.json()),
          "xodim topshiriqlar ro'yxatini ko'radi", _body(r))
    if r.status_code == 200 and r.json():
        check("student_name" in r.json()[0], "topshiriqda talaba ismi bor", str(r.json()[0].keys()))

    r = client.get(f"/api/homework/{homework_id}/submissions", headers=S)
    check(r.status_code == 403, "talaba topshiriqlar ro'yxatini ko'ra olmaydi", _body(r))

    r = client.post(f"/api/homework/submissions/{submission_id}/grade", headers=A,
                    json={"status": "approved", "grade": "5", "teacher_feedback": "Barakalla!"})
    check(r.status_code == 200, "xodim topshiriqni baholadi", _body(r))

    r = client.get("/api/homework/submissions/my", headers=S)
    graded = next((x for x in r.json() if x["id"] == submission_id), {}) if r.status_code == 200 else {}
    check(graded.get("status") == "approved" and graded.get("grade") == "5",
          "talaba bahoni ko'radi", str(graded)[:200])

    r = client.get("/api/notifications", headers=S)
    check(r.status_code == 200 and any(
        n.get("event_type") == "homework_graded" for n in _as_list(r.json())),
        "baholash bildirishnomasi keldi", _body(r, 300))

    r = client.put(f"/api/homework/{homework_id}", headers=A,
                   data={"title": "Yangilangan vazifa"})
    check(r.status_code == 200, "vazifa yangilandi", _body(r))

    # --------------------------------------------------------------- baholar
    print("\n11. Fan bo'yicha baho (xodim qo'yadi)")
    r = client.post("/api/quiz/grades", headers=A, json={
        "student_user_id": student_id, "subject_id": subject_id, "score": 92.5,
    })
    check(r.status_code == 200, "baho qo'yildi", _body(r))

    r = client.get(f"/api/quiz/grades/{student_id}", headers=S)
    row = next((x for x in r.json() if x["subject_id"] == subject_id), {}) if r.status_code == 200 else {}
    check(row.get("score") == 92.5 and row.get("grade_label") == "A'lo",
          "talaba bahoni ko'radi va yorliq to'g'ri", str(row)[:200])
    grade_id = row.get("grade_id")

    r = client.post("/api/quiz/grades", headers=A, json={
        "student_user_id": student_id, "subject_id": subject_id, "score": 70,
    })
    check(r.status_code == 200, "baho qayta yozildi (upsert)", _body(r))

    r = client.post("/api/quiz/grades", headers=S, json={
        "student_user_id": student_id, "subject_id": subject_id, "score": 100,
    })
    check(r.status_code == 403, "talaba o'ziga baho qo'ya olmaydi", _body(r))

    print("\n11a. Xodim paneli analitikasi")
    r = client.get("/api/auth/analytics", headers=A)
    if check(r.status_code == 200, "GET /api/auth/analytics = 200", _body(r, 200)):
        data = r.json()
        totals = data.get("totals", {})
        check(
            all(k in totals for k in (
                "students", "subjects", "topics", "schedules",
                "pending_applications", "pending_submissions",
            )),
            "analitikada barcha sonlar bor", str(totals)[:200],
        )
        check(totals.get("subjects", 0) >= 1 and totals.get("topics", 0) >= 1,
              "sonlar haqiqiy ma'lumotni aks ettiradi", str(totals)[:200])
        trend = data.get("trend", [])
        check(isinstance(trend, list) and len(trend) == 7,
              "haftalik dinamika 7 nuqtadan iborat", f"{len(trend)} ta")
        check(all("average" in p for p in trend), "har bir nuqtada o'rtacha bor")
        check(isinstance(data.get("top_students"), list),
              "eng faol talabalar ro'yxati bor", str(data.get("top_students"))[:150])

    r = client.get("/api/auth/analytics", headers=S)
    check(r.status_code == 403, "talaba analitikani ko'ra olmaydi", _body(r))

    r = client.get("/api/quiz/students", headers=A)
    check(r.status_code == 200 and any(x["id"] == student_id for x in r.json()),
          "xodim talabalar statistikasini ko'radi", _body(r, 150))

    r = client.get(f"/api/quiz/students/{student_id}/overview", headers=A)
    check(r.status_code == 200, "talaba bo'yicha umumiy ma'lumot", _body(r, 150))

    r = client.get(f"/api/auth/students/{student_id}/academic-stats", headers=A)
    check(r.status_code == 200, "akademik statistika", _body(r, 150))

    r = client.post(f"/api/auth/students/{student_id}/targets", headers=A, json={
        "target_topics": 10, "target_quizzes": 5, "target_ai_questions": 20,
    })
    check(r.status_code == 200, "maqsadlar belgilandi", _body(r))

    r = client.get(f"/api/auth/students/{student_id}/gamification", headers=S)
    check(r.status_code == 200, "talaba geymifikatsiyani ko'radi", _body(r, 150))

    # ------------------------------------------------------------------ chat
    # --------------------------------------------------------------- tahlil
    print("\n11b. Chuqurlashtirilgan tahlil")
    r = client.get("/api/analytics/groups", headers=A)
    groups_data = _as_list(r.json()) if r.status_code == 200 else []
    check(r.status_code == 200 and groups_data, "guruhlar kesimi", _body(r, 200))
    if groups_data:
        row = groups_data[0]
        check(all(k in row for k in (
            "student_group", "students", "average_score", "attendance_percent",
            "homework_percent", "accuracy")),
            "guruh yozuvida barcha ko'rsatkichlar bor", str(row)[:200])

    r = client.get("/api/analytics/subjects", headers=A)
    subjects_data = _as_list(r.json()) if r.status_code == 200 else []
    check(r.status_code == 200 and any(x["subject_id"] == subject_id for x in subjects_data),
          "fanlar kesimida yangi fan bor", _body(r, 200))

    r = client.get("/api/analytics/at-risk", headers=A)
    check(r.status_code == 200 and isinstance(r.json(), list),
          "e'tibor talab qiladigan talabalar ro'yxati", _body(r, 150))
    if r.status_code == 200 and r.json():
        check(all(x.get("reasons") for x in r.json()),
              "har bir talabada sabab ko'rsatilgan", str(r.json()[0])[:200])

    r = client.get("/api/analytics/activity", headers=A, params={"days": 14})
    activity = r.json() if r.status_code == 200 else {}
    check(r.status_code == 200 and len(activity.get("series", [])) == 14,
          "kunlik faollik 14 nuqta", _body(r, 150))
    check(all(k in (activity.get("series") or [{}])[0]
              for k in ("date", "quizzes", "submissions", "attendance", "ai_questions")),
          "faollik yozuvida barcha turlar bor", str(activity.get("series", [{}])[0])[:150])

    r = client.get("/api/analytics/teachers", headers=A)
    teachers_data = _as_list(r.json()) if r.status_code == 200 else []
    check(r.status_code == 200 and teachers_data, "xodimlar faoliyati", _body(r, 200))
    if teachers_data:
        check(all(k in teachers_data[0] for k in (
            "topics", "homeworks", "graded_submissions", "attendance_marked")),
            "xodim yozuvida faoliyat sonlari bor", str(teachers_data[0])[:200])

    r = client.get("/api/analytics/report/pdf", headers=A)
    check(r.status_code == 200
          and r.headers.get("content-type", "").startswith("application/pdf"),
          "tahlil PDF hisoboti", _body(r, 120))

    # Rol chegaralari
    r = client.get("/api/analytics/groups", headers=S)
    check(r.status_code == 403, "talaba tahlilni ko'ra olmaydi", _body(r))

    print("\n12. Chat")
    r = client.post("/api/chat/send", headers=S,
                    json={"recipient_id": admin_id, "message_text": "Assalomu alaykum, ustoz!"})
    check(r.status_code in (200, 201), "talaba xodimga xabar yubordi", _body(r))

    r = client.get("/api/chat/messages", headers=S, params={"other_user_id": admin_id})
    msgs = _as_list(r.json()) if r.status_code == 200 else []
    check(r.status_code == 200 and len(msgs) >= 1, "yozishma o'qildi", _body(r, 200))

    r = client.get("/api/chat/messages", headers=A, params={"other_user_id": student_id})
    check(r.status_code == 200 and len(_as_list(r.json())) >= 1,
          "xodim tomonda ham xuddi shu yozishma", _body(r, 200))

    r = client.post("/api/chat/send", headers=A,
                    json={"recipient_id": student_id, "message_text": "Va alaykum assalom."})
    check(r.status_code in (200, 201), "xodim javob yozdi", _body(r))

    r = client.post("/api/chat/typing", headers=S, json={"recipient_id": admin_id})
    check(r.status_code == 200, "yozmoqda signali", _body(r))

    r = client.post("/api/chat/send-image", headers=S,
                    data={"recipient_id": str(admin_id), "message_text": "Rasm"},
                    files={"image": ("rasm.png", PNG_1X1, "image/png")})
    check(r.status_code in (200, 201), "rasmli xabar yuborildi", _body(r))

    r = client.get("/api/chat/contacts", headers=S)
    check(r.status_code == 200, "kontaktlar ro'yxati", _body(r, 200))

    if S2:
        r = client.get("/api/chat/messages", headers=S2, params={"other_user_id": admin_id})
        other = _as_list(r.json()) if r.status_code == 200 else []
        leaked = any("Assalomu alaykum, ustoz!" == m.get("message_text") for m in other)
        check(not leaked, "boshqa talaba begona yozishmani ko'rmaydi", f"{len(other)} ta xabar")

    print("\n13. Guruh chati")
    r = client.post("/api/chat/group/messages", headers=S,
                    data={"group_name": group_name, "message_text": f"Guruhga salom {suffix}"})
    check(r.status_code in (200, 201), "guruhga xabar yuborildi", _body(r))

    r = client.get("/api/chat/group/messages", headers=S, params={"group_name": group_name})
    check(r.status_code == 200 and any(
        f"Guruhga salom {suffix}" == m.get("message_text") for m in _as_list(r.json())),
        "guruh xabarlari o'qildi", _body(r, 250))

    # -------------------------------------------------------- bildirishnomalar
    print("\n14. Bildirishnomalar")
    r = client.get("/api/notifications/unread-count", headers=S)
    check(r.status_code == 200, "o'qilmagan soni", _body(r))
    unread_before = r.json().get("count", 0) if r.status_code == 200 else 0

    r = client.get("/api/notifications", headers=S)
    items = _as_list(r.json()) if r.status_code == 200 else []
    if items:
        nid = items[0].get("id")
        r = client.post(f"/api/notifications/{nid}/read", headers=S)
        check(r.status_code == 200, "bitta bildirishnoma o'qildi", _body(r))

    r = client.post("/api/notifications/read-all", headers=S)
    check(r.status_code == 200, "hammasi o'qildi", _body(r))
    r = client.get("/api/notifications/unread-count", headers=S)
    check(r.status_code == 200 and r.json().get("count") == 0,
          "o'qilmagan soni 0 ga tushdi", f"oldin={unread_before}, hozir={_body(r, 80)}")

    # ----------------------------------------------------------------- arena
    print("\n15. Klinik arena")
    r = client.get("/api/topics/arena/case", headers=S)
    if check(r.status_code == 200, "keys olindi", _body(r, 150)):
        case = r.json()
        stages = case.get("stages", [])
        r = client.post("/api/topics/arena/case/submit", headers=S, json={
            "case_id": str(case.get("id")),   # ilova ham `id` maydonini yuboradi
            "selected_answers": ["A"] * len(stages),
        })
        check(r.status_code == 200, "keys topshirildi", _body(r, 200))

    r = client.get("/api/topics/arena/history", headers=S)
    check(r.status_code == 200, "arena tarixi", _body(r, 150))

    # ----------------------------------------------------------------- reyting
    print("\n16. Reyting va profil")
    r = client.get("/api/auth/leaderboard", headers=S, params={"limit": 10, "offset": 0})
    check(r.status_code == 200, "reyting ro'yxati", _body(r, 150))

    r = client.post("/api/profile/me/avatar", headers=S,
                    files={"image": ("avatar.png", PNG_1X1, "image/png")})
    check(r.status_code in (200, 201), "avatar yuklandi", _body(r))

    r = client.get("/api/profile/me", headers=S)
    avatar = (r.json().get("profile") or r.json()).get("avatar_path") if r.status_code == 200 else None
    check(bool(avatar), "profilda avatar yo'li bor", _body(r, 200))
    if avatar:
        rr = client.get(avatar)
        check(rr.status_code == 200, "avatar fayli statik tarqatiladi", str(rr.status_code))

    r = client.delete("/api/profile/me/avatar", headers=S)
    check(r.status_code == 200, "avatar o'chirildi", _body(r))

    r = client.get("/api/profile/requests/types", headers=S)
    check(r.status_code == 200, "murojaat turlari ro'yxati", _body(r, 150))

    # ------------------------------------------------------------ fayl xavfsizligi
    print("\n17. Fayl yuklash cheklovlari")
    r = client.post("/api/profile/me/avatar", headers=S,
                    files={"image": ("zararli.exe", b"MZ\x90\x00", "application/x-msdownload")})
    check(r.status_code == 415, "ruxsatsiz fayl turi rad etildi", _body(r))

    r = client.post("/api/profile/me/avatar", headers=S,
                    files={"image": ("bosh.png", b"", "image/png")})
    check(r.status_code == 400, "bo'sh fayl rad etildi", _body(r))

    # --------------------------------------------------------------- AI oqimi
    print("\n18. Test (AI)")
    r = client.post("/api/quiz/generate", headers=S, json={"topic_id": topic_id, "language": "uz"})
    if r.status_code == 200:
        # Testni tashlab yuborib qaytadan boshlash — eski (tugallanmagan)
        # urinish tozalanishi va yangi urinish xatosiz ochilishi kerak.
        r = client.post("/api/quiz/generate", headers=S,
                        json={"topic_id": topic_id, "language": "uz"})
        check(r.status_code == 200, "testni qaytadan boshlash ishlaydi", _body(r, 250))
    if r.status_code == 200:
        quiz = r.json()
        check(all("correct_option" not in q for q in quiz["questions"]),
              "test savollarida to'g'ri javob yo'q")
        attempt_id = quiz["attempt_id"]
        r = client.post("/api/quiz/submit", headers=S, json={
            "attempt_id": attempt_id,
            "answers": [{"question_id": q["id"], "selected_option": "A"} for q in quiz["questions"]],
            "elapsed_seconds": 42,
        })
        if check(r.status_code == 200, "test topshirildi", _body(r, 200)):
            check("results" in r.json() and r.json()["total"] == quiz["total_questions"],
                  "natija to'liq qaytdi", _body(r, 150))
        r = client.post("/api/quiz/submit", headers=S,
                        json={"attempt_id": attempt_id, "answers": []})
        check(r.status_code == 409, "qayta topshirish = 409", _body(r))
        r = client.get(f"/api/quiz/attempt/{attempt_id}", headers=S)
        check(r.status_code == 200, "urinish tafsiloti", _body(r, 150))
        r = client.get("/api/quiz/report/pdf", headers=S, params={"attempt_id": attempt_id})
        check(r.status_code == 200, "natija PDF", _body(r, 120))
        if S2:
            r = client.get(f"/api/quiz/attempt/{attempt_id}", headers=S2)
            check(r.status_code == 403, "begona talaba urinishni ko'ra olmaydi", _body(r))
    elif r.status_code in (502, 429):
        skip("test generatsiya", f"AI xizmati mavjud emas ({r.status_code})")
    else:
        check(False, "POST /api/quiz/generate kutilmagan javob", _body(r, 250))

    r = client.post(f"/api/topics/{topic_id}/ask", headers=S,
                    json={"question": "Yurak nima?", "language": "uz"})
    if r.status_code in (502, 429):
        skip("mavzu bo'yicha savol", f"AI xizmati mavjud emas ({r.status_code})")
    else:
        check(r.status_code == 200, "mavzu bo'yicha AI savol", _body(r, 200))

    r = client.get(f"/api/topics/{topic_id}/translation", headers=S, params={"language": "uz"})
    check(r.status_code == 200, "o'zbekcha tarjima (AI'siz)", _body(r, 150))

    # ---------------------------------------------------------------- imtihon
    print("\n18a. Imtihon rejimi")
    r = client.get("/api/exam/active", headers=S)
    check(r.status_code == 200 and r.json().get("active") is None,
          "boshda tugallanmagan imtihon yo'q", _body(r, 150))

    r = client.post("/api/exam/start", headers=S, json={
        "subject_id": subject_id, "question_count": 5, "duration_minutes": 15,
    })
    if r.status_code == 200:
        exam = r.json()
        exam_id = exam["attempt_id"]
        questions = exam["questions"]
        check(len(questions) == exam["total_questions"] >= 5,
              "imtihon savollari tuzildi", f"{len(questions)} ta")
        check(all("correct_option" not in q and "expected_answer" not in q for q in questions),
              "imtihonda to'g'ri javoblar klientga sizmaydi")
        check(exam["remaining_seconds"] is not None and exam["remaining_seconds"] <= 900,
              "qolgan vaqt serverdan keldi", str(exam.get("remaining_seconds")))

        r = client.post("/api/exam/start", headers=S, json={"subject_id": subject_id})
        check(r.status_code == 409, "bir vaqtda ikkita imtihon bo'lmaydi", _body(r, 150))

        first = questions[0]
        r = client.post(f"/api/exam/{exam_id}/answer", headers=S,
                        json={"question_id": first["id"], "selected_option": "A"})
        check(r.status_code == 200 and r.json().get("answered_count") == 1,
              "javob darhol saqlandi", _body(r, 150))

        r = client.post(f"/api/exam/{exam_id}/answer", headers=S,
                        json={"question_id": first["id"], "selected_option": "Z"})
        check(r.status_code == 400, "mavjud bo'lmagan variant rad etildi", _body(r))

        r = client.get(f"/api/exam/{exam_id}", headers=S)
        resumed = r.json() if r.status_code == 200 else {}
        saved = [q.get("selected_option") for q in resumed.get("questions", [])]
        check(r.status_code == 200 and saved and saved[0] == "A",
              "imtihonni davom ettirish javoblarni tiklaydi", str(saved)[:120])

        if S2:
            r = client.get(f"/api/exam/{exam_id}", headers=S2)
            check(r.status_code == 403, "begona talaba imtihonni ocha olmaydi", _body(r))
            r = client.post(f"/api/exam/{exam_id}/answer", headers=S2,
                            json={"question_id": first["id"], "selected_option": "A"})
            check(r.status_code == 403, "begona talaba javob yoza olmaydi", _body(r))

        r = client.post(f"/api/exam/{exam_id}/submit", headers=S, json={
            "answers": [{"question_id": q["id"], "selected_option": "B"} for q in questions[1:]],
        })
        if check(r.status_code == 200, "imtihon yakunlandi", _body(r, 200)):
            result = r.json()
            check(result["total"] == len(questions)
                  and 0 <= result["score"] <= result["total"],
                  "ball server tomonda hisoblandi",
                  f"{result.get('score')}/{result.get('total')}")
            check(result.get("grade_label") and "percent" in result,
                  "baho yorlig'i va foiz qaytdi", str(result)[:150])
            check(isinstance(result.get("topic_breakdown"), list)
                  and result["topic_breakdown"],
                  "mavzular kesimida tahlil bor", str(result.get("topic_breakdown"))[:150])
            check("correct_option" in result["results"][0],
                  "yakundan keyin to'g'ri javoblar ko'rsatiladi")

        r = client.post(f"/api/exam/{exam_id}/submit", headers=S, json={"answers": []})
        check(r.status_code == 409, "imtihonni qayta yakunlab bo'lmaydi", _body(r))

        r = client.get(f"/api/exam/{exam_id}/result", headers=S)
        check(r.status_code == 200, "natijani qayta o'qish", _body(r, 120))

        r = client.get(f"/api/exam/{exam_id}/report/pdf", headers=S)
        check(r.status_code == 200
              and r.headers.get("content-type", "").startswith("application/pdf"),
              "imtihon PDF hisoboti", _body(r, 120))

        r = client.get("/api/exam/history", headers=S)
        check(r.status_code == 200 and any(x["attempt_id"] == exam_id for x in _as_list(r.json())),
              "imtihon tarixda ko'rinadi", _body(r, 150))

        r = client.get("/api/exam/active", headers=S)
        check(r.status_code == 200 and r.json().get("active") is None,
              "yakunlangach aktiv imtihon qolmadi", _body(r, 120))

        # Bank ishlayotganini tekshiramiz: ikkinchi imtihon AI'siz tuzilishi kerak.
        started = time.monotonic()
        r = client.post("/api/exam/start", headers=S, json={
            "subject_id": subject_id, "question_count": 5, "duration_minutes": 5,
        })
        elapsed = time.monotonic() - started
        if check(r.status_code == 200, "ikkinchi imtihon boshlandi", _body(r, 150)):
            check(elapsed < 5, "savollar bankdan olindi (AI kutilmadi)",
                  f"{elapsed:.1f}s")
            client.post(f"/api/exam/{r.json()['attempt_id']}/submit",
                        headers=S, json={"answers": []})
    elif r.status_code == 422:
        skip("imtihon rejimi", "savollar banki bo'sh va AI mavjud emas")
    else:
        check(False, "POST /api/exam/start kutilmagan javob", _body(r, 250))

    r = client.post("/api/exam/start", headers=S, json={"question_count": 5})
    check(r.status_code == 400, "fansiz imtihon boshlanmaydi", _body(r))

    # ------------------------------------------------------------- xodimlar
    print("\n19. Xodimlarni boshqarish (superadmin)")
    emp_login = f"e2e.ustoz.{suffix}"
    r = client.post("/api/auth/employees", headers=A, json={
        "login": emp_login, "password": "Ustoz12345", "full_name": "E2E Ustoz",
        "department": "Anatomiya kafedrasi", "degree": "PhD", "role": "employee",
    })
    check(r.status_code in (200, 201), "xodim yaratildi", _body(r))
    employee_id = _extract_id(r, "user") or _extract_id(r, "employee")

    r = client.post("/api/auth/login", json={"login": emp_login, "password": "Ustoz12345"})
    check(r.status_code == 200, "xodim kira oladi", _body(r))
    E = {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else None

    if E:
        r = client.get("/api/auth/students", headers=E)
        check(r.status_code == 200, "xodim talabalar ro'yxatini ko'radi", _body(r, 120))
        r = client.post("/api/topics/subjects", headers=E, json={"title": f"Ustoz fani {suffix}"})
        check(r.status_code in (200, 201), "xodim fan yarata oladi", _body(r))
        emp_subject_id = _extract_id(r, "subject")
        if emp_subject_id:
            client.delete(f"/api/topics/subjects/{emp_subject_id}", headers=A)
        r = client.post("/api/auth/employees", headers=E, json={
            "login": f"x.{suffix}", "password": "Parol12345", "full_name": "Ruxsatsiz",
        })
        check(r.status_code == 403, "oddiy xodim boshqa xodim yarata olmaydi", _body(r))

    r = client.get("/api/auth/teachers", headers=S)
    check(r.status_code == 200 and any(t.get("full_name") == "E2E Ustoz" for t in _as_list(r.json())),
          "talaba professorlar ro'yxatida yangi ustozni ko'radi", _body(r, 200))

    if employee_id:
        r = client.put(f"/api/auth/employees/{employee_id}", headers=A,
                       json={"bio": "20 yillik tajriba", "degree": "DSc"})
        check(r.status_code == 200, "xodim profili yangilandi", _body(r))

    # -------------------------------------------------------------- arizalar
    # ----------------------------------------------------------------- davomat
    print("\n19a. Davomat")
    # Jadval yaratganimizda kun 2 ga o'zgartirilgan edi — shu kunga to'g'ri
    # keladigan eng yaqin o'tgan sanani topamiz.
    today = date.today()
    lesson_day = 2  # seshanba (yuqorida jadval shu kunga ko'chirilgan)
    lesson_date = today - timedelta(days=(today.isoweekday() - lesson_day) % 7)
    if lesson_date > today:
        lesson_date -= timedelta(days=7)

    r = client.get("/api/attendance/lessons", headers=A,
                   params={"date": lesson_date.isoformat(), "student_group": group_name})
    lessons = _as_list(r.json()) if r.status_code == 200 else []
    mine = next((x for x in lessons if x["schedule_id"] == schedule_id), None)
    check(r.status_code == 200 and mine is not None,
          "shu kundagi darslar ro'yxati", _body(r, 200))

    if mine:
        check(mine.get("is_marked") is False, "dars hali belgilanmagan", str(mine)[:150])

        r = client.get("/api/attendance/roster", headers=A,
                       params={"schedule_id": schedule_id, "date": lesson_date.isoformat()})
        roster = r.json() if r.status_code == 200 else {}
        students_in = roster.get("students", [])
        check(r.status_code == 200 and any(
            s["student_user_id"] == student2_id for s in students_in),
            "guruh talabalari ro'yxatda", _body(r, 200))
        check(all(s["status"] is None for s in students_in),
              "boshda hech kim belgilanmagan", str(students_in)[:150])

        r = client.get("/api/attendance/roster", headers=S,
                       params={"schedule_id": schedule_id, "date": lesson_date.isoformat()})
        check(r.status_code == 403, "talaba ro'yxatni ko'ra olmaydi", _body(r))

        # Talaba 2 shu guruhda — uni "kelmadi" deb belgilaymiz.
        r = client.post("/api/attendance/mark", headers=A, json={
            "schedule_id": schedule_id,
            "lesson_date": lesson_date.isoformat(),
            "records": [{"student_user_id": student2_id, "status": "absent",
                         "note": "Sababsiz"}],
        })
        check(r.status_code == 200 and r.json().get("saved") == 1,
              "davomat belgilandi", _body(r, 200))

        r = client.post("/api/attendance/mark", headers=S, json={
            "schedule_id": schedule_id, "lesson_date": lesson_date.isoformat(),
            "records": [{"student_user_id": student2_id, "status": "present"}],
        })
        check(r.status_code == 403, "talaba davomat belgilay olmaydi", _body(r))

        r = client.post("/api/attendance/mark", headers=A, json={
            "schedule_id": schedule_id,
            "lesson_date": (today + timedelta(days=7)).isoformat(),
            "records": [{"student_user_id": student2_id, "status": "present"}],
        })
        check(r.status_code == 400, "kelajakdagi dars rad etildi", _body(r))

        r = client.post("/api/attendance/mark", headers=A, json={
            "schedule_id": schedule_id,
            "lesson_date": (lesson_date + timedelta(days=1)).isoformat(),
            "records": [{"student_user_id": student2_id, "status": "present"}],
        })
        check(r.status_code == 400, "hafta kuniga mos kelmagan sana rad etildi", _body(r))

        r = client.post("/api/attendance/mark", headers=A, json={
            "schedule_id": schedule_id, "lesson_date": lesson_date.isoformat(),
            "records": [{"student_user_id": admin_id, "status": "present"}],
        })
        check(r.status_code == 400, "begona talabani belgilash rad etildi", _body(r))

        r = client.get("/api/attendance/lessons", headers=A,
                       params={"date": lesson_date.isoformat(), "student_group": group_name})
        marked = next((x for x in _as_list(r.json()) if x["schedule_id"] == schedule_id), {})
        check(marked.get("is_marked") is True and marked.get("marked_count") == 1,
              "dars belgilangan deb ko'rinadi", str(marked)[:150])

        # Talaba o'z davomatini ko'radi
        if S2:
            r = client.get("/api/attendance/my", headers=S2)
            mine_att = r.json() if r.status_code == 200 else {}
            records = mine_att.get("records", [])
            record_id = records[0]["id"] if records else None
            check(r.status_code == 200 and len(records) == 1,
                  "talaba o'z davomatini ko'radi", _body(r, 200))
            check(mine_att.get("summary", {}).get("percent") == 0.0
                  and mine_att.get("summary", {}).get("absent") == 1,
                  "foiz hisoblandi", str(mine_att.get("summary"))[:150])
            check(bool(mine_att.get("summary", {}).get("subjects")),
                  "fan kesimida tahlil bor", str(mine_att.get("summary", {}).get("subjects"))[:150])

            r = client.get("/api/notifications", headers=S2)
            check(r.status_code == 200 and any(
                n.get("event_type") == "attendance_absent" for n in _as_list(r.json())),
                "qoldirilgan dars uchun bildirishnoma keldi", _body(r, 200))

            # Sabab yuborish
            if record_id:
                r = client.post("/api/attendance/excuses", headers=S2, json={
                    "record_id": record_id, "reason": "Kasal bo'lib qoldim, spravka bor.",
                })
                check(r.status_code == 201, "talaba sabab yubordi", _body(r, 200))

                r = client.post("/api/attendance/excuses", headers=S2, json={
                    "record_id": record_id, "reason": "Yana bir marta",
                })
                check(r.status_code == 409, "takroriy sabab rad etildi", _body(r))

                r = client.post("/api/attendance/excuses", headers=S, json={
                    "record_id": record_id, "reason": "Begona sabab",
                })
                check(r.status_code == 403, "begona talaba sabab yubora olmaydi", _body(r))

                r = client.get("/api/attendance/excuses/pending-count", headers=A)
                check(r.status_code == 200 and r.json().get("count", 0) >= 1,
                      "kutilayotgan sabablar soni", _body(r))

                r = client.get("/api/attendance/excuses", headers=A, params={"status": "pending"})
                check(r.status_code == 200 and any(
                    x["id"] == record_id for x in _as_list(r.json())),
                    "xodim sabab so'rovini ko'radi", _body(r, 200))

                r = client.post(f"/api/attendance/excuses/{record_id}/review", headers=S2,
                                json={"approve": True})
                check(r.status_code == 403, "talaba sababni tasdiqlay olmaydi", _body(r))

                r = client.post(f"/api/attendance/excuses/{record_id}/review", headers=A,
                                json={"approve": True, "comment": "Spravka qabul qilindi"})
                check(r.status_code == 200
                      and r.json()["record"]["status"] == "excused"
                      and r.json()["record"]["excuse_status"] == "approved",
                      "xodim sababni tasdiqladi, holat 'sababli' bo'ldi", _body(r, 250))

                r = client.post(f"/api/attendance/excuses/{record_id}/review", headers=A,
                                json={"approve": False})
                check(r.status_code == 409, "qayta ko'rib chiqish rad etildi", _body(r))

                r = client.get("/api/attendance/my", headers=S2)
                summary = r.json().get("summary", {}) if r.status_code == 200 else {}
                check(summary.get("percent") == 100.0 and summary.get("excused") == 1,
                      "sababli qoldirish foizni tushirmaydi", str(summary)[:150])

                r = client.get("/api/notifications", headers=S2)
                check(r.status_code == 200 and any(
                    n.get("event_type") == "excuse_reviewed" for n in _as_list(r.json())),
                    "sabab javobi bildirishnomasi keldi", _body(r, 200))

        # Hisobot
        r = client.get("/api/attendance/group", headers=A, params={
            "student_group": group_name,
            "from": (lesson_date - timedelta(days=7)).isoformat(),
            "to": lesson_date.isoformat(),
        })
        report = r.json() if r.status_code == 200 else {}
        check(r.status_code == 200 and report.get("dates") and report.get("students"),
              "guruh hisoboti", _body(r, 200))

        r = client.get("/api/attendance/group/report/pdf", headers=A, params={
            "student_group": group_name,
            "from": (lesson_date - timedelta(days=7)).isoformat(),
            "to": lesson_date.isoformat(),
        })
        check(r.status_code == 200
              and r.headers.get("content-type", "").startswith("application/pdf"),
              "davomat PDF hisoboti", _body(r, 120))

        r = client.get("/api/attendance/group", headers=A, params={
            "student_group": group_name, "from": lesson_date.isoformat(),
            "to": (lesson_date - timedelta(days=1)).isoformat(),
        })
        check(r.status_code == 400, "teskari davr rad etildi", _body(r))

        r = client.get("/api/attendance/group", headers=S, params={
            "student_group": group_name, "from": lesson_date.isoformat(),
            "to": lesson_date.isoformat(),
        })
        check(r.status_code == 403, "talaba guruh hisobotini ko'ra olmaydi", _body(r))

        if student2_id:
            r = client.get(f"/api/attendance/summary/{student2_id}", headers=A)
            check(r.status_code == 200 and r.json()["summary"]["total"] == 1,
                  "xodim talaba davomat xulosasini ko'radi", _body(r, 150))
            r = client.get(f"/api/attendance/summary/{student2_id}", headers=S)
            check(r.status_code == 403, "talaba begona xulosani ko'ra olmaydi", _body(r))

            r = client.get(f"/api/auth/students/{student2_id}/academic-stats", headers=A)
            check(r.status_code == 200 and "attendance_percent" in r.json(),
                  "davomat akademik statistikada", _body(r, 200))

        r = client.get("/api/auth/analytics", headers=A)
        totals = r.json().get("totals", {}) if r.status_code == 200 else {}
        check("unmarked_lessons_today" in totals and "pending_excuses" in totals
              and "attendance_percent" in r.json(),
              "davomat xodim analitikasida", str(totals)[:200])

    print("\n20. Ariza rad etish oqimi")
    rej_login = f"e2e.rad.{suffix}"
    r = client.post("/api/auth/register", json={
        "login": rej_login, "password": "Talaba12345", "full_name": "Rad etiladigan",
    })
    check(r.status_code == 201, "ariza yuborildi", _body(r))
    app_id = r.json().get("application_id") if r.status_code == 201 else None

    r = client.get("/api/auth/applications", headers=A, params={"status": "pending"})
    check(r.status_code == 200 and any(x["id"] == app_id for x in _as_list(r.json())),
          "kutilayotgan arizalar ro'yxati", _body(r, 200))

    r = client.get("/api/auth/applications/pending-count", headers=A)
    check(r.status_code == 200 and r.json().get("count", 0) >= 1, "kutilayotgan arizalar soni", _body(r))

    if app_id:
        r = client.post(f"/api/auth/applications/{app_id}/reject", headers=A,
                        json={"reason": "Ma'lumotlar to'liq emas"})
        check(r.status_code == 200, "ariza rad etildi", _body(r))
        r = client.post("/api/auth/login", json={"login": rej_login, "password": "Talaba12345"})
        check(r.status_code == 403, "rad etilgan ariza egasi kira olmaydi", _body(r))
        r = client.post(f"/api/auth/applications/{app_id}/approve", headers=A)
        check(r.status_code in (400, 409), "rad etilgan arizani tasdiqlab bo'lmaydi", _body(r))

    # ------------------------------------------------------- parol tiklash
    print("\n21. Parolni tiklash (xodim)")
    r = client.post(f"/api/auth/students/{student_id}/reset-password", headers=A,
                    json={"new_password": "TiklanganParol1"})
    check(r.status_code == 200, "parol tiklandi", _body(r))
    r = client.post("/api/auth/login", json={"login": stud_login, "password": "TiklanganParol1"})
    check(r.status_code == 200, "yangi parol bilan kirish", _body(r))
    if r.status_code == 200:
        S = {"Authorization": f"Bearer {r.json()['access_token']}"}
        check(r.json()["user"].get("must_change_password") is True,
              "tiklashdan keyin parol almashtirish talab qilinadi", _body(r, 200))

    r = client.put(f"/api/auth/students/{student_id}", headers=A,
                   json={"full_name": "E2E Talaba (yangilandi)", "student_group": group_name})
    check(r.status_code == 200, "talaba ma'lumoti yangilandi", _body(r))

    # ---------------------------------------------------------------- tozalash
    print("\n22. O'chirish oqimlari")
    for label, path in [
        ("baho", f"/api/quiz/grades/{grade_id}" if grade_id else None),
        ("vazifa", f"/api/homework/{homework_id}"),
        ("e'lon", f"/api/announcements/{ann_id}"),
        ("termin", f"/api/topics/dictionary/{term_id}"),
        ("jadval", f"/api/topics/schedules/{schedule_id}"),
        ("material", f"/api/topics/materials/{material_id}"),
        ("mavzu", f"/api/topics/{topic_id}"),
        ("fan", f"/api/topics/subjects/{subject_id}"),
        ("guruh", f"/api/auth/groups/{group_id}" if group_id else None),
        ("xodim", f"/api/auth/employees/{employee_id}" if employee_id else None),
    ]:
        if not path or "None" in path:
            continue
        r = client.delete(path, headers=A)
        check(r.status_code == 200, f"{label} o'chirildi", _body(r))

    client.delete(f"/api/auth/students/{student_id}", headers=A)
    if student2_id:
        client.delete(f"/api/auth/students/{student2_id}", headers=A)

    return _summary()


def _as_list(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "data", "messages", "notifications"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _extract_id(r: httpx.Response, *keys: str):
    """Javobdan yaratilgan obyekt id'sini oladi (turli formatlarni qo'llaydi)."""
    if r.status_code >= 300:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        for key in keys:
            nested = data.get(key)
            if isinstance(nested, dict) and "id" in nested:
                return nested["id"]
        for key in keys:
            # {"topic_id": 1} ko'rinishi
            if isinstance(data.get(f"{key}_id"), int):
                return data[f"{key}_id"]
        if "id" in data:
            return data["id"]
    return None


def _summary() -> int:
    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{'=' * 60}\nNatija: {passed}/{total} test o'tdi"
          + (f", {len(_skipped)} ta o'tkazib yuborildi" if _skipped else ""))
    failed = [label for ok, label in _results if not ok]
    if failed:
        print("O'tmagan testlar:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("Hammasi joyida.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--admin-password", required=True)
    parsed = parser.parse_args()
    sys.exit(run(parsed.base_url, parsed.admin_login, parsed.admin_password))
