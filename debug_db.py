import asyncio
import os
from sqlalchemy import text
from app.database import engine, Base
from dotenv import load_dotenv

load_dotenv()

async def debug():
    print(f"DATABASE_URL: {os.getenv('DATABASE_URL')}")
    try:
        async with engine.connect() as conn:
            print("Successfully connected to the database!")
            result = await conn.execute(text("SELECT version();"))
            row = result.fetchone()
            print(f"PostgreSQL version: {row[0]}")
            
            # Check tables
            print("\nChecking tables...")
            from sqlalchemy import inspect
            def get_tables(connection):
                return inspect(connection).get_table_names()
            
            tables = await conn.run_sync(get_tables)
            print(f"Tables in database: {tables}")
            
    except Exception as e:
        print(f"Database connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(debug())
