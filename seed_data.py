import asyncio
import os
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, UserRole, UserState
from dotenv import load_dotenv

load_dotenv()

async def create_user_with_state(session, telegram_id: int, full_name: str, role: UserRole):
    # Check if user already exists
    result = await session.execute(select(User).where(User.telegram_user_id == telegram_id))
    user = result.scalar_one_or_none()
    
    if user:
        print(f"User with ID {telegram_id} ({full_name}) already exists. Skipping...")
        return user

    user = User(
        telegram_user_id=telegram_id,
        full_name=full_name,
        role=role,
        is_active=True
    )
    session.add(user)
    await session.flush()  # To get user.id

    # Create state
    state = UserState(user_id=user.id)
    session.add(state)
    
    print(f"Successfully created {role.name}: {full_name} ({telegram_id})")
    return user

async def main():
    teacher_id = int(os.getenv("SUPERADMIN_TELEGRAM_ID", 7402633908))
    
    async with AsyncSessionLocal() as session:
        try:
            # 1. Create Teacher (Employee)
            print("--- Creating Teacher ---")
            await create_user_with_state(session, teacher_id, "Main Teacher", UserRole.employee)
            
            # 2. Create 20 Students
            print("\n--- Creating 20 Students ---")
            for i in range(1, 21):
                student_id = 10000 + i
                student_name = f"Student {i}"
                await create_user_with_state(session, student_id, student_name, UserRole.student)
            
            await session.commit()
            print("\nDatabase seeding completed successfully!")
            
        except Exception as e:
            await session.rollback()
            print(f"Error seeding database: {e}")

if __name__ == "__main__":
    asyncio.run(main())
