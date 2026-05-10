from telegram import Update
from telegram.ext import ContextTypes
from app.models import User, Topic, UserRole, TopicStatus, UserState
from app.database import AsyncSessionLocal
from sqlalchemy import select

async def start_topic_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User):
    async with AsyncSessionLocal() as session:
        stmt = select(UserState).where(UserState.user_id == user.id)
        res = await session.execute(stmt)
        state = res.scalar_one_or_none()
        
        if state:
            state.pending_action = "awaiting_topic_title"
            await session.commit()
            
        await update.message.reply_text("Yangi mavzu nomini yuboring:")

async def handle_topic_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, title: str):
    async with AsyncSessionLocal() as session:
        new_topic = Topic(
            employee_user_id=user.id,
            title=title,
            status=TopicStatus.active
        )
        session.add(new_topic)
        await session.flush()
        
        # Clear state
        stmt = select(UserState).where(UserState.user_id == user.id)
        res = await session.execute(stmt)
        state = res.scalar_one_or_none()
        if state:
            state.pending_action = None
            state.active_topic_id = new_topic.id
            await session.commit()
            
        await update.message.reply_text(f"Mavzu yaratildi: {title}\nEndi materiallarni (video yoki text) yuborishingiz mumkin.")
