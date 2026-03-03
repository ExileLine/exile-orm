from __future__ import annotations

import asyncio
import os

from exile_orm.core.database import Database, DatabaseConfig


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Please set DATABASE_URL before running this script.")

    db = Database(DatabaseConfig(dsn=dsn))
    await db.connect()
    try:
        row = await db.fetch_one("SELECT 1 AS value")
        print(f"Database ping OK: value={row['value'] if row else None}")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

