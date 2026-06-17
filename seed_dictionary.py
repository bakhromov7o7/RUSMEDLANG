import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import MedicalTerm

terms_data = [
    {
        "word": "Сердце",
        "transcription": "[с`эрдцэ]",
        "gender": "ср.р. (neuter)",
        "translation": "Yurak",
        "category": "Anatomiya",
        "description": "Tana a'zolarini qon bilan ta'minlovchi markaziy mushak a'zosi.",
        "example_ru": "У пациента наблюдается учащённое сердцебиение.",
        "example_uz": "Bemorning yurak urishi tezlashishi kuzatilmoqda."
    },
    {
        "word": "Печень",
        "transcription": "[п`эчэн']",
        "gender": "жен.р. (feminine)",
        "translation": "Jigar",
        "category": "Anatomiya",
        "description": "Moddalar almashinuvida ishtirok etuvchi eng katta bez.",
        "example_ru": "Печень играет важную роль в детоксикации организма.",
        "example_uz": "Jigar organizmni toksinlardan tozalashda muhim rol o'ynaydi."
    },
    {
        "word": "Лёгкие",
        "transcription": "[л'`охкии]",
        "gender": "мн.ч. (plural)",
        "translation": "O'pka",
        "category": "Anatomiya",
        "description": "Nafas olish tizimining asosiy a'zosi.",
        "example_ru": "Рентген лёгких не выявил воспалительных процессов.",
        "example_uz": "O'pka rentgeni yallig'lanish jarayonlarini aniqlamadi."
    },
    {
        "word": "Давление",
        "transcription": "[давл`энии]",
        "gender": "ср.р. (neuter)",
        "translation": "Qon bosimi",
        "category": "Kardiologiya",
        "description": "Qon tomirlari devoridagi bosim darajasi.",
        "example_ru": "Необходимо измерять артериальное давление дважды в день.",
        "example_uz": "Arterial qon bosimini kuniga ikki marta o'lchash zarur."
    },
    {
        "word": "Одышка",
        "transcription": "[ад`ышка]",
        "gender": "жен.р. (feminine)",
        "translation": "Harsillash / Nafas qisishi",
        "category": "Kardiologiya",
        "description": "Nafas olish chastotasi va chuqurligining buzilishi.",
        "example_ru": "При физической нагрузке у больного появляется одышка.",
        "example_uz": "Jismoniy yuklama paytida bemorda nafas qisishi paydo bo'ladi."
    },
    {
        "word": "Воспаление",
        "transcription": "[васпал`ении]",
        "gender": "ср.р. (neuter)",
        "translation": "Yallig'lanish",
        "category": "Terapiya",
        "description": "Patogen ta'sirga qarshi organizmning himoya reaksiyasi.",
        "example_ru": "Аспирин помогает снять воспаление и уменьшить боль.",
        "example_uz": "Aspirin yallig'lanishni bartaraf etishga va og'riqni kamaytirishga yordam beradi."
    },
    {
        "word": "Желудок",
        "transcription": "[жыл`удак]",
        "gender": "муж.р. (masculine)",
        "translation": "Oshqozon",
        "category": "Anatomiya",
        "description": "Hazm qilish tizimining kengaygan qismi.",
        "example_ru": "После еды возникла резкая боль в желудке.",
        "example_uz": "Ovqatlangandan so'ng oshqozonda o'tkir og'riq paydo bo'ldi."
    },
    {
        "word": "Позвоночник",
        "transcription": "[пазван`очник]",
        "gender": "муж.р. (masculine)",
        "translation": "Umurtqa pog'onasi",
        "category": "Anatomiya",
        "description": "Tananing tayanch va harakat o'qi.",
        "example_ru": "Искривление позвоночника часто начинается в детстве.",
        "example_uz": "Umurtqa pog'onasining qiyshayishi ko'pincha bolalikdan boshlanadi."
    },
    {
        "word": "Инфаркт",
        "transcription": "[инф`аркт]",
        "gender": "муж.р. (masculine)",
        "translation": "Infarkt",
        "category": "Kardiologiya",
        "description": "Qon yetishmasligi tufayli a'zo to'qimasining o'lishi (nekroz).",
        "example_ru": "Острый инфаркт миокарда требует немедленной госпитализации.",
        "example_uz": "O'tkir miokard infarkti zudlik bilan shifoxonaga yotqizishni talab qiladi."
    },
    {
        "word": "Диагноз",
        "transcription": "[д'`иагназ]",
        "gender": "муж.р. (masculine)",
        "translation": "Tashxis",
        "category": "Terapiya",
        "description": "Kasallikning tibbiy xulosasi.",
        "example_ru": "Врач подтвердил диагноз после получения анализов.",
        "example_uz": "Shifokor tahlil natijalaridan so'ng tashxisni tasdiqladi."
    },
    {
        "word": "Мозг",
        "transcription": "[моск]",
        "gender": "муж.р. (masculine)",
        "translation": "Miya",
        "category": "Nevrologiya",
        "description": "Markaziy nerv tizimining asosiy boshqaruv organi.",
        "example_ru": "Головной мозг координирует все движения тела.",
        "example_uz": "Bosh miya tananing barcha harakatlarini muvofiqlashtiradi."
    },
    {
        "word": "Рецепт",
        "transcription": "[риц`эпт]",
        "gender": "муж.р. (masculine)",
        "translation": "Retsept",
        "category": "Terapiya",
        "description": "Dori sotib olish yoki tayyorlash uchun yozma shifokor ko'rsatmasi.",
        "example_ru": "Выпишите, пожалуйста, рецепт на антибиотики.",
        "example_uz": "Iltimos, antibiyotiklarga retsept yozib bersangiz."
    }
]

async def seed_dictionary():
    async with AsyncSessionLocal() as session:
        print("Seeding medical dictionary...")
        for t in terms_data:
            # Check if term already exists
            res = await session.execute(select(MedicalTerm).where(MedicalTerm.word == t["word"]))
            term = res.scalar_one_or_none()
            if term:
                print(f"Term '{t['word']}' already exists. Skipping...")
                continue
            
            new_term = MedicalTerm(
                word=t["word"],
                transcription=t["transcription"],
                gender=t["gender"],
                translation=t["translation"],
                category=t["category"],
                description=t["description"],
                example_ru=t["example_ru"],
                example_uz=t["example_uz"]
            )
            session.add(new_term)
        await session.commit()
        print("Medical dictionary seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_dictionary())
