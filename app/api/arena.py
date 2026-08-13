import logging
import random
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import iso, tashkent_date, tashkent_day_start_utc
from app.core.security import get_current_user
from app.database import get_db
from app.models import ClinicalArenaAttempt, User, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=True)

# 1. Daily Clinical Cases Data (Cardiology, Neurology, Pulmonology)
CLINICAL_CASES = {
    "cardio_case": {
        "id": "cardio_case",
        "subject": "Kardiologiya",
        "title": "Ko'krak qafasidagi to'satdan o'tkir og'riq",
        "patient_name": "Smirnov Ivan (62 yosh)",
        "vitals_start": "Pulse: 96 bpm, BP: 145/90 mmHg, Temp: 36.8°C",
        "description": "Bemor Smirnov Ivan, 62 yosh. To'satdan ko'krak qafasi ortida paydo bo'lgan kuchli va siquvchi og'riq shikoyati bilan murojaat qildi. Og'riq chap yelka va chap qo'lga tarqalayotganini aytmoqda. Nafas qisilishi kuzatilmoqda.",
        "stages": [
            {
                "index": 1,
                "title": "1-bosqich: Anamnez yig'ish (Symptom check)",
                "question": "Bemor holatini aniqlash uchun unga rus tilida qaysi savolni berish to'g'ri hisoblanadi?",
                "options": [
                    {"id": "A", "text": "Как долго продолжается эта боль и проходит ли она после нитроглицерина?", "explanation": "To'g'ri! Stenokardiya yoki infarktni ajratish uchun og'riq davomiyligi va nitratlarga javobi eng muhim savoldir."},
                    {"id": "B", "text": "Что вы ели сегодня на обед и есть ли тошнота?", "explanation": "Noto'g'ri. Garchi ba'zan oshqozon-ichak xastaliklari ko'krak og'rig'iga o'xshasa-da, bu kardiologik holatda birlamchi emas."},
                    {"id": "C", "text": "Какая у вас температура тела обычно по вечерам?", "explanation": "Noto'g'ri. Harorat ko'tarilishi surunkali yallig'lanish uchun muhim, ammo o'tkir kardial og'riqda asosiy savol emas."},
                    {"id": "D", "text": "Были ли у вас травмы позвоночника в детстве?", "explanation": "Noto'g'ri. Umurtqa pog'onasi travmasi radikulopatiyaga sabab bo'lsa-da, hozirgi o'tkir simptomlarga aloqasi yo'q."}
                ],
                "correct_id": "A"
            },
            {
                "index": 2,
                "title": "2-bosqich: Tashxis qo'yish (Diagnostic investigation)",
                "question": "EKG tahlili shuni ko'rsatdiki: V1-V4 tarmoqlarda ST segmenti ko'tarilgan (ST elevation). Qaysi dastlabki tashxis eng to'g'ri keladi?",
                "options": [
                    {"id": "A", "text": "Острый инфаркт миокарда передней стенки (ST-elevation)", "explanation": "To'g'ri! V1-V4 tarmoqlarda ST ko'tarilishi oldingi devor o'tkir infarktining klassik belgisidir."},
                    {"id": "B", "text": "Межреберная невралгия", "explanation": "Noto'g'ri. Qovurg'alararo nevralgiya EKGda ST segmenti ko'tarilishiga olib kelmaydi."},
                    {"id": "C", "text": "Острый панкреатит", "explanation": "Noto'g'ri. Pankreatit EKGda bunday o'zgarish bermaydi, u qorin sohasida og'riq bilan kechadi."},
                    {"id": "D", "text": "Стабильная стенокардия напряжения", "explanation": "Noto'g'ri. Stabil stenokardiyada tinch holatdagi EKG normal yoki ST depressiyasi bilan kechadi, ko'tarilish kuzatilmaydi."}
                ],
                "correct_id": "A"
            },
            {
                "index": 3,
                "title": "3-bosqich: Davolash va dorilar (Treatment & Prescription)",
                "question": "O'tkir miokard infarkti (STEMI) tasdiqlanganda, zudlik bilan qilinadigan terapiya va retsept formulasi qanday bo'lishi kerak?",
                "options": [
                    {"id": "A", "text": "Антиагрегантная терапия (Аспирин 300 мг разжевать) + тромболизис/ЧКВ", "explanation": "To'g'ri! Aspirin yuklama dozasi va zudlik bilan revaskulyarizatsiya (trombolizis yoki koronar angioplastika) standart davodir."},
                    {"id": "B", "text": "Принять Ибупрофен 400 мг и пойти спать", "explanation": "Noto'g'ri va o'ta xavfli! NSAID preparatlari infarktda yordam bermaydi va ahvolni og'irlashtiradi."},
                    {"id": "C", "text": "Внутримышечно ввести Но-шпу (Дротаверин) для снятия спазма", "explanation": "Noto'g'ri. Spazmolitiklar yirik koronar arteriya trombozida foydasizdir."},
                    {"id": "D", "text": "Назначить антибиотики широкого спектра действия", "explanation": "Noto'g'ri. Infarkt yuqumli kasallik emas, antibiotiklar bu yerda qo'llanilmaydi."}
                ],
                "correct_id": "A"
            }
        ]
    },
    "neuro_case": {
        "id": "neuro_case",
        "subject": "Nevrologiya",
        "title": "To'satdan yuz asimmetriyasi va nutq buzilishi",
        "patient_name": "Petrova Mariya (55 yosh)",
        "vitals_start": "Pulse: 84 bpm, BP: 170/100 mmHg, Temp: 36.6°C",
        "description": "Bemor Petrova Mariya, 55 yosh. Yaqinlari bemorning to'satdan gapirishi qiyinlashgani, o'ng qo'l va oyog'i zaiflashgani, yuzining o'ng tomoni qiyshayib qolgani (asimmetriya) sababli tez yordam chaqirishdi.",
        "stages": [
            {
                "index": 1,
                "title": "1-bosqich: Anamnez yig'ish (Symptom check)",
                "question": "Insult gumon qilinganda, rus tilida bemorning nevrologik holatini tekshirish uchun qaysi tezkor so'rov beriladi?",
                "options": [
                    {"id": "A", "text": "Попробуйте улыбнуться, поднять обе руки и назвать свое имя.", "explanation": "To'g'ri! Bu tezkor insultni aniqlash FAST (Face, Arm, Speech, Time) testining ruscha ko'rinishidir."},
                    {"id": "B", "text": "Когда вы в последний раз проверяли зрение?", "explanation": "Noto'g'ri. Ko'rish o'tkirligi muhim bo'lsa-da, o'tkir insultda birlamchi diagnostika hisoblanmaydi."},
                    {"id": "C", "text": "Есть ли у вас боль при повороте шеи?", "explanation": "Noto'g'ri. Bu osteoxondroz uchun xos, o'tkir fokal nevrologik defitsitga aloqador emas."},
                    {"id": "D", "text": "Сколько часов вы спали сегодня ночью?", "explanation": "Noto'g'ri. Uyqu yetishmasligi charchoq berishi mumkin, ammo yuz qiyshayishi yoki gemiparez keltirib chiqarmaydi."}
                ],
                "correct_id": "A"
            },
            {
                "index": 2,
                "title": "2-bosqich: Tashxis qo'yish (Diagnostic investigation)",
                "question": "KT (Kompter tomografiya) tekshiruvida miya qon ketishi (hemorrhage) aniqlanmadi. Simptomlar boshlanganiga 2 soat bo'lgan. Tashxis qanday?",
                "options": [
                    {"id": "A", "text": "Острый ишемический инсульт в терапевтическом окне", "explanation": "To'g'ri! KTda gemorragiyaning yo'qligi va o'tkir boshlanishi - ishemik insultni bildiradi. 4.5 soatgacha bo'lgan davr esa trombolizis oynasidir."},
                    {"id": "B", "text": "Геморрагический инсульт", "explanation": "Noto'g'ri. Agar qon ketish bo'lganda KT tasvirida giperdens (yorqin) qon o'choqlari ko'ringan bo'lardi."},
                    {"id": "C", "text": "Мигрень с аурой", "explanation": "Noto'g'ri. Migren aurasida gemiparez yoki yuz asimmetriyasi to'satdan turg'un saqlanmaydi."},
                    {"id": "D", "text": "Остеохондроз шейного отдела", "explanation": "Noto'g'ri. Bo'yin osteoxondrozi gemiparez yoki o'tkir afaziyaga sabab bo'lmaydi."}
                ],
                "correct_id": "A"
            },
            {
                "index": 3,
                "title": "3-bosqich: Davolash va dorilar (Treatment & Prescription)",
                "question": "Ishemik insult terapevtik oyna (trombolitik davolash oynasi) ichida bo'lsa, qanday davo choralari buyuriladi?",
                "options": [
                    {"id": "A", "text": "Тромболитическая терапия (Альтеплаза в/в) для растворения тромба", "explanation": "To'g'ri! 4.5 soatlik oyna ichida o'tkir ishemik insultda trombolizis (Alteplaza) o'choqli asoratlarni keskin kamaytiradi."},
                    {"id": "B", "text": "Назначить постельный режим и Анальгин для купирования боли", "explanation": "Noto'g'ri. Oddiy og'riqsizlantirish insultni davolamaydi."},
                    {"id": "C", "text": "Снизить артериальное давление до 100/60 mmHg с помощью мочегонных", "explanation": "Xavfli xato! Insult o'tkir davrida qon bosimini keskin tushirish perfuziyani battar yomonlashtiradi va miya nekrozini oshiradi."},
                    {"id": "D", "text": "Срочное хирургическое шунтирование артерий", "explanation": "Noto'g'ri. Koronar shuntlash yurak uchun, insultning o'tkir davrida esa zudlik bilan trombolizis qilinadi."}
                ],
                "correct_id": "A"
            }
        ]
    }
}

