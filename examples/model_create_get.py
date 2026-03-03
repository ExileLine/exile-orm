from __future__ import annotations

import asyncio
import os
import uuid

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, Model, StringField


class User(Model):
    __table_name__ = "users"

    id = IntegerField(primary_key=True)
    name = StringField()


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Please set DATABASE_URL before running this script.")

    table_name = f'users_{uuid.uuid4().hex[:8]}'
    User.__table_name__ = table_name

    db = Database(DatabaseConfig(dsn=dsn))
    await db.connect()
    User.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{table_name}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL"
            ")"
        )
        created = await User.create(name="alice")
        fetched = await User.get(id=created.id)
        print(f"Created user id={created.id}, fetched name={fetched.name}")
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

