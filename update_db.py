import asyncio
from sqlalchemy import text
from app.database import engine
from app.models import Base

async def update_schema():
    # 1. Ensure all new tables are created first
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("New tables (subjects, homeworks) created or verified.")
    except Exception as e:
        print(f"Error creating tables: {e}")

    # 2. Add source_url to topic_materials
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE topic_materials ADD COLUMN source_url TEXT"))
        print("Column 'source_url' added to 'topic_materials'")
    except Exception as e:
        print(f"Info (topic_materials.source_url): {e}")

    # 3. Add new columns to users table
    for col, col_type in [
        ("phone_number", "VARCHAR(50)"),
        ("student_group", "VARCHAR(100)"),
        ("parent_name", "VARCHAR(255)"),
        ("parent_phone", "VARCHAR(50)"),
        ("birth_date", "VARCHAR(100)"),
        ("notes", "TEXT"),
    ]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
            print(f"Column '{col}' added to 'users'")
        except Exception as e:
            print(f"Info (users.{col}): {e}")

    # 4. Add subject_id column to topics table
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE topics ADD COLUMN subject_id BIGINT REFERENCES subjects(id) ON DELETE CASCADE"))
        print("Column 'subject_id' added to 'topics'")
    except Exception as e:
        print(f"Info (topics.subject_id): {e}")

    print("Schema sync completed successfully.")

if __name__ == "__main__":
    asyncio.run(update_schema())