# 2. Mock Quiz Battle Questions Generator (Anatomy, Cardiology, Physiology)
DUEL_QUESTIONS = [
    {
        "question": "Rus tilida yurakning o'ng bo'lmasi qanday nomlanadi?",
        "options": {"A": "Правое предсердие", "B": "Правый желудочек", "C": "Левое предсердие", "D": "Левый желудочек"},
        "correct_option": "A",
        "explanation": "Правое предсердие - o'ng bo'lma, правый желудочек - o'ng qorincha degani."
    },
    {
        "question": "Lotincha 'Cor' so'zining ruscha tarjimasi nima?",
        "options": {"A": "Мозг", "B": "Сердце", "C": "Печень", "D": "Легкие"},
        "correct_option": "B",
        "explanation": "'Cor' lotin tilida yurak (ruscha: Сердце) degan ma'noni anglatadi."
    },
    {
        "question": "Qon bosimi rus tilida qanday nomlanadi?",
        "options": {"A": "Пульс", "B": "Дыхание", "C": "Артериальное давление", "D": "Температура"},
        "correct_option": "C",
        "explanation": "Qon bosimi - Артериальное давление (AD) deb ataladi."
    },
    {
        "question": "Bemorning shikoyatlarini rus tilida so'rash uchun qaysi ibora to'g'ri keladi?",
        "options": {"A": "Где вы живете?", "B": "На что вы жалуетесь?", "C": "Как вас зовут?", "D": "Сколько вам лет?"},
        "correct_option": "B",
        "explanation": "'На что вы жалуетесь?' iborasi 'Nimalardan shikoyat qilasiz?' degan ma'noni beradi."
    },
    {
        "question": "Nafas qisilishi (dyshnea) rus tilida nima deyiladi?",
        "options": {"A": "Кашель", "B": "Одышка", "C": "Насморк", "D": "Лихорадка"},
        "correct_option": "B",
        "explanation": "Nafas qisilishi - Одышка deb ataladi. Кашель - yo'tal, лихорадка - isitma."
    },
    {
        "question": "Dorini til ostiga qo'yish farmakologiyada ruscha qanday aytiladi?",
        "options": {"A": "Внутривенно", "B": "Под язык (сублингвально)", "C": "Внутримышечно", "D": "Перорально"},
        "correct_option": "B",
        "explanation": "Til ostiga qo'yish - Под язык (sublingual) deb tarjima qilinadi."
    },
    {
        "question": "Miya faoliyatini o'rganish uchun ishlatiladigan EKGga o'xshash tekshiruv?",
        "options": {"A": "ЭхоКГ", "B": "ЭЭГ (Электроэнцефалография)", "C": "УЗИ", "D": "МРТ"},
        "correct_option": "B",
        "explanation": "EEG miya bioelektr faolligini o'rganish uchun xizmat qiladi."
    }
]

