from __future__ import annotations

import asyncio
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
async def test_connection_pool_stays_leak_free_under_concurrency() -> None:
    assert DATABASE_URL is not None
    max_size = 10
    workers = 60
    queries_per_worker = 20

    db = Database(
        DatabaseConfig(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=max_size,
        )
    )
    await db.connect()

    async def worker() -> None:
        for _ in range(queries_per_worker):
            row = await db.fetch_one("SELECT 1 AS value")
            assert row is not None
            assert row["value"] == 1

    try:
        await asyncio.wait_for(asyncio.gather(*(worker() for _ in range(workers))), timeout=30.0)
    finally:
        await db.disconnect()

    assert db.acquire_count == db.release_count
    assert db.in_use_connections == 0
    assert db.peak_in_use_connections <= max_size
    assert db.peak_in_use_connections > 0
