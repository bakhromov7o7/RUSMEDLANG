import asyncio
import json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, UserRole, Topic, KnowledgeChunk, QuizAttempt, QuizQuestion, StudentSession
from app.api.quiz import generate_quiz, submit_quiz, QuizStartRequest, QuizSubmitRequest

async def run_flow():
    async with AsyncSessionLocal() as db:
        # 1. Get student user
        res = await db.execute(select(User).where(User.role == UserRole.student))
        student = res.scalars().first()
        
        # 2. Get topic
        res = await db.execute(select(Topic))
        topic = res.scalars().first()

        print(f"Found student: {student.full_name} (ID: {student.id})")
        print(f"Found topic: {topic.title} (ID: {topic.id})")

        print("\n--- FIRST GENERATION ---")
        try:
            req = QuizStartRequest(topic_id=topic.id, language="uz")
            quiz_data = await generate_quiz(req, db)
            print("First generation successful!")
            print(f"Type: {type(quiz_data)}")
            print(json.dumps(quiz_data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"First generation FAILED: {e}")
            return

        print("\n--- SECOND GENERATION ---")
        try:
            req = QuizStartRequest(topic_id=topic.id, language="uz")
            quiz_data_2 = await generate_quiz(req, db)
            print("Second generation successful!")
            print(f"Type: {type(quiz_data_2)}")
            print(quiz_data_2)
        except Exception as e:
            print(f"Second generation FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(run_flow())
