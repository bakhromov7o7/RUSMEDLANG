import asyncio
import sys
from app.database import AsyncSessionLocal
from app.models import User, UserRole, UserState
from sqlalchemy import select

async def create_user(telegram_id: int, full_name: str, role_str: str):
    role = UserRole[role_str]
    async with AsyncSessionLocal() as session:
        # Check if exists
        result = await session.execute(select(User).where(User.telegram_user_id == telegram_id))
        user = result.scalar_one_or_none()
        
        if user:
            print(f"User with ID {telegram_id} already exists.")
            return
        
        user = User(
            telegram_user_id=telegram_id,
            full_name=full_name,
            role=role,
            is_active=True
        )
        session.add(user)
        await session.flush()
        
        # Create state
        state = UserState(user_id=user.id)
        session.add(state)
        
        await session.commit()
        print(f"Successfully created {role_str}: {full_name} ({telegram_id})")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 create_user.py <telegram_id> <full_name> <role: superadmin|employee|student>")
    else:
        tid = int(sys.argv[1])
        name = sys.argv[2]
        role = sys.argv[3]
        asyncio.run(create_user(tid, name, role))
