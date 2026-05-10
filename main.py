import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.bot.bot import create_bot_application
from app.database import engine, Base

app = FastAPI(title="Ustoz AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start Telegram Bot in background
    bot_app = create_bot_application()
    asyncio.create_task(bot_app.initialize())
    asyncio.create_task(bot_app.start())
    asyncio.create_task(bot_app.updater.start_polling())
    print("Telegram bot started.")

@app.get("/")
async def root():
    return {"message": "Ustoz AI API is running"}

from app.api import auth, topics, quiz

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(topics.router, prefix="/api/topics", tags=["Topics"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
