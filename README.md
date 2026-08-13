# Ustoz AI — Backend

RUSMEDLANG tibbiyot talabalari uchun o'quv platformasi API'si.
FastAPI + SQLAlchemy (async) + PostgreSQL.

> **Diqqat:** Telegram bot olib tashlangan. Ro'yxatdan o'tish, kirish va barcha
> funksiyalar faqat mobil ilova orqali ishlaydi.

## Tez boshlash

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env       # va qiymatlarni to'ldiring
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY uchun

docker compose up -d             # PostgreSQL (ixtiyoriy)
alembic upgrade head             # sxemani yaratish/yangilash

SUPERADMIN_LOGIN=admin SUPERADMIN_PASSWORD='kuchli-parol' \
  python3 scripts/create_superadmin.py

uvicorn main:app --reload --port 8000
```

Hujjatlar: http://127.0.0.1:8000/docs • Holat: http://127.0.0.1:8000/health

## Muhit o'zgaruvchilari

`.env.example` faylida to'liq ro'yxat bor. Majburiylari:

| O'zgaruvchi | Izoh |
|---|---|
| `SECRET_KEY` | JWT imzo kaliti. **Bo'sh bo'lsa server ishga tushmaydi** (`DEBUG=true` dan tashqari). |
| `DATABASE_URL` | `postgresql://...` yoki `sqlite+aiosqlite:///./test.db` |
| `GROQ_API_KEY` | AI funksiyalari uchun (test generatsiya, tarjima, savol-javob) |
| `CORS_ORIGINS` | Vergul bilan ajratilgan ro'yxat. `*` bo'lsa credentials o'chadi. |

## Autentifikatsiya

Barcha endpointlar JWT talab qiladi (`Authorization: Bearer <token>`).
Istisno: `POST /api/auth/register`, `POST /api/auth/login`, `GET /health`, `GET /`.

Kirish oqimi:

```
Talaba /api/auth/register  ──►  ariza (pending)  ──►  403 "ko'rib chiqilmoqda"
Ustoz  /api/auth/applications/{id}/approve  ──►  User yaratiladi
Talaba /api/auth/login  ──►  JWT
```

