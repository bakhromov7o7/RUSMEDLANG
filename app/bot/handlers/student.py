from telegram import Update
from telegram.ext import ContextTypes
from app.models import User, Topic, UserRole, TopicStatus, StudentTopicAccess, UserState
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.bot.keyboards import get_topic_actions_keyboard
from app.services.ai_service import AIService

ai_service = AIService()

async def list_student_topics(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User):
    async with AsyncSessionLocal() as session:
        # Get topics assigned to this student
        stmt = select(Topic).join(StudentTopicAccess).where(StudentTopicAccess.student_user_id == user.id)
        result = await session.execute(stmt)
        topics = result.scalars().all()
        
        if not topics:
            await update.message.reply_text("Sizda hali biriktirilgan mavzular yo'q.")
            return
            
        text = "Sizning mavzularingiz:\n\n"
        for t in topics:
            text += f"📚 {t.title}\n"
            text += f"Tushuntirish: /topic_{t.id}\n\n"
            
        await update.message.reply_text(text)

async def view_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, topic_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Topic).where(Topic.id == topic_id))
        topic = result.scalar_one_or_none()
        
        if not topic:
            await update.message.reply_text("Mavzu topilmadi.")
            return
            
        # Update active topic
        stmt = select(UserState).where(UserState.user_id == user.id)
        res = await session.execute(stmt)
        state = res.scalar_one_or_none()
        if state:
            state.active_topic_id = topic.id
            await session.commit()
            
        await update.message.reply_text(
            f"Mavzu: {topic.title}\n\n{topic.description or ''}\n\n"
            "Savollaringizni yuborishingiz mumkin.",
            reply_markup=get_topic_actions_keyboard(topic.id)
        )

async def handle_student_ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str):
    async with AsyncSessionLocal() as session:
        stmt = select(UserState).where(UserState.user_id == user.id)
        res = await session.execute(stmt)
        state = res.scalar_one_or_none()
        
        if not state or not state.active_topic_id:
            await update.message.reply_text("Iltimos, avval mavzu tanlang.")
            return
            
        # For MVP, we'll just use a generic context or get chunks later
        # In full version, we'd query KnowledgeChunk here
        response = await ai_service.get_response("Generic context about the topic", text, state.preferred_language)
        await update.message.reply_text(response)
