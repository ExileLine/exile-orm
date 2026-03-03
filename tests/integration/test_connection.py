from __future__ import annotations

import os

import pytest

from exile_orm.core.database import Database, DatabaseConfig

DATABASE_URL = os.getenv("EXILE_ORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="Set EXILE_ORM_TEST_DATABASE_URL to run integration database tests.",
    ),
]


@pytest.mark.asyncio
async def test_select_one_roundtrip() -> None:
    assert DATABASE_URL is not None
    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    row = await db.fetch_one("SELECT 1 AS value")
    await db.disconnect()

    assert row is not None
    assert row["value"] == 1

