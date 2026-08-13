"""Uchidan-uchiga tekshiruv: auth, ruxsatlar va asosiy oqimlar.

Ishlab turgan serverga qarshi ishlaydi (AI chaqiruvlari o'tkazib yuboriladi).

    cd backend
    uvicorn main:app --port 8000 &
    python3 scripts/smoke_test.py --base-url http://127.0.0.1:8000 \
        --admin-login admin --admin-password 'Parol123!'
"""

import argparse
import sys
import uuid

import httpx

PASS = "\033[32mOK\033[0m"
FAIL = "\033[31mXATO\033[0m"

_results: list[tuple[bool, str]] = []


def check(condition: bool, label: str, detail: str = "") -> bool:
    _results.append((condition, label))
    mark = PASS if condition else FAIL
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
    return condition


def run(base_url: str, admin_login: str, admin_password: str) -> int:
    client = httpx.Client(base_url=base_url, timeout=30.0)
    suffix = uuid.uuid4().hex[:8]
    student_login = f"test.talaba.{suffix}"
    student_password = "Talaba12345"

    print("\n1. Xizmat holati")
    r = client.get("/health")
    check(r.status_code == 200, "GET /health = 200", f"{r.status_code} {r.text[:120]}")

    print("\n2. Himoyalanmagan kirish bloklanadi")
    r = client.get("/api/auth/students")
    check(r.status_code == 401, "tokensiz GET /api/auth/students = 401", str(r.status_code))
    r = client.get("/api/topics/", headers={"Authorization": "Bearer soxta.token.qiymat"})
    check(r.status_code == 401, "soxta token = 401", str(r.status_code))

    print("\n3. Admin kirishi")
    r = client.post("/api/auth/login", json={"login": admin_login, "password": admin_password})
    if not check(r.status_code == 200, "admin login = 200", f"{r.status_code} {r.text[:200]}"):
        print("\nAdmin kira olmadi — qolgan testlar o'tkazib yuborildi.")
        return 1
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/api/auth/me", headers=admin_headers)
    check(r.status_code == 200 and r.json().get("login") == admin_login.lower(), "GET /api/auth/me")

    print("\n4. Ro'yxatdan o'tish -> tasdiqlash -> kirish")
    r = client.post("/api/auth/register", json={
        "login": student_login,
        "password": student_password,
        "full_name": "Test Talaba",
        "phone_number": "+998900000000",
    })
    check(r.status_code == 201, "register = 201", f"{r.status_code} {r.text[:200]}")
    application_id = r.json().get("application_id") if r.status_code == 201 else None

    r = client.post("/api/auth/login", json={"login": student_login, "password": student_password})
    check(r.status_code == 403, "tasdiqlanmagan talaba login = 403", str(r.status_code))

    r = client.post("/api/auth/register", json={
        "login": student_login, "password": student_password, "full_name": "Takror",
    })
    check(r.status_code == 400, "band login bilan register = 400", str(r.status_code))

    if application_id:
        r = client.post(f"/api/auth/applications/{application_id}/approve", headers=admin_headers)
        check(r.status_code == 200, "arizani tasdiqlash = 200", f"{r.status_code} {r.text[:200]}")

    r = client.post("/api/auth/login", json={"login": student_login, "password": student_password})
    if not check(r.status_code == 200, "tasdiqlangandan keyin login = 200", f"{r.status_code} {r.text[:200]}"):
        return _summary()
    student = r.json()["user"]
    student_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/api/auth/login", json={"login": student_login, "password": "notogri-parol"})
    check(r.status_code == 401, "noto'g'ri parol = 401", str(r.status_code))

    print("\n5. Rol cheklovlari")
    r = client.post("/api/topics/subjects", json={"title": f"Sinov fani {suffix}"},
                    headers=student_headers)
    check(r.status_code == 403, "talaba fan yarata olmaydi = 403", str(r.status_code))

    r = client.get("/api/auth/students", headers=student_headers)
    check(r.status_code == 403, "talaba talabalar ro'yxatini ko'ra olmaydi = 403", str(r.status_code))

    r = client.get("/api/auth/employees", headers=admin_headers)
    check(r.status_code in (200, 403), "GET /api/auth/employees ishlaydi", str(r.status_code))

    print("\n6. Talaba boshqa foydalanuvchi ma'lumotiga kira olmaydi")
    other_id = student["id"] + 99999
    r = client.get(f"/api/auth/students/{other_id}/overview", headers=student_headers)
    check(r.status_code == 403, "boshqa talaba overview = 403", str(r.status_code))
    r = client.get(f"/api/quiz/grades/{other_id}", headers=student_headers)
    check(r.status_code == 403, "boshqa talaba baholari = 403", str(r.status_code))

    print("\n7. Ilgari 500 bergan endpointlar")
    r = client.get("/api/topics/subjects", params={"user_id": student["id"]}, headers=student_headers)
    check(r.status_code == 200, "GET /api/topics/subjects?user_id= = 200 (ilgari 500)",
          f"{r.status_code} {r.text[:200]}")

    r = client.get("/api/quiz/report/pdf", params={"attempt_id": 999999999}, headers=admin_headers)
    check(r.status_code == 404, "mavjud bo'lmagan attempt PDF = 404 (ilgari 500)", str(r.status_code))

    r = client.get("/api/topics/999999999/pdf", headers=admin_headers)
    check(r.status_code == 404, "mavjud bo'lmagan mavzu PDF = 404 (ilgari 500)", str(r.status_code))

    print("\n8. Ilova chaqiradigan endpointlar mavjudligi")
    r = client.post("/api/quiz/report/pdf", headers=student_headers, json={
        "user_full_name": "Test Talaba",
        "topic_title": "Yurak anatomiyasi — Сердце",
        "results": [{
            "question": "Yurak ruscha qanday?",
            "options": {"A": "Сердце", "B": "Печень"},
            "correct_option": "A", "user_answer": "A", "is_correct": True,
            "explanation": "Сердце — yurak.",
        }],
        "score": 1, "total": 1,
    })
    check(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"),
          "POST /api/quiz/report/pdf = PDF (ilgari 405)", f"{r.status_code} {r.text[:120]}")

    for method, path in [
        ("GET", "/api/notifications"),
        ("GET", "/api/notifications/unread-count"),
        ("GET", "/api/announcements/"),
        ("GET", "/api/homework/"),
        ("GET", "/api/topics/"),
        ("GET", "/api/topics/dictionary"),
        ("GET", "/api/topics/schedules/all"),
        ("GET", "/api/auth/groups"),
        ("GET", "/api/auth/leaderboard"),
        ("GET", "/api/chat/contacts"),
        ("GET", f"/api/quiz/history/{student['id']}"),
        ("GET", f"/api/auth/students/{student['id']}/gamification"),
        ("GET", f"/api/auth/students/{student['id']}/academic-stats"),
        ("GET", f"/api/quiz/grades/{student['id']}"),
        ("GET", "/api/topics/arena/case"),
        ("GET", "/api/homework/submissions/my"),
    ]:
        r = client.request(method, path, headers=student_headers)
        check(r.status_code == 200, f"{method} {path} = 200", f"{r.status_code} {r.text[:120]}")

    print("\n9. Arena server tomonda baholaydi")
    r = client.get("/api/topics/arena/case", headers=student_headers)
    if r.status_code == 200:
        case = r.json()
        leaked = any(
            "correct_id" in stage or any("explanation" in o for o in stage.get("options", []))
            for stage in case.get("stages", [])
        )
        check(not leaked, "keys javoblari klientga sizmaydi")

    r = client.get("/api/topics/arena/duel", headers=student_headers)
    if check(r.status_code == 200, "GET /api/topics/arena/duel = 200", str(r.status_code)):
        duel = r.json()
        leaked = any("correct_option" in q for q in duel.get("questions", []))
        check(not leaked, "duel to'g'ri javoblari klientga sizmaydi")

        r = client.post("/api/topics/arena/duel/submit", headers=student_headers, json={
            "duel_id": duel["duel_id"],
            "answers": ["A"] * len(duel["questions"]),
            "score": 5, "is_winner": True,  # soxta qiymatlar — e'tiborga olinmasligi kerak
        })
        if check(r.status_code == 200, "duel submit = 200", f"{r.status_code} {r.text[:200]}"):
            body = r.json()
            check(body["correct_answers"] <= len(duel["questions"]),
                  "duel bali server tomonda hisoblandi",
                  f"correct={body['correct_answers']}")
            r2 = client.post("/api/topics/arena/duel/submit", headers=student_headers, json={
                "duel_id": duel["duel_id"], "answers": ["A"],
            })
            check(r2.status_code == 409, "duelni qayta topshirish = 409", str(r2.status_code))

    print("\n10. Chat qoidalari")
    r = client.post("/api/chat/send", headers=student_headers,
                    json={"recipient_id": student["id"], "message_text": "salom"})
    check(r.status_code == 400, "o'ziga xabar = 400", str(r.status_code))

    print("\n11. Parolni o'zgartirish")
    r = client.post("/api/auth/change-password", headers=student_headers,
                    json={"old_password": "notogri", "new_password": "YangiParol1"})
    check(r.status_code == 400, "noto'g'ri joriy parol = 400", str(r.status_code))
    r = client.post("/api/auth/change-password", headers=student_headers,
                    json={"old_password": student_password, "new_password": "YangiParol1"})
    check(r.status_code == 200, "parol o'zgartirildi = 200", f"{r.status_code} {r.text[:150]}")
    r = client.post("/api/auth/login", json={"login": student_login, "password": "YangiParol1"})
    check(r.status_code == 200, "yangi parol bilan login = 200", str(r.status_code))

    print("\n12. Profil bo'limlari")
    r = client.get("/api/profile/me", headers=student_headers)
    check(r.status_code == 200, "GET /api/profile/me = 200", str(r.status_code))

    r = client.patch("/api/profile/me", headers=student_headers, json={
        "phone_number": "+998911112233", "parent_name": "Karim Karimov",
    })
    check(r.status_code == 200
          and r.json()["profile"]["phone_number"] == "+998911112233",
          "shaxsiy ma'lumot yangilandi", f"{r.status_code} {r.text[:150]}")

    r = client.patch("/api/profile/me", headers=student_headers,
                     json={"department": "Kardiologiya"})
    check(r.status_code == 200 and not r.json()["profile"]["department"],
          "talaba kafedra maydonini o'zgartira olmaydi")

    r = client.get("/api/profile/me/settings", headers=student_headers)
    check(r.status_code == 200 and "notification_prefs" in r.json(),
          "sozlamalar olindi", f"{r.status_code} {r.text[:120]}")

    r = client.put("/api/profile/me/settings", headers=student_headers, json={
        "preferred_language": "ru",
        "notification_prefs": {"new_message": False, "soxta_kalit": True},
    })
    body = r.json() if r.status_code == 200 else {}
    check(r.status_code == 200
          and body.get("preferred_language") == "ru"
          and body.get("notification_prefs", {}).get("new_message") is False
          and "soxta_kalit" not in body.get("notification_prefs", {}),
          "sozlamalar saqlandi, noma'lum kalit rad etildi",
          f"{r.status_code} {r.text[:200]}")

    r = client.get("/api/profile/me/security", headers=student_headers)
    check(r.status_code == 200 and r.json().get("last_login"),
          "xavfsizlik: oxirgi kirish yozilgan", f"{r.status_code} {r.text[:150]}")

    print("\n13. Saqlanganlar")
    r = client.post("/api/profile/saved", headers=student_headers, json={
        "item_type": "term", "item_id": 999999, "title": "Сердце",
        "subtitle": "Yurak",
    })
    check(r.status_code == 201, "element saqlandi", f"{r.status_code} {r.text[:150]}")
    r = client.post("/api/profile/saved", headers=student_headers, json={
        "item_type": "term", "item_id": 999999, "title": "Сердце",
    })
    check(r.status_code in (200, 201) and r.json().get("status") == "exists",
          "takroriy saqlash xato bermaydi", f"{r.status_code} {r.text[:150]}")
    r = client.get("/api/profile/saved", headers=student_headers)
    check(r.status_code == 200 and len(r.json()) == 1, "saqlanganlar ro'yxati")
    r = client.delete("/api/profile/saved/term/999999", headers=student_headers)
    check(r.status_code == 200, "saqlangan element o'chirildi", str(r.status_code))

    print("\n14. Murojaatlar")
    r = client.post("/api/profile/requests", headers=student_headers, json={
        "request_type": "ma'lumotnoma", "subject": "Talabalik ma'lumotnomasi",
        "message": "Bankka taqdim etish uchun ma'lumotnoma kerak.",
    })
    check(r.status_code == 201, "murojaat yuborildi", f"{r.status_code} {r.text[:150]}")
    request_id = r.json()["request"]["id"] if r.status_code == 201 else None

    r = client.get("/api/profile/requests", headers=student_headers)
    check(r.status_code == 200 and len(r.json()) == 1, "talaba o'z murojaatini ko'radi")

    r = client.get("/api/profile/requests", headers=admin_headers)
    check(r.status_code == 200 and any(x["id"] == request_id for x in r.json()),
          "xodim barcha murojaatlarni ko'radi")

    r = client.get("/api/profile/requests/pending-count", headers=admin_headers)
    check(r.status_code == 200 and r.json()["count"] >= 1, "kutilayotgan murojaat soni")

    if request_id:
        r = client.post(f"/api/profile/requests/{request_id}/respond",
                        headers=student_headers, json={"status": "resolved"})
        check(r.status_code == 403, "talaba o'zi javob bera olmaydi", str(r.status_code))

        r = client.post(f"/api/profile/requests/{request_id}/respond",
                        headers=admin_headers,
                        json={"status": "resolved", "response": "Tayyor, dekanatdan oling."})
        check(r.status_code == 200 and r.json()["request"]["status"] == "resolved",
              "xodim javob berdi", f"{r.status_code} {r.text[:150]}")

        r = client.delete(f"/api/profile/requests/{request_id}", headers=student_headers)
        check(r.status_code == 409, "hal qilingan murojaatni talaba o'chira olmaydi",
              str(r.status_code))

    print("\n15. Yordam / FAQ")
    r = client.post("/api/profile/faq", headers=student_headers,
                    json={"question": "Sinov?", "answer": "Javob"})
    check(r.status_code == 403, "talaba FAQ qo'sha olmaydi", str(r.status_code))

    r = client.post("/api/profile/faq", headers=admin_headers, json={
        "category": "hisob", "question": "Parolni qanday almashtiraman?",
        "answer": "Profil > Xavfsizlik bo'limiga kiring.",
    })
    check(r.status_code == 201, "FAQ qo'shildi", f"{r.status_code} {r.text[:150]}")
    faq_id = r.json()["faq"]["id"] if r.status_code == 201 else None

    r = client.get("/api/profile/faq", headers=student_headers)
    check(r.status_code == 200 and len(r.json()) >= 1, "talaba FAQ ni ko'radi")
    if faq_id:
        r = client.delete(f"/api/profile/faq/{faq_id}", headers=admin_headers)
        check(r.status_code == 200, "FAQ o'chirildi", str(r.status_code))

    print("\n16. Professorlar")
    r = client.get("/api/auth/teachers", headers=student_headers)
    check(r.status_code == 200 and isinstance(r.json(), list),
          "talaba o'qituvchilar ro'yxatini oladi", f"{r.status_code} {r.text[:150]}")
    if r.status_code == 200 and r.json():
        leaked = any("password" in str(k).lower() for k in r.json()[0])
        check(not leaked, "o'qituvchi javobida parol yo'q")

    r = client.get("/api/auth/employees", headers=student_headers)
    check(r.status_code == 403, "talaba /employees ni ko'ra olmaydi", str(r.status_code))

    print("\n17. Tozalash")
    r = client.delete(f"/api/auth/students/{student['id']}", headers=admin_headers)
    check(r.status_code == 200, "test talabasi faolsizlantirildi", str(r.status_code))
    r = client.post("/api/auth/login", json={"login": student_login, "password": "YangiParol1"})
    check(r.status_code == 403, "faolsiz hisob kira olmaydi = 403", str(r.status_code))

    return _summary()


def _summary() -> int:
    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{'=' * 60}\nNatija: {passed}/{total} test o'tdi")
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