Ustoz talabani to'g'ridan-to'g'ri ham yaratishi mumkin: `POST /api/auth/students`
(login + parol bilan; talabadan birinchi kirishda parolni almashtirish so'raladi).

Rollar: `student` < `employee` < `superadmin`. Yozish/o'chirish amallari
`employee`+ talab qiladi, xodimlarni boshqarish — `superadmin`.

## Migratsiyalar

```bash
alembic upgrade head                          # qo'llash
alembic revision -m "izoh" --autogenerate     # yangi migratsiya
alembic downgrade -1                          # orqaga
```

Migratsiyalar **himoyalangan**: mavjud jadval/ustunlarni tekshirib o'tadi,
shuning uchun ularni ishlab turgan bazada ham bemalol ishga tushirish mumkin.

### Eski bazadan o'tish

Bot davridagi foydalanuvchilarda login/parol yo'q — ular kira olmaydi.
Quyidagi skript ularga login va vaqtinchalik parol beradi:

```bash
python3 scripts/backfill_logins.py            # ko'rish (yozmaydi)
python3 scripts/backfill_logins.py --apply --csv parollar.csv
```

Ro'yxatni tarqatgach CSV faylni o'chiring. Har bir foydalanuvchidan birinchi
kirishda parolni almashtirish so'raladi (`must_change_password`).

## Skriptlar

| Skript | Vazifasi |
|---|---|
| `scripts/create_superadmin.py` | Superadmin yaratish / parolini yangilash |
| `scripts/backfill_logins.py` | Eski foydalanuvchilarga login+parol berish |
| `scripts/seed_subjects.py` | Namuna fanlar va mavzular |
| `scripts/seed_dictionary.py` | Tibbiy lug'at terminlari |
| `scripts/seed_faq.py` | Yordam bo'limi uchun savol-javoblar |
| `scripts/seed_demo_data.py` | Barcha jadvallar uchun demo ma'lumot (sinov va namoyish uchun) |
| `scripts/smoke_test.py` | Auth, ruxsatlar va asosiy oqimlar tekshiruvi |
| `scripts/e2e_test.py` | To'liq uchidan-uchiga tekshiruv: xodim va talabaning barcha oqimlari |
| `scripts/test_quiz_flow.py` | Test oqimi (AI'siz, offline) |

```bash
# Tekshiruvlar
python3 -m pyflakes app/ main.py
DATABASE_URL="sqlite+aiosqlite:///./_t.db" SECRET_KEY=test python3 scripts/test_quiz_flow.py
python3 scripts/smoke_test.py --admin-login admin --admin-password '...'
python3 scripts/e2e_test.py --admin-login admin --admin-password '...'
```

`e2e_test.py` fan/mavzu/material/jadval/lug'at/e'lon/vazifa/guruh CRUD, baholash,
chat, guruh chati, bildirishnomalar, arena, imtihon, profil, avatar, xodim
analitikasi, fayl yuklash cheklovlari va test oqimini bosib chiqadi
(182 ta tekshiruv). AI kaliti bo'lmasa AI'ga bog'liq qismlar o'tkazib yuboriladi.

## Imtihon rejimi (`/api/exam`)

Bir nechta mavzudan yig'ma test. Oddiy testdan farqi: vaqt cheklangan,
javoblar bittalab saqlanadi va imtihonni yarim yo'lda tashlab, keyin davom
ettirish mumkin.

| Endpoint | Vazifasi |
|---|---|
| `GET /active` | Tugallanmagan imtihon (bo'lsa) — ilova "davom ettirish" taklif qiladi |
| `POST /start` | `subject_id` yoki `topic_ids`, `question_count` (5–50), `duration_minutes` (0–180) |
| `GET /{id}` | Davom ettirish: savollar, saqlangan javoblar, qolgan vaqt |
| `POST /{id}/answer` | Bitta javobni saqlash |
| `POST /{id}/submit` | Yakunlash va natija |
| `GET /{id}/result` | Yakunlangan imtihon natijasi |
| `GET /{id}/report/pdf` | PDF hisobot |
| `GET /history` | Oldingi imtihonlar |

Muhim xatti-harakatlar:

- **Savollar avval bankdan olinadi.** Shu mavzular bo'yicha ilgari tuzilgan
  test/imtihon savollari qayta ishlatiladi (takrorlanmaydigan qilib), yetmasa
  yetishmagan qismi AI bilan mavzular bo'yicha **parallel** tuziladi. Shu
  sababli ikkinchi va keyingi imtihonlar deyarli bir zumda boshlanadi.
- **Variantlar aralashtiriladi** — bankdan olingan savolni talaba ilgari
  ko'rgan bo'lsa ham javob tartibi boshqacha bo'ladi.
- **Vaqt serverda hisoblanadi.** Klient yuborgan vaqtga ishonilmaydi; vaqt
  tugagach urinish `expired` bo'ladi, javoblar esa baholanadi.
- **Bir vaqtda bitta imtihon** — ochiq imtihon bo'lsa yangisi 409 beradi.
- To'g'ri javoblar imtihon davomida **klientga yuborilmaydi**.

## Xodim paneli uchun analitika

`GET /api/auth/analytics` (xodim+) panelga haqiqiy ko'rsatkichlarni beradi:

| Maydon | Izoh |
|---|---|
| `totals` | Talaba, fan, mavzu, jadval, kutilayotgan ariza va tekshirilmagan javoblar soni |
| `average_score` | Umumiy o'rtacha natija (5 ballik shkala) |
| `average_accuracy` | To'g'ri javoblar ulushi (%) |
| `trend` | Haftalik o'rtacha natija (sukut bo'yicha 7 hafta, `?weeks=` bilan o'zgaradi) |
| `top_students` | Eng yuqori aniqlikdagi 5 talaba |

## Profil bo'limlari (`/api/profile`)

Ilovadagi profil menyusi shu modul orqali ishlaydi:

| Endpoint | Vazifasi |
|---|---|
| `GET/PATCH /me` | Shaxsiy ma'lumotlar. Talaba `department`/`degree`/`bio` ni o'zgartira olmaydi. |
| `POST/DELETE /me/avatar` | Profil rasmi |
| `GET/PUT /me/settings` | Til (`uz`/`ru`) va bildirishnoma sozlamalari. Noma'lum kalitlar rad etiladi. |
| `GET /me/security` | Oxirgi kirish, oxirgi faollik, hisob yaratilgan sana |
| `GET/POST /saved`, `DELETE /saved/{type}/{id}` | Saqlangan mavzu / material / termin / e'lon |
| `GET/POST /requests` | Murojaatlar. Talaba o'zinikini, xodim hammasini ko'radi. |
| `POST /requests/{id}/respond` | Xodim javobi va holat (`pending`/`in_progress`/`resolved`/`rejected`) |
| `GET /requests/pending-count` | Xodim paneli uchun belgi |
| `GET/POST/PUT/DELETE /faq` | Yordam bo'limi. O'qish hammaga, tahrirlash xodimga. |

Bundan tashqari `GET /api/auth/teachers` — professorlar ro'yxati (har qanday
tizimga kirgan foydalanuvchi uchun; `/employees` dan farqli o'laroq faqat ochiq
profil maydonlari qaytariladi).

## Tuzilma

```
app/
  core/        config.py (env), security.py (JWT/parol/rollar), files.py (yuklash)
  api/         auth, topics, quiz, exam, attendance, homework, chat, arena,
               notifications,
               announcements, profile
               _shared.py — umumiy yordamchilar (sana, AI savollari, davomiylik)
  services/    ai_service.py (Groq/OpenAI, async), pdf_service.py
  models.py    SQLAlchemy modellari
  database.py  Async engine va sessiya
alembic/       Migratsiyalar
assets/fonts/  PDF uchun Unicode font (README ga qarang)
```

## Muhim xatti-harakatlar

- **Test baholash faqat serverda.** `POST /api/quiz/generate` urinish ochadi va
  savollarni **to'g'ri javobsiz** qaytaradi; `POST /api/quiz/submit` faqat
  tanlangan variantni qabul qiladi. Duel va klinik keys ham shunday.
- **Fayl yuklash:** faqat rasm/PDF, maksimal hajm `MAX_UPLOAD_BYTES`, fayl nomi
  har doim serverda generatsiya qilinadi.
- **Kunlik AI limiti:** `AI_QUESTION_DAILY_LIMIT` (Toshkent vaqti bo'yicha).
- **PDF fontlari:** kirill uchun `assets/fonts/README.md` ga qarang. Font
  topilmasa PDF baribir yaratiladi, lekin harflar `?` bilan almashadi.

## Demo ma'lumot

Bo'sh bazani sinov uchun to'ldirish (barcha 28 ta jadval):

```bash
python3 scripts/seed_demo_data.py              # baza manzilini ko'rsatib tasdiq so'raydi
python3 scripts/seed_demo_data.py --yes        # tasdiqsiz
python3 scripts/seed_demo_data.py --students 20 --yes
python3 scripts/seed_demo_data.py --suffix 2 --yes   # ikkinchi mustaqil to'plam
```

Skript **idempotent** — qayta ishga tushirilsa dublikat yaratmaydi va mavjud
ma'lumotga tegmaydi. Bazada superadmin bo'lsa, yangisi yaratilmaydi.

Yaratiladigan hisoblar (parol hammasida `Demo12345`): `demo.admin`,
`demo.ustoz1`, `demo.ustoz2`, `demo.talaba1` … `demo.talaba8`.
Guruhlar: `DEMO-101`, `DEMO-102`.

## Davomat (`/api/attendance`)

Davomat **har bir dars uchun** olinadi: sana + dars jadvalidagi juftlik. Shu
sababli fan kesimida foiz chiqadi va talaba aynan qaysi darsni qoldirganini
ko'radi.

| Endpoint | Kim | Vazifasi |
|---|---|---|
| `GET /lessons?date=&student_group=` | xodim | Shu kundagi darslar va belgilanish holati |
| `GET /roster?schedule_id=&date=` | xodim | Dars uchun talabalar va joriy holatlari |
| `POST /mark` | xodim | Yo'qlamani saqlash (bitta so'rovda) |
| `GET /group?student_group=&from=&to=` | xodim | Guruh hisoboti (talabalar × sanalar) |
| `GET /group/report/pdf` | xodim | Xuddi shu hisobot PDF sifatida |
| `GET /excuses`, `GET /excuses/pending-count` | xodim | Sabab so'rovlari navbati |
| `POST /excuses/{id}/review` | xodim | Sababni tasdiqlash / rad etish |
| `GET /my?from=&to=` | talaba | O'z davomati: xulosa va yozuvlar |
| `POST /excuses` | talaba | Qoldirilgan dars uchun sabab yuborish |
| `GET /summary/{student_id}` | ikkalasi | Fan kesimida foizlar |

Holatlar: `present` (keldi), `late` (kechikdi), `absent` (kelmadi),
`excused` (sababli).

Muhim xatti-harakatlar:

- **Foizga** `present`, `late` va `excused` "kelgan" deb hisoblanadi — sababli
  qoldirish talabani jazolamaydi.
- Kelajakdagi dars uchun yo'qlama qilib bo'lmaydi; sana jadvaldagi hafta kuniga
  mos kelishi shart.
- Talaba `absent`/`late` deb belgilansa unga bildirishnoma boradi
  (`attendance_absent`), sabab ko'rib chiqilgach — `excuse_reviewed`.
- Sabab tasdiqlansa holat avtomatik `excused` ga o'tadi.
- Davomat foizi `GET /api/auth/students/{id}/academic-stats` va
  `GET /api/auth/analytics` javoblariga ham qo'shiladi.
