import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import os
from dotenv import load_dotenv

# Import models
import sys
sys.path.append(os.getcwd())
from app.models import Topic, KnowledgeChunk, User

load_dotenv()

RAW_DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ustozai")
if "asyncpg" not in RAW_DB_URL:
    DATABASE_URL = RAW_DB_URL.replace("postgresql://", "postgresql+asyncpg://")
else:
    DATABASE_URL = RAW_DB_URL

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def populate_biology():
    async with AsyncSessionLocal() as session:
        # Create an employee user if needed
        employee = User(
            telegram_user_id=12345678,
            full_name="Biologiya O'qituvchisi",
            role="employee"
        )
        session.add(employee)
        await session.flush()

        # 1. Sitologiya
        citology = Topic(
            employee_user_id=employee.id,
            title="Sitologiya - Hujayra nazariyasi",
            description="Hujayraning tuzilishi, funksiyasi va hayotiy jarayonlari haqida umumiy tushunchalar.",
            status="active"
        )
        session.add(citology)
        await session.flush()

        chunks = [
            KnowledgeChunk(
                topic_id=citology.id,
                chunk_index=0,
                chunk_text="Hujayra nazariyasining asoschilari Teodor Shvann va Mattias Shleyden hisoblanadi (1838-1839). Rudolf Virxov esa 1858-yilda 'har bir hujayra hujayradan hosil bo'ladi' degan qoidani qo'shgan. Hujayra membranasining asosi qo'sh qavatli fosfolipidlar va ularning orasiga suzib yuruvchi oqsillardan iborat (Suyuq-mozaik model). Membrana tanlab o'tkazuvchanlik xususiyatiga ega."
            ),
            KnowledgeChunk(
                topic_id=citology.id,
                chunk_index=1,
                chunk_text="Mitoz bo'linish 4 bosqichdan iborat: profaza, metafaza, anafaza va telofaza. Metafaza bosqichida xromosomalar hujayra ekvatori bo'ylab tiziladi va xromosoma sonini sanash uchun eng qulay bosqich hisoblanadi. Anafazada esa sentromeralar bo'linib, xromatidalar qutblarga tarqaladi. Meioz bo'linish natijasida xromosomalar soni ikki baravar kamayadi (reduksion bo'linish)."
            ),
            KnowledgeChunk(
                topic_id=citology.id,
                chunk_index=2,
                chunk_text="Ribosomalar oqsil sinteziga javobgar bo'lib, ular membrana bilan o'ralmagan organoidlardir. Mitoxondriyalar esa hujayraning 'energiya stansiyasi' bo'lib, ularda ATF (adenozintrifosfat) sintezlanadi. Mitoxondriyalar o'zining shaxsiy DNK va ribosomalariga ega (yarim avtonom organoidlar). Lizosomalar hujayra ichida hazm qilish funksiyasini bajaradi."
            )
        ]
        session.add_all(chunks)

        # 2. Genetika
        genetics = Topic(
            employee_user_id=employee.id,
            title="Genetika - Mendel qonunlari",
            description="Irsiyatning asosiy qonuniyatlari, dominant va resessiv belgilarning nasldan naslga o'tishi.",
            status="active"
        )
        session.add(genetics)
        await session.flush()

        chunks_gen = [
            KnowledgeChunk(
                topic_id=genetics.id,
                chunk_index=0,
                chunk_text="Gregor Mendel genetika fanining asoschisi hisoblanadi. Uning birinchi qonuni - Birinchi bo'g'in duragaylarining bir xilligi qonuni. Ikkinchi qonuni - Belgilarning ajralish qonuni (F2 bo'g'inda fenotip bo'yicha 3:1, genotip bo'yicha 1:2:1 nisbatda ajralish kuzatiladi). Uchinchi qonuni - Belgilarning mustaqil holda irsiylanishi qonuni (faqat noallel genlar turli xromosomalarda joylashgan bo'lsa amal qiladi)."
            ),
            KnowledgeChunk(
                topic_id=genetics.id,
                chunk_index=1,
                chunk_text="Allellar - bitta genning muqobil ko'rinishlari bo'lib, ular gomologik xromosomalarning bir xil lokuslarida joylashadi. Gomozigota (AA yoki aa) organizmlarda belgilar ajralish bermaydi. Geterozigota (Aa) organizmlarda dominant belgi fenotipda namoyon bo'ladi, lekin resessiv gen yashirin holda saqlanadi. To'liqsiz dominantlikda (masalan, tungi go'zal o'simligida) oraliq fenotip hosil bo'ladi."
            )
        ]
        session.add_all(chunks_gen)

        await session.commit()
        print("Biologiya mavzulari muvaffaqiyatli qo'shildi!")

if __name__ == "__main__":
    asyncio.run(populate_biology())
