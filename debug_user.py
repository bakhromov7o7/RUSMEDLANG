import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User
import os
from dotenv import load_dotenv

load_dotenv()

async def check_user():
    async with AsyncSessionLocal() as session:
        admin_id = int(os.getenv("SUPERADMIN_TELEGRAM_ID", 7402633908))
        result = await session.execute(select(User).where(User.telegram_user_id == admin_id))
        user = result.scalar_one_or_none()
        if user:
            print(f"DEBUG: User found - Name: {user.full_name}, Role: {user.role}, ID: {user.telegram_user_id}")
        else:
            print(f"DEBUG: User with ID {admin_id} NOT FOUND")

if __name__ == "__main__":
    asyncio.run(check_user())