DUEL_SIZE = 5
OPPONENTS = [
    {"name": "Anvar Smirnov", "avatar": "👨‍⚕️", "accuracy": 0.8},
    {"name": "Mariya Petrova", "avatar": "👩‍⚕️", "accuracy": 0.6},
    {"name": "Dilnoza Alieva", "avatar": "👩‍⚕️", "accuracy": 0.75},
]


# ---------------------------------------------------------------------------
# So'rov sxemalari
# ---------------------------------------------------------------------------

class CaseSubmitRequest(BaseModel):
    case_id: str = Field(..., max_length=100)
    selected_answers: List[str] = Field(..., min_length=1, max_length=20)
    student_id: Optional[int] = None  # e'tiborsiz — tokendan olinadi


class DuelSubmitRequest(BaseModel):
    duel_id: int
    # Har bir savol uchun tanlangan variant ("A".."D") yoki bo'sh.
    answers: List[Optional[str]] = Field(default_factory=list, max_length=20)
    student_id: Optional[int] = None
    opponent_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Klinik keys
# ---------------------------------------------------------------------------

def _public_case(case: dict) -> dict:
    """To'g'ri javob va izohlarsiz nusxa.

    Ilgari `correct_id` va har bir variantning izohi klientga yuborilardi —
    talaba javobni ko'rib turardi.
    """
    return {
        "id": case["id"],
        "subject": case["subject"],
        "title": case["title"],
        "patient_name": case["patient_name"],
        "vitals_start": case["vitals_start"],
        "description": case["description"],
        "stages": [
            {
                "index": stage["index"],
                "title": stage["title"],
                "question": stage["question"],
                "options": [
                    {"id": opt["id"], "text": opt["text"]} for opt in stage["options"]
                ],
            }
            for stage in case["stages"]
        ],
    }


