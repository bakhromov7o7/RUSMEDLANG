import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import ClinicalArenaAttempt, User
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

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

# Request validation classes
class CaseSubmitRequest(BaseModel):
    student_id: int
    case_id: str
    selected_answers: List[str]  # e.g. ["A", "B", "A"]

class DuelSubmitRequest(BaseModel):
    student_id: int
    opponent_name: str
    score: int  # 0 to 5
    is_winner: bool

@router.get("/case")
async def get_daily_case():
    # Return first case (Cardiology) as daily case
    return CLINICAL_CASES["cardio_case"]

@router.post("/case/submit")
async def submit_case(req: CaseSubmitRequest, db: AsyncSession = Depends(get_db)):
    case = CLINICAL_CASES.get(req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Clinical case not found")
        
    stages = case["stages"]
    if len(req.selected_answers) != len(stages):
        raise HTTPException(status_code=400, detail="Selected answers count must match case stages count")
        
    correct_count = 0
    feedback_details = []
    
    for i, selected in enumerate(req.selected_answers):
        stage = stages[i]
        is_correct = selected == stage["correct_id"]
        if is_correct:
            correct_count += 1
            
        opt = next((o for o in stage["options"] if o["id"] == selected), None)
        explanation = opt["explanation"] if opt else "Noto'g'ri tanlov."
        feedback_details.append({
            "stage": stage["title"],
            "selected": selected,
            "correct": stage["correct_id"],
            "is_correct": is_correct,
            "explanation": explanation
        })
        
    # Calculate score
    score = int((correct_count / len(stages)) * 100)
    # Award 150 points for 100% score, proportional otherwise
    points_awarded = int((correct_count / len(stages)) * 150)
    
    # Save attempt
    attempt = ClinicalArenaAttempt(
        student_user_id=req.student_id,
        mode="case",
        scenario_or_opponent=case["title"],
        score=score,
        is_winner=correct_count == len(stages),
        points_awarded=points_awarded
    )
    db.add(attempt)
    await db.commit()
    
    return {
        "score": score,
        "points_awarded": points_awarded,
        "correct_answers": correct_count,
        "total_stages": len(stages),
        "details": feedback_details
    }

@router.get("/duel")
async def get_duel_questions():
    # Return 5 random/sliced questions for quiz battle
    import random
    questions = random.sample(DUEL_QUESTIONS, min(5, len(DUEL_QUESTIONS)))
    
    # Return virtual opponents list as options
    opponents = [
        {"name": "Anvar Smirnov", "avatar": "👨‍⚕️", "accuracy": 0.8},
        {"name": "Mariya Petrova", "avatar": "👩‍⚕️", "accuracy": 0.6},
        {"name": "Dilnoza Alieva", "avatar": "👩‍⚕️", "accuracy": 0.75}
    ]
    selected_opponent = random.choice(opponents)
    
    return {
        "opponent": selected_opponent,
        "questions": questions
    }

@router.post("/duel/submit")
async def submit_duel(req: DuelSubmitRequest, db: AsyncSession = Depends(get_db)):
    # Calculate points: 15 points per correct answer + 25 points bonus if winner
    points_awarded = (req.score * 15) + (25 if req.is_winner else 0)
    
    attempt = ClinicalArenaAttempt(
        student_user_id=req.student_id,
        mode="duel",
        scenario_or_opponent=req.opponent_name,
        score=int((req.score / 5) * 100),
        is_winner=req.is_winner,
        points_awarded=points_awarded
    )
    db.add(attempt)
    await db.commit()
    
    return {
        "status": "success",
        "points_awarded": points_awarded,
        "score": attempt.score,
        "is_winner": req.is_winner
    }
