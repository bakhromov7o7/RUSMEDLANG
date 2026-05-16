import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()
from app.bot.bot import create_bot_application
from app.database import engine, Base

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

app = FastAPI(title="Ustoz AI API")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Global error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "path": request.url.path,
            "type": type(exc).__name__
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info(f"Incoming request: {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        logging.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logging.error(f"Request failed: {e}")
        raise e

@app.on_event("startup")
async def startup_event():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start Telegram Bot (Disabled as requested)
    # bot_app = create_bot_application()
    # await bot_app.initialize()
    # await bot_app.start()
    # await bot_app.updater.start_polling()
    # print("Telegram bot started.")

@app.get("/")
async def root():
    return {"message": "Ustoz AI API is running"}

from app.api import auth, topics, quiz

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(topics.router, prefix="/api/topics", tags=["Topics"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
