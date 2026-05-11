import asyncio
import sys
import os

# Add the current directory to sys.path so it can find the 'app' module
sys.path.append(os.getcwd())

from app.database import engine, Base
from app.models import User, Topic, TopicMaterial, KnowledgeChunk, UserState, StudentSession, QuizAttempt, QuizQuestion, StudentApplication

async def init_db():
    print("Connecting to database and creating tables...")
    try:
        async with engine.begin() as conn:
            # This will create all tables defined in models.py
            await conn.run_sync(Base.metadata.create_all)
        print("Successfully created all tables!")
    except Exception as e:
        print(f"Error creating tables: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
