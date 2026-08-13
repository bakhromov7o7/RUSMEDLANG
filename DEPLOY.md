# VPS'ga joylashtirish (deployment)

Ubuntu 22.04 / 24.04 uchun to'liq qo'llanma. Har bir qadam ketma-ket bajariladi.

Natijada: `https://api.sizning-domen.uz` manzilida HTTPS bilan ishlaydigan,
avtomatik qayta ishga tushadigan va kunlik zaxira olinadigan backend.

---

## 0. Nima kerak

| Talab | Izoh |
|---|---|
| VPS | 2 GB RAM, 2 vCPU yetarli (minimal 1 GB) |
| Domen | Masalan `api.sizning-domen.uz`, A-yozuv VPS IP ga qaratilgan |
| Groq API kaliti | AI funksiyalari uchun (https://console.groq.com) |

Bosh foydalanuvchi (`root`) o'rniga alohida foydalanuvchi ostida ishlaymiz.

---

## 1. Serverni tayyorlash

```bash
ssh root@SERVER_IP

apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx postgresql \
               postgresql-contrib ufw fail2ban

# Ilova uchun alohida foydalanuvchi (root ostida ishlatmaymiz)
adduser --system --group --home /opt/ustozai ustozai
```

### Xavfsizlik devori

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
ufw status
```

> Diqqat: `5432` (PostgreSQL) portini **tashqariga ochmang** — baza faqat
> shu serverning ichidan ishlatiladi.

---

## 2. PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE ustoz_ai;
CREATE USER ustozai WITH PASSWORD 'BU_YERGA_KUCHLI_PAROL';
GRANT ALL PRIVILEGES ON DATABASE ustoz_ai TO ustozai;
-- PostgreSQL 15+ da sxema huquqi ham kerak:
\c ustoz_ai
GRANT ALL ON SCHEMA public TO ustozai;
ALTER DATABASE ustoz_ai OWNER TO ustozai;
\q
```

Parolni generatsiya qilish:

```bash
openssl rand -base64 32
```

Tekshirish:

```bash
psql "postgresql://ustozai:PAROL@127.0.0.1:5432/ustoz_ai" -c "select version();"
```

---

## 3. Kodni joylashtirish

```bash
cd /opt
git clone git@github.com:bakhromov7o7/RUSMEDLANG.git ustozai-backend
chown -R ustozai:ustozai /opt/ustozai-backend
cd /opt/ustozai-backend

sudo -u ustozai python3 -m venv .venv
sudo -u ustozai .venv/bin/pip install --upgrade pip
sudo -u ustozai .venv/bin/pip install -r requirements.txt
```

---

## 4. Muhit o'zgaruvchilari

```bash
sudo -u ustozai nano /opt/ustozai-backend/.env
```

```ini
# === Majburiy ===
SECRET_KEY=BU_YERGA_GENERATSIYA_QILINGAN_KALIT
DATABASE_URL=postgresql://ustozai:PAROL@127.0.0.1:5432/ustoz_ai

# === AI ===
GROQ_API_KEY=gsk_...
# Limitga urilganda avtomatik almashish uchun zaxira kalit
# GROQ_API_KEY_2=gsk_...
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile
AI_TIMEOUT_SECONDS=60

# === Web ===
# Mobil ilova uchun "*" yetarli (cookie ishlatilmaydi, JWT header orqali keladi)
CORS_ORIGINS=*
DEBUG=false
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# === Fayl yuklash ===
UPLOAD_DIR=/opt/ustozai-backend/uploads
MAX_UPLOAD_BYTES=10485760

# === Biznes qoidalari ===
QUIZ_QUESTION_COUNT=5
AI_QUESTION_DAILY_LIMIT=10
TOPIC_CONTEXT_CHUNK_LIMIT=10
CHAT_PAGE_SIZE=100

# === Davomatda joylashuv nazorati ===
# O'quv binosining koordinatasi. Dars jadvalida alohida koordinata
# kiritilmagan bo'lsa shu ishlatiladi. Bo'sh qoldirilsa joylashuv
# tekshirilmaydi (holat "unknown"), hech kim jazolanmaydi.
CAMPUS_LATITUDE=41.311081
CAMPUS_LONGITUDE=69.240562
ATTENDANCE_RADIUS_METERS=150
```

> Koordinatani Google Maps'dan olish: kerakli nuqtaga o'ng tugma → birinchi
> qator (`41.311081, 69.240562`) — birinchi son kenglik, ikkinchisi uzunlik.
> Radius binoning kattaligi va GPS xatoligini qoplashi kerak — shahar sharoitida
> 100–200 metr amalda yaxshi ishlaydi.

`SECRET_KEY` ni generatsiya qilish:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Faylni himoyalash (parollar bor):

```bash
chmod 600 /opt/ustozai-backend/.env
chown ustozai:ustozai /opt/ustozai-backend/.env
```

> **Muhim:** `SECRET_KEY` o'zgartirilsa barcha foydalanuvchilar tizimdan
> chiqib ketadi (mavjud tokenlar yaroqsiz bo'ladi). Uni bir marta
> o'rnatib, keyin tegmang.

---

## 5. Migratsiyalar

Sxema **faqat alembic orqali** yaratiladi — qo'lda `CREATE TABLE` qilmang.

```bash
cd /opt/ustozai-backend
sudo -u ustozai .venv/bin/alembic upgrade head
```

Kutilayotgan natija:

```
Running upgrade  -> 0001_baseline
Running upgrade 0001_baseline -> 0002_auth_and_grading
Running upgrade 0002_auth_and_grading -> 0003_profile_features
Running upgrade 0003_profile_features -> 0004_exam_mode
Running upgrade 0004_exam_mode -> 0005_attendance
Running upgrade 0005_attendance -> 0006_attendance_location
```

### Migratsiyalar ro'yxati

| Revizioniya | Nima qiladi |
|---|---|
| `0001_baseline` | Asosiy jadvallar: foydalanuvchi, fan, mavzu, test, vazifa, chat |
| `0002_auth_and_grading` | Login/parol, server tomonda baholash, indeks va constraintlar |
| `0003_profile_features` | Til, bildirishnoma sozlamalari, saqlanganlar, murojaatlar, FAQ, avatar |
| `0004_exam_mode` | Imtihon rejimi: `exam_attempts`, `exam_questions` |
| `0005_attendance` | Davomat: `attendance_records` (yo'qlama va sabab so'rovlari) |
| `0006_attendance_location` | Joylashuv nazorati: `lesson_schedules` ga koordinata, `attendance_check_ins`, `location_violations` |

Barcha migratsiyalar **himoyalangan**: mavjud jadval/ustunni qayta yaratmaydi,
shuning uchun ishlab turgan bazada ham bemalol ishga tushirish mumkin.

Foydali buyruqlar:

```bash
sudo -u ustozai .venv/bin/alembic current       # hozirgi holat
sudo -u ustozai .venv/bin/alembic history       # tarix
sudo -u ustozai .venv/bin/alembic downgrade -1  # bitta orqaga qaytarish
```

### Superadmin yaratish

```bash
cd /opt/ustozai-backend
sudo -u ustozai env SUPERADMIN_LOGIN=admin \
     SUPERADMIN_PASSWORD='KUCHLI_PAROL' \
     SUPERADMIN_NAME='Ism Familiya' \
     .venv/bin/python scripts/create_superadmin.py
```

### Boshlang'ich ma'lumot (ixtiyoriy)

```bash
sudo -u ustozai .venv/bin/python scripts/seed_dictionary.py   # tibbiy lug'at
sudo -u ustozai .venv/bin/python scripts/seed_faq.py          # yordam savollari
```

---

## 6. systemd xizmati

```bash
nano /etc/systemd/system/ustozai.service
```

```ini
[Unit]
Description=Ustoz AI backend
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=ustozai
Group=ustozai
WorkingDirectory=/opt/ustozai-backend
EnvironmentFile=/opt/ustozai-backend/.env
ExecStart=/opt/ustozai-backend/.venv/bin/uvicorn main:app \
          --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers \
          --forwarded-allow-ips='127.0.0.1'
Restart=always
RestartSec=5

# Xavfsizlik cheklovlari
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ustozai-backend/uploads /opt/ustozai-backend/reports

[Install]
WantedBy=multi-user.target
```

```bash
mkdir -p /opt/ustozai-backend/{uploads,reports}
chown -R ustozai:ustozai /opt/ustozai-backend/{uploads,reports}

systemctl daemon-reload
systemctl enable --now ustozai
systemctl status ustozai
```

Tekshirish:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","database":"ok"}
```

> `--workers 2` — 2 GB RAM uchun mos. Har bir worker ~150-250 MB oladi.
> 4 GB da `--workers 4` qo'yish mumkin.

---

## 7. Nginx va HTTPS

```bash
nano /etc/nginx/sites-available/ustozai
```

```nginx
server {
    listen 80;
    server_name api.sizning-domen.uz;

    # Fayl yuklash chegarasi (.env dagi MAX_UPLOAD_BYTES bilan mos bo'lsin)
    client_max_body_size 12M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # AI javoblari uzoq davom etishi mumkin (test generatsiyasi)
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Yuklangan rasm va fayllar — to'g'ridan-to'g'ri nginx orqali
    location /uploads/ {
        alias /opt/ustozai-backend/uploads/;
        expires 30d;
        add_header Cache-Control "public";
        # Yuklangan fayl brauzerda bajarilmasin
        add_header X-Content-Type-Options nosniff;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/ustozai /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### Let's Encrypt sertifikati

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.sizning-domen.uz --agree-tos -m siz@pochta.uz --redirect
```

Certbot avtomatik yangilanishni o'zi sozlaydi. Tekshirish:

```bash
certbot renew --dry-run
```

Endi tekshiring:

```bash
curl https://api.sizning-domen.uz/health
```

---

## 8. Mobil ilovani serverga ulash

Ilova `API_BASE_URL` ni kompilyatsiya vaqtida oladi:

```bash
cd flutter

# Android
flutter build apk --release --split-per-abi \
  --dart-define=API_BASE_URL=https://api.sizning-domen.uz

# iOS
flutter build ipa --release \
  --dart-define=API_BASE_URL=https://api.sizning-domen.uz
```

Ko'rsatilmasa `lib/core/api_client.dart` dagi standart qiymat ishlatiladi.

---

## 9. Zaxira nusxa (backup)

Bazani kunlik zaxiralash:

```bash
mkdir -p /opt/backups && chown ustozai:ustozai /opt/backups
nano /opt/ustozai-backend/backup.sh
```

```bash
#!/bin/bash
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
export PGPASSWORD='BAZA_PAROLI'

# Baza
pg_dump -h 127.0.0.1 -U ustozai ustoz_ai | gzip > /opt/backups/db-$STAMP.sql.gz

# Yuklangan fayllar
tar czf /opt/backups/uploads-$STAMP.tar.gz -C /opt/ustozai-backend uploads

# 14 kundan eski nusxalarni o'chirish
find /opt/backups -name '*.gz' -mtime +14 -delete
```

```bash
chmod 700 /opt/ustozai-backend/backup.sh
chown ustozai:ustozai /opt/ustozai-backend/backup.sh

# Har kuni soat 03:00 da
crontab -u ustozai -e
```

```
0 3 * * * /opt/ustozai-backend/backup.sh >> /opt/backups/backup.log 2>&1
```

### Zaxiradan tiklash

```bash
systemctl stop ustozai
gunzip -c /opt/backups/db-20260813-0300.sql.gz | psql -h 127.0.0.1 -U ustozai ustoz_ai
systemctl start ustozai
```

---

## 10. Yangilanishni chiqarish

```bash
cd /opt/ustozai-backend

# 1. Zaxira (majburiy!)
./backup.sh

# 2. Yangi kod
sudo -u ustozai git pull

# 3. Yangi kutubxonalar (agar requirements.txt o'zgargan bo'lsa)
sudo -u ustozai .venv/bin/pip install -r requirements.txt

# 4. Migratsiyalar
sudo -u ustozai .venv/bin/alembic upgrade head

# 5. Qayta ishga tushirish
systemctl restart ustozai
systemctl status ustozai

# 6. Tekshirish
curl https://api.sizning-domen.uz/health
```

---

## 11. Kuzatuv va nosozliklar

```bash
# Jonli log
journalctl -u ustozai -f

# Oxirgi 100 qator
journalctl -u ustozai -n 100 --no-pager

# Faqat xatolar
journalctl -u ustozai -p err --since "1 hour ago"

# Nginx loglari
tail -f /var/log/nginx/error.log
```

### Tez-tez uchraydigan muammolar

| Belgi | Sabab va yechim |
|---|---|
| `502 Bad Gateway` | Xizmat o'chgan. `systemctl status ustozai`, `journalctl -u ustozai -n 50` |
| `SECRET_KEY o'rnatilmagan` | `.env` topilmadi yoki `EnvironmentFile` yo'li noto'g'ri |
| Login 401 beradi | `SECRET_KEY` o'zgartirilgan — eski tokenlar yaroqsiz, qayta kiring |
| Test 502/429 beradi | Groq kaliti tugagan yoki limitga urildi. `GROQ_API_KEY_2` qo'shing |
| Rasm ko'rinmayapti | `/uploads/` nginx yo'li yoki huquqlar. `ls -la /opt/ustozai-backend/uploads` |
| `413 Request Entity Too Large` | Nginx `client_max_body_size` ni oshiring |
| PDF da harflar `?` | Kirill fonti yo'q: `apt install fonts-dejavu` |

### Ishlayotganini tekshirish

Serverda:

```bash
cd /opt/ustozai-backend
sudo -u ustozai .venv/bin/python scripts/smoke_test.py \
  --base-url https://api.sizning-domen.uz \
  --admin-login admin --admin-password 'PAROL'
```

`72/72 test o'tdi` chiqishi kerak.

To'liq tekshiruv (test ma'lumot yaratadi va o'zi tozalaydi):

```bash
sudo -u ustozai .venv/bin/python scripts/e2e_test.py \
  --base-url https://api.sizning-domen.uz \
  --admin-login admin --admin-password 'PAROL'
```

`193/193 test o'tdi` chiqishi kerak.

---

## 12. Xavfsizlik bo'yicha eslatmalar

- `.env` faylini hech qachon git ga qo'shmang (`.gitignore` da bor).
- `DEBUG=false` bo'lsin — aks holda xato tafsilotlari tashqariga chiqadi.
- PostgreSQL porti tashqariga ochilmasin.
- SSH uchun parol o'rniga kalit ishlating:
  `PasswordAuthentication no` (`/etc/ssh/sshd_config`).
- Superadmin parolini kuchli qiling — u barcha ma'lumotga kirish huquqiga ega.
- Serverni muntazam yangilab turing: `apt update && apt upgrade`.
