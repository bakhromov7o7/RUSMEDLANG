import asyncio
from sqlalchemy import text
from app.database import engine

async def test_conn():
    print("Testing database connection...")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print(f"Connection successful! Result: {result.fetchone()}")
    except Exception as e:
        print(f"Connection FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_conn())
