import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, UserRole
import os
from dotenv import load_dotenv

load_dotenv()

async def make_employee():
    async with AsyncSessionLocal() as session:
        # Get Superadmin ID from .env
        admin_id = int(os.getenv("SUPERADMIN_TELEGRAM_ID", 7402633908))
        
        result = await session.execute(select(User).where(User.telegram_user_id == admin_id))
        user = result.scalar_one_or_none()
        
        if user:
            user.role = "employee"
            print(f"User {user.full_name} (ID: {user.id}) role updated to employee.")
        else:
            user = User(
                telegram_user_id=admin_id,
                full_name="Admin Adminov",
                role="employee"
            )
            session.add(user)
            print(f"Created new employee user with Telegram ID: {admin_id}")
            
        await session.commit()

if __name__ == "__main__":
    asyncio.run(make_employee())
