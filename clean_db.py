import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

load_dotenv(find_dotenv())

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: F401, E402


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgresql+psycopg2://"):
        return database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return database_url


def database_name_from_url(database_url: str) -> str:
    parsed = urlparse(normalize_database_url(database_url))

    if parsed.scheme.startswith("sqlite"):
        path = parsed.path or parsed.netloc
        if not path or path in {":memory:", "/:memory:"}:
            return ":memory:"
        return Path(path).name

    return parsed.path.lstrip("/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean only this project's configured database."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation flag. Without it the script will not clean data.",
    )
    parser.add_argument(
        "--allow-db",
        default=os.getenv("DB_CLEAN_ALLOW_NAME"),
        help="Database name that is allowed to be cleaned. Can also be set via DB_CLEAN_ALLOW_NAME.",
    )
    return parser.parse_args()


async def clean_postgres() -> None:
    table_names = [table.name for table in reversed(Base.metadata.sorted_tables)]
    if not table_names:
        print("No tables found in SQLAlchemy metadata.")
        return

    quoted_tables = ", ".join(f'public."{table_name}"' for table_name in table_names)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))


async def clean_sqlite() -> None:
    table_names = [table.name for table in reversed(Base.metadata.sorted_tables)]
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table_name in table_names:
            await conn.execute(text(f'DELETE FROM "{table_name}"'))
        try:
            await conn.execute(text("DELETE FROM sqlite_sequence"))
        except SQLAlchemyError:
            pass
        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def main() -> int:
    args = parse_args()
    raw_database_url = os.getenv("DATABASE_URL")

    if not raw_database_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    if not args.allow_db:
        print(
            "ERROR: DB_CLEAN_ALLOW_NAME is not set. Example: DB_CLEAN_ALLOW_NAME=ustoz_ai",
            file=sys.stderr,
        )
        return 1

    actual_db = database_name_from_url(raw_database_url)
    if actual_db != args.allow_db:
        print(
            f"ERROR: refusing to clean database '{actual_db}'. Allowed database is '{args.allow_db}'.",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        print("ERROR: add --yes to confirm database cleaning.", file=sys.stderr)
        return 1

    dialect = engine.dialect.name
    if dialect == "postgresql":
        await clean_postgres()
    elif dialect == "sqlite":
        await clean_sqlite()
    else:
        print(f"ERROR: unsupported database dialect '{dialect}'.", file=sys.stderr)
        return 1

    await engine.dispose()
    print(f"OK: cleaned only '{actual_db}' database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
