import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv

from app.bot.keyboards import get_role_keyboard
from app.database import AsyncSessionLocal
from app.models import User, UserRole, UserState
from sqlalchemy import select

load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    full_name = update.effective_user.full_name
    
    async with AsyncSessionLocal() as session:
        # Check if user exists
        result = await session.execute(select(User).where(User.telegram_user_id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            # Check for superadmin bootstrap
            superadmin_id = os.getenv("SUPERADMIN_TELEGRAM_ID")
            if superadmin_id and str(user_id) == superadmin_id:
                user = User(
                    telegram_user_id=user_id,
                    full_name=full_name,
                    username=username,
                    role=UserRole.superadmin
                )
                session.add(user)
                await session.flush()
                # Create state
                state = UserState(user_id=user.id)
                session.add(state)
                await session.commit()
            else:
                await update.message.reply_text(
                    "Assalomu alaykum! Ustoz AI botiga xush kelibsiz.\n"
                    "Foydalanish uchun employee tomonidan ro'yxatga olingan bo'lishingiz kerak."
                )
                return

        await update.message.reply_text(
            f"Xush kelibsiz, {user.full_name}!",
            reply_markup=get_role_keyboard(user.role)
        )

from app.bot.handlers import student, employee

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_user_id == user_id))
        user = result.scalar_one_or_none()
        if not user: return
        
        # Check pending state
        stmt = select(UserState).where(UserState.user_id == user.id)
        res = await session.execute(stmt)
        state = res.scalar_one_or_none()
        
        text = update.message.text
        
        if state and state.pending_action == "awaiting_topic_title":
            await employee.handle_topic_title_input(update, context, user, text)
            return
            
        if text == "📚 Mavzularim":
            await student.list_student_topics(update, context, user)
            return
        elif text == "📝 Mavzu yaratish":
            await employee.start_topic_creation(update, context, user)
            return
            
        # Default AI chat for students
        if user.role == UserRole.student:
            await student.handle_student_ai_query(update, context, user, text)

async def handle_topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_user_id == user_id))
        user = result.scalar_one_or_none()
        if not user: return
        
        cmd = update.message.text
        if cmd.startswith("/topic_"):
            topic_id = int(cmd.split("_")[1])
            await student.view_topic(update, context, user, topic_id)

def create_bot_application():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex(r'^/topic_'), handle_topic_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    return application
