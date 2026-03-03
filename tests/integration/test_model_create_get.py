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


class IntegrationUser(Model):
    __table_name__ = "integration_users"

    id = IntegerField(primary_key=True)
    name = StringField()


@pytest.mark.asyncio
async def test_model_create_then_get_roundtrip() -> None:
    assert DATABASE_URL is not None
    table_name = f'integration_users_{uuid.uuid4().hex[:8]}'
    IntegrationUser.__table_name__ = table_name

    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    IntegrationUser.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{table_name}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL"
            ")"
        )
        created = await IntegrationUser.create(name="integration-alice")
        fetched = await IntegrationUser.get(id=created.id)

        assert fetched.id == created.id
        assert fetched.name == "integration-alice"
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        await db.disconnect()