@router.get("/case")
async def get_daily_case(_user: User = Depends(get_current_user)):
    """Kunlik klinik keys.

    Ilgari har doim `cardio_case` qaytarilardi va qolgan keyslar umuman
    ko'rinmasdi. Endi Toshkent sanasi bo'yicha navbat bilan almashadi —
    kun davomida barcha talabalar bir xil keysni ko'radi.
    """
    keys = sorted(CLINICAL_CASES)
    today = tashkent_date(utcnow())
    index = today.toordinal() % len(keys) if today else 0
    return _public_case(CLINICAL_CASES[keys[index]])


async def _already_scored_today(db: AsyncSession, student_id: int, mode: str) -> bool:
    """Bugun shu rejimda ball olinganmi (kuniga bir marta)."""
    day_start = tashkent_day_start_utc()
    count = (
        await db.execute(
            select(func.count(ClinicalArenaAttempt.id)).where(
                ClinicalArenaAttempt.student_user_id == student_id,
                ClinicalArenaAttempt.mode == mode,
                ClinicalArenaAttempt.status == "finished",
                ClinicalArenaAttempt.points_awarded > 0,
                ClinicalArenaAttempt.created_at >= day_start,
            )
        )
    ).scalar() or 0
    return count > 0


@router.post("/case/submit")
async def submit_case(
    req: CaseSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = CLINICAL_CASES.get(req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Klinik keys topilmadi")

    stages = case["stages"]
    if len(req.selected_answers) != len(stages):
        raise HTTPException(
            status_code=400, detail="Javoblar soni bosqichlar soniga teng bo'lishi kerak"
        )

    correct_count = 0
    details = []
    for index, selected in enumerate(req.selected_answers):
        stage = stages[index]
        choice = (selected or "").strip().upper()
        is_correct = choice == stage["correct_id"]
        if is_correct:
            correct_count += 1

        option = next((o for o in stage["options"] if o["id"] == choice), None)
        details.append({
            "stage": stage["title"],
            "selected": choice or None,
            "correct": stage["correct_id"],
            "is_correct": is_correct,
            "explanation": option["explanation"] if option else "Javob tanlanmadi.",
        })

    score = int(correct_count / len(stages) * 100)
    # Ball kuniga bir marta beriladi — takroriy yechishda 0.
    repeat = await _already_scored_today(db, current_user.id, "case")
    points_awarded = 0 if repeat else int(correct_count / len(stages) * 150)

    attempt = ClinicalArenaAttempt(
        student_user_id=current_user.id,
        mode="case",
        status="finished",
        scenario_or_opponent=case["title"],
        score=score,
        is_winner=correct_count == len(stages),
        points_awarded=points_awarded,
        finished_at=utcnow(),
    )
    db.add(attempt)
    await db.commit()

    return {
        "score": score,
        "points_awarded": points_awarded,
        "points_skipped_reason": "Bugun ball allaqachon olingan" if repeat else None,
        "correct_answers": correct_count,
        "total_stages": len(stages),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Duel (tezkor test jangi)
# ---------------------------------------------------------------------------

@router.get("/duel")
async def get_duel_questions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Duelni ochadi va savollarni to'g'ri javobsiz qaytaradi.

    Berilgan savollar indeksi bazada saqlanadi — submit'da server aynan shu
    savollar bo'yicha baholaydi, natija klientdan qabul qilinmaydi.
    """
    indexes = random.sample(range(len(DUEL_QUESTIONS)), min(DUEL_SIZE, len(DUEL_QUESTIONS)))
    opponent = random.choice(OPPONENTS)

    attempt = ClinicalArenaAttempt(
        student_user_id=current_user.id,
        mode="duel",
        status="issued",
        scenario_or_opponent=opponent["name"],
        issued_payload={"question_indexes": indexes, "opponent": opponent},
        score=0,
        is_winner=False,
        points_awarded=0,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    return {
        "duel_id": attempt.id,
        "opponent": opponent,
        "questions": [
            {
                "index": position,
                "question": DUEL_QUESTIONS[i]["question"],
                "options": DUEL_QUESTIONS[i]["options"],
            }
            for position, i in enumerate(indexes)
        ],
    }


@router.post("/duel/submit")
async def submit_duel(
    req: DuelSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = (
        await db.execute(
            select(ClinicalArenaAttempt).where(ClinicalArenaAttempt.id == req.duel_id)
        )
    ).scalar_one_or_none()
    if not attempt or attempt.mode != "duel":
        raise HTTPException(status_code=404, detail="Duel topilmadi")
    if attempt.student_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu duel sizga tegishli emas")
    if attempt.status != "issued":
        raise HTTPException(status_code=409, detail="Bu duel allaqachon yakunlangan")

    payload = attempt.issued_payload or {}
    indexes = payload.get("question_indexes") or []
    opponent = payload.get("opponent") or {}

    correct_count = 0
    details = []
    for position, question_index in enumerate(indexes):
        question = DUEL_QUESTIONS[question_index]
        choice = (req.answers[position] or "").strip().upper() if position < len(req.answers) else ""
        is_correct = choice == question["correct_option"]
        if is_correct:
            correct_count += 1
        details.append({
            "question": question["question"],
            "options": question["options"],
            "selected": choice or None,
            "correct_option": question["correct_option"],
            "is_correct": is_correct,
            "explanation": question["explanation"],
        })

    total = len(indexes) or 1
    # Raqib natijasi uning "aniqligi" asosida hisoblanadi.
    opponent_correct = round(float(opponent.get("accuracy", 0.7)) * total)
    is_winner = correct_count > opponent_correct

    repeat = await _already_scored_today(db, current_user.id, "duel")
    points_awarded = 0 if repeat else (correct_count * 15) + (25 if is_winner else 0)

    attempt.status = "finished"
    attempt.score = int(correct_count / total * 100)
    attempt.is_winner = is_winner
    attempt.points_awarded = points_awarded
    attempt.finished_at = utcnow()
    await db.commit()

    return {
        "status": "success",
        "duel_id": attempt.id,
        "score": attempt.score,
        "correct_answers": correct_count,
        "total_questions": total,
        "opponent_correct": opponent_correct,
        "is_winner": is_winner,
        "points_awarded": points_awarded,
        "points_skipped_reason": "Bugun ball allaqachon olingan" if repeat else None,
        "details": details,
    }


@router.get("/history")
async def arena_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ClinicalArenaAttempt)
            .where(
                ClinicalArenaAttempt.student_user_id == current_user.id,
                ClinicalArenaAttempt.status == "finished",
            )
            .order_by(ClinicalArenaAttempt.created_at.desc())
            .limit(100)
        )
    ).scalars().all()

    return [
        {
            "id": r.id,
            "mode": r.mode,
            "scenario_or_opponent": r.scenario_or_opponent,
            "score": r.score,
            "is_winner": r.is_winner,
            "points_awarded": r.points_awarded,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]
