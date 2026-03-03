from __future__ import annotations

import os
import uuid

import pytest

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, Model, StringField

DATABASE_URL = os.getenv("EXILE_ORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="Set EXILE_ORM_TEST_DATABASE_URL to run integration database tests.",
    ),
]


class CrudUser(Model):
    __table_name__ = "crud_users"

    id = IntegerField(primary_key=True)
    name = StringField()


@pytest.mark.asyncio
async def test_crud_and_bulk_operations_roundtrip() -> None:
    assert DATABASE_URL is not None
    table_name = f'crud_users_{uuid.uuid4().hex[:8]}'
    CrudUser.__table_name__ = table_name

    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    CrudUser.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{table_name}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL"
            ")"
        )

        created = await CrudUser.create(name="alice")
        fetched = await CrudUser.get(id=created.id)
        assert fetched.name == "alice"

        fetched.name = "alice-updated"
        await fetched.save()
        updated = await CrudUser.get(id=created.id)
        assert updated.name == "alice-updated"

        bulk = await CrudUser.bulk_create(
            [{"name": "b1"}, {"name": "b2"}, {"name": "b3"}],
            batch_size=2,
        )
        assert len(bulk) == 3

        bulk[0].name = "bulk-1"
        bulk[1].name = "bulk-2"
        updated_rows = await CrudUser.bulk_update(bulk[:2], fields=["name"], batch_size=1)
        assert updated_rows == 2

        deleted_rows = await CrudUser.bulk_delete(bulk, batch_size=2)
        assert deleted_rows == 3

        await updated.delete()
        assert await CrudUser.filter(id=created.id).first() is None
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        await db.disconnect()


@pytest.mark.asyncio
async def test_transaction_rollback_on_exception() -> None:
    assert DATABASE_URL is not None
    table_name = f'txn_users_{uuid.uuid4().hex[:8]}'
    CrudUser.__table_name__ = table_name

    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    CrudUser.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{table_name}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL"
            ")"
        )

        with pytest.raises(RuntimeError):
            async with db.transaction():
                await CrudUser.create(name="to-rollback")
                raise RuntimeError("force rollback")

        remaining = await CrudUser.filter(name="to-rollback").count()
        assert remaining == 0
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        await db.disconnect()

