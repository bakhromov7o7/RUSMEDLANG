import asyncio
from sqlalchemy import text
from app.database import engine
from app.models import Base

async def update_schema():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE topic_materials ADD COLUMN source_url TEXT"))
            print("Column 'source_url' added to 'topic_materials'")
        except Exception as e:
            print(f"Info: {e}")
        
        # Ensure all tables are created
        await conn.run_sync(Base.metadata.create_all)
        print("Schema sync completed.")

if __name__ == "__main__":
    asyncio.run(update_schema())
