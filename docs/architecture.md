# Ustoz AI arxitekturasi

## 1. Asosiy prinsip

Katta video fayllarni o'z DB'ingizga saqlamaysiz. Telegramning o'zi storage bo'lib xizmat qiladi.

Bot video qabul qilganda quyidagilarni olib saqlaydi:

- `telegram_file_id`
- `telegram_file_unique_id`
- `source_chat_id`
- `source_message_id`

Keyin studentga video yuborishda:

- `sendVideo(file_id)` ishlatish mumkin
- yoki kerak bo'lsa `copyMessage(from_chat_id, message_id)` ishlatish mumkin

Eng to'g'ri yo'l: `file_id`ni asosiy reference sifatida saqlash.

## 2. Nega to'g'ridan-to'g'ri training emas?

Har safar employee yuborgan material bilan modelni train qilish qimmat va murakkab bo'ladi. Amaliy variant:

- materialni transcript yoki text ko'rinishiga o'tkazish
- kerakli bo'laklarga ajratish
- student tanlagan mavzu bo'yicha shu bo'laklarni AIga context qilib berish

Bu usul `RAG`ga yaqin yondashuv bo'lib, aynan sizga kerak bo'lgan cheklovni beradi.

## 3. Mavzu bo'yicha cheklangan javob

Student mavzu tanlaganidan keyin session ochiladi:

- `student_user_id`
- `topic_id`
- `state = asking`

Har student savolida backend quyidagicha ishlaydi:

1. active `topic_id`ni topadi
2. shu topicga tegishli `knowledge_chunks`ni oladi
3. AIga instruction beradi:
   `Faqat tanlangan mavzu bo'yicha javob ber. Agar savol mavzuga tegishli bo'lmasa, foydalanuvchini mavzuga qaytar.`
4. AI javobini studentga qaytaradi

## 4. Quiz yaratish

Quiz 2 xil usulda bo'lishi mumkin:

### Variant A: oldindan saqlangan savollar

Afzalligi:

- nazorat oson
- bir xil daraja
- AI xatosi kamroq

### Variant B: AI shu mavzu bo'yicha 5 ta savol generatsiya qiladi

Afzalligi:

- avtomatik
- har safar boshqa savol

Boshlanish uchun tavsiya:

- AI savol yaratsin
- employee keyin xohlasa manual savollar qo'shish imkonini ham qo'shing

## 5. Employeega natija yuborish

Quiz tugagandan keyin:

1. `quiz_attempts` update bo'ladi
2. `correct_answers` hisoblanadi
3. employeega Telegram xabar yuboriladi

Xabar namunasi:

```text
Student: Ali Valiyev
Mavzu: Python asoslari
Natija: 5 tadan 4 tasi to'g'ri
Vaqt: 2026-04-03 19:00
```

## 6. Tavsiya etilgan backend modullar

Minimal bo'linish:

- `auth/roles`
- `topics`
- `materials`
- `ai`
- `quiz`
- `reports`
- `telegram`

## 7. Birinchi versiya uchun eng sodda MVP

MVP ichida quyidagilar yetadi:

1. superadmin employee ochadi
2. employee student ochadi
3. employee topic yaratadi
4. employee video yuboradi
5. bot `file_id`ni DBga yozadi
6. employee text yuboradi
7. text `knowledge_chunks`ga ajratiladi
8. student topic tanlaydi
9. bot video'ni `file_id` bilan yuboradi
10. student savol beradi
11. AI faqat shu topic context bilan javob beradi
12. quiz boshlanadi
13. natija employeega yuboriladi

## 8. Qisqa xulosa

Sizning video muammo uchun yechim tayyor:

- video'ni DBga emas Telegramga qoldiring
- DBda faqat `file_id` va metadata saqlang
- AI uchun `training` emas, topic-based retrieval ishlating

Shu model sizning bot uchun eng yengil va real ishlaydigan variant bo'ladi.
