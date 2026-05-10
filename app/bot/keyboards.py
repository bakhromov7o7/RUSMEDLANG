from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from app.models import UserRole

def get_role_keyboard(role: UserRole):
    if role == UserRole.superadmin:
        keyboard = [
            ["➕ Employee qo'shish", "👥 Employee'lar"],
            ["📊 Umumiy natijalar", "⚠️ Kuchsiz studentlar"],
            ["🔄 Role almashtirish"]
        ]
    elif role == UserRole.employee:
        keyboard = [
            ["📝 Mavzu yaratish", "📚 Mavzularim"],
            ["👨‍🎓 Student qo'shish", "🔗 Studentga biriktirish"],
            ["📊 Natijalar", "⚠️ Kuchsiz studentlar"]
        ]
    else: # student
        keyboard = [
            ["📚 Mavzularim", "✨ Aktiv mavzu"],
            ["❓ Savol berish", "✍️ Test boshlash"],
            ["❌ Xatolarim", "🌐 Til tanlash"]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_languages_keyboard():
    keyboard = [
        [InlineKeyboardButton("O'zbekcha 🇺🇿", callback_data="lang_uz")],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_topic_actions_keyboard(topic_id):
    keyboard = [
        [InlineKeyboardButton("📖 O'qish", callback_data=f"topic_view_{topic_id}")],
        [InlineKeyboardButton("✍️ Testni boshlash", callback_data=f"topic_quiz_{topic_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)
