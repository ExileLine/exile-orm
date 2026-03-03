from __future__ import annotations

import asyncio
from typing import Any

import pytest

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.core.exceptions import (
    DatabaseNotConnectedError,
    ForeignKeyConstraintError,
    MissingDependencyError,
    QueryError,
    UniqueConstraintError,
)


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        self.connection.transaction_entries += 1
        self.connection.transaction_depth += 1
        return self.connection

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.connection.transaction_exits += 1
        self.connection.transaction_depth -= 1


class FakeConnection:
    def __init__(self) -> None:
        self.transaction_entries = 0
        self.transaction_exits = 0
        self.transaction_depth = 0
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_count = 0
        self.fetch_count = 0
        self.execute_failures: list[Exception] = []
        self.fetchrow_failures: list[Exception] = []
        self.fetch_failures: list[Exception] = []
        self.fetchrow_delay_seconds = 0.0
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    async def execute(self, query: str, *args: object) -> str:
        if self.execute_failures:
            raise self.execute_failures.pop(0)
        self.executed.append((query, args))
        if query.startswith("DELETE"):
            return "DELETE 1"
        if query.startswith("UPDATE"):
            return "UPDATE 1"
        return "EXECUTED"

    async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
        if self.fetchrow_delay_seconds > 0:
            await asyncio.sleep(self.fetchrow_delay_seconds)
        if self.fetchrow_failures:
            raise self.fetchrow_failures.pop(0)
        self.fetchrow_count += 1
        return {"query": query, "args": args}

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        if self.fetch_failures:
            raise self.fetch_failures.pop(0)
        self.fetch_count += 1
        return [{"query": query, "args": args}]

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> str:
        self.executemany_calls.append((query, args))
        return "EXECUTEMANY"

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


class FakePool:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.closed = False
        self.release_count = 0
        self.acquire_count = 0

    async def acquire(self) -> FakeConnection:
        self.acquire_count += 1
        return self.connection

    async def release(self, connection: FakeConnection) -> None:
        assert connection is self.connection
        self.release_count += 1

    async def close(self) -> None:
        self.closed = True


class FakeDriver:
    def __init__(self) -> None:
        self.last_create_pool_kwargs: dict[str, object] = {}
        self.pool = FakePool()

    async def create_pool(self, **kwargs: object) -> FakePool:
        self.last_create_pool_kwargs = kwargs
        return self.pool


@pytest.mark.asyncio
async def test_connect_execute_fetch_and_disconnect() -> None:
    driver = FakeDriver()
    config = DatabaseConfig(
        dsn="postgresql://localhost/exile_orm_test",
        min_size=2,
        max_size=5,
    )
    db = Database(config, driver_module=driver)

    await db.connect()
    assert db.is_connected is True
    assert driver.last_create_pool_kwargs["min_size"] == 2
    assert driver.last_create_pool_kwargs["max_size"] == 5

    status = await db.execute("SELECT 1")
    assert status == "EXECUTED"

    row = await db.fetch_one("SELECT $1", 1)
    assert row["args"] == (1,)

    rows = await db.fetch_all("SELECT $1", 2)
    assert len(rows) == 1
    assert rows[0]["args"] == (2,)

    await db.disconnect()
    assert driver.pool.closed is True
    assert db.is_connected is False


@pytest.mark.asyncio
async def test_nested_transaction_reuses_connection_and_supports_savepoint() -> None:
    driver = FakeDriver()
    db = Database(DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"), driver_module=driver)
    await db.connect()

    async with db.transaction():
        assert db.transaction_depth == 1
        await db.execute("SELECT 1")
        async with db.savepoint():
            assert db.transaction_depth == 2
            await db.execute("SELECT 2")
        assert db.transaction_depth == 1

    assert db.transaction_depth == 0
    assert driver.pool.acquire_count == 1
    assert driver.pool.release_count == 1
    assert driver.pool.connection.transaction_entries == 2
    assert driver.pool.connection.transaction_exits == 2
    await db.disconnect()


@pytest.mark.asyncio
async def test_savepoint_requires_active_transaction() -> None:
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=FakeDriver(),
    )
    await db.connect()

    with pytest.raises(QueryError, match="savepoint"):
        async with db.savepoint():
            pass
    await db.disconnect()


@pytest.mark.asyncio
async def test_sql_logging_redacts_parameters_by_default() -> None:
    logs: list[tuple[str, tuple[object, ...], float, bool]] = []

    def logger(query: str, args: tuple[object, ...], duration_ms: float, success: bool) -> None:
        logs.append((query, args, duration_ms, success))

    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            log_sql=True,
            sql_logger=logger,
        ),
        driver_module=FakeDriver(),
    )
    await db.connect()
    await db.execute("SELECT $1", 123)
    await db.disconnect()

    assert len(logs) == 1
    assert logs[0][0] == "SELECT $1"
    assert logs[0][1] == ("<redacted>",)
    assert logs[0][3] is True


@pytest.mark.asyncio
async def test_sql_logging_can_include_parameters() -> None:
    logs: list[tuple[str, tuple[object, ...], float, bool]] = []

    def logger(query: str, args: tuple[object, ...], duration_ms: float, success: bool) -> None:
        logs.append((query, args, duration_ms, success))

    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            log_sql=True,
            log_sql_parameters=True,
            sql_logger=logger,
        ),
        driver_module=FakeDriver(),
    )
    await db.connect()
    await db.execute("SELECT $1", 456)
    await db.disconnect()

    assert logs[0][1] == (456,)


@pytest.mark.asyncio
async def test_slow_query_logging_works_without_general_sql_logging() -> None:
    logs: list[tuple[str, tuple[object, ...], float, bool]] = []

    def logger(query: str, args: tuple[object, ...], duration_ms: float, success: bool) -> None:
        logs.append((query, args, duration_ms, success))

    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            slow_query_threshold_ms=0,
            sql_logger=logger,
        ),
        driver_module=FakeDriver(),
    )
    await db.connect()
    await db.fetch_one("SELECT 1")
    await db.disconnect()

    assert len(logs) == 1
    assert logs[0][0] == "SELECT 1"


@pytest.mark.asyncio
async def test_query_cache_hits_for_cached_fetch_one() -> None:
    now_value = [100.0]

    def time_source() -> float:
        return now_value[0]

    driver = FakeDriver()
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            enable_query_cache=True,
        ),
        driver_module=driver,
        time_source=time_source,
    )
    await db.connect()

    first = await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=10.0)
    second = await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=10.0)
    await db.disconnect()

    assert first["args"] == (1,)
    assert second["args"] == (1,)
    assert driver.pool.connection.fetchrow_count == 1
    assert db.cache_hits == 1
    assert db.cache_misses == 1


@pytest.mark.asyncio
async def test_query_cache_expires_by_ttl() -> None:
    now_value = [200.0]

    def time_source() -> float:
        return now_value[0]

    driver = FakeDriver()
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            enable_query_cache=True,
        ),
        driver_module=driver,
        time_source=time_source,
    )
    await db.connect()

    await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=1.0)
    now_value[0] += 2.0
    await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=1.0)
    await db.disconnect()

    assert driver.pool.connection.fetchrow_count == 2
    assert db.cache_hits == 0
    assert db.cache_misses == 2


@pytest.mark.asyncio
async def test_execute_invalidates_query_cache() -> None:
    driver = FakeDriver()
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            enable_query_cache=True,
        ),
        driver_module=driver,
    )
    await db.connect()

    await db.cached_fetch_all("SELECT 1", ttl_seconds=10.0)
    await db.execute("UPDATE table_x SET y = 1")
    await db.cached_fetch_all("SELECT 1", ttl_seconds=10.0)
    await db.disconnect()

    assert driver.pool.connection.fetch_count == 2


@pytest.mark.asyncio
async def test_query_cache_eviction_by_max_entries() -> None:
    driver = FakeDriver()
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            enable_query_cache=True,
            query_cache_max_entries=1,
        ),
        driver_module=driver,
    )
    await db.connect()

    await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=10.0)
    await db.cached_fetch_one("SELECT $1", 2, ttl_seconds=10.0)
    await db.cached_fetch_one("SELECT $1", 1, ttl_seconds=10.0)
    await db.disconnect()

    assert driver.pool.connection.fetchrow_count == 3


@pytest.mark.asyncio
async def test_idempotent_fetch_retries_on_timeout() -> None:
    driver = FakeDriver()
    driver.pool.connection.fetchrow_failures = [TimeoutError("temporary timeout")]
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            idempotent_retry_attempts=2,
            idempotent_retry_backoff_seconds=0.0,
        ),
        driver_module=driver,
    )
    await db.connect()
    row = await db.fetch_one("SELECT 1")
    await db.disconnect()

    assert row["query"] == "SELECT 1"
    assert driver.pool.connection.fetchrow_count == 1


@pytest.mark.asyncio
async def test_execute_does_not_retry_by_default() -> None:
    driver = FakeDriver()
    driver.pool.connection.execute_failures = [TimeoutError("temporary timeout")]
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            idempotent_retry_attempts=3,
            idempotent_retry_backoff_seconds=0.0,
        ),
        driver_module=driver,
    )
    await db.connect()

    with pytest.raises(QueryError, match="execute query"):
        await db.execute("UPDATE foo SET bar = 1")
    await db.disconnect()
    assert len(driver.pool.connection.executed) == 0


@pytest.mark.asyncio
async def test_execute_idempotent_retries() -> None:
    driver = FakeDriver()
    driver.pool.connection.execute_failures = [TimeoutError("temporary timeout")]
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            idempotent_retry_attempts=2,
            idempotent_retry_backoff_seconds=0.0,
        ),
        driver_module=driver,
    )
    await db.connect()
    status = await db.execute_idempotent("VACUUM")
    await db.disconnect()

    assert status == "EXECUTED"
    assert driver.pool.connection.executed == [("VACUUM", ())]


@pytest.mark.asyncio
async def test_query_timeout_maps_to_query_error() -> None:
    driver = FakeDriver()
    driver.pool.connection.fetchrow_delay_seconds = 0.01
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            query_timeout_seconds=0.001,
            idempotent_retry_attempts=0,
        ),
        driver_module=driver,
    )
    await db.connect()

    with pytest.raises(QueryError, match="fetch row"):
        await db.fetch_one("SELECT 1")
    await db.disconnect()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_wrapping() -> None:
    driver = FakeDriver()
    driver.pool.connection.fetchrow_delay_seconds = 0.05
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=driver,
    )
    await db.connect()

    task = asyncio.create_task(db.fetch_one("SELECT 1"))
    await asyncio.sleep(0.001)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await db.disconnect()


@pytest.mark.asyncio
async def test_execute_many_and_cache_invalidation() -> None:
    driver = FakeDriver()
    db = Database(
        DatabaseConfig(
            dsn="postgresql://localhost/exile_orm_test",
            enable_query_cache=True,
        ),
        driver_module=driver,
    )
    await db.connect()
    await db.cached_fetch_one("SELECT 1", ttl_seconds=30.0)

    await db.execute_many(
        "INSERT INTO foo (a, b) VALUES ($1, $2)",
        [(1, "x"), (2, "y")],
    )
    await db.cached_fetch_one("SELECT 1", ttl_seconds=30.0)
    await db.disconnect()

    assert driver.pool.connection.executemany_calls == [
        (
            "INSERT INTO foo (a, b) VALUES ($1, $2)",
            [(1, "x"), (2, "y")],
        )
    ]
    assert driver.pool.connection.fetchrow_count == 2


@pytest.mark.asyncio
async def test_connection_counters_no_leak_under_concurrency() -> None:
    driver = FakeDriver()
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=driver,
    )
    await db.connect()

    await asyncio.gather(*[db.fetch_one("SELECT $1", i) for i in range(50)])
    await db.disconnect()

    assert db.acquire_count == db.release_count
    assert db.in_use_connections == 0
    assert db.peak_in_use_connections >= 1


@pytest.mark.asyncio
async def test_missing_dependency_error() -> None:
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=None,
    )
    db._driver = None  # simulate missing asyncpg
    with pytest.raises(MissingDependencyError):
        await db.connect()


@pytest.mark.asyncio
async def test_error_when_not_connected() -> None:
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=FakeDriver(),
    )
    with pytest.raises(DatabaseNotConnectedError):
        await db.execute("SELECT 1")


@pytest.mark.asyncio
async def test_query_error_mapping() -> None:
    class BrokenConnection(FakeConnection):
        async def execute(self, query: str, *args: object) -> str:
            raise RuntimeError("boom")

    class BrokenPool(FakePool):
        def __init__(self) -> None:
            super().__init__()
            self.connection = BrokenConnection()

    class BrokenDriver(FakeDriver):
        def __init__(self) -> None:
            super().__init__()
            self.pool = BrokenPool()

    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=BrokenDriver(),
    )
    await db.connect()
    with pytest.raises(QueryError):
        await db.execute("SELECT 1")
    await db.disconnect()


@pytest.mark.asyncio
async def test_unique_violation_maps_to_domain_error() -> None:
    class UniqueViolationError(Exception):
        pass

    driver = FakeDriver()
    driver.pool.connection.execute_failures = [UniqueViolationError("duplicate key")]
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=driver,
    )
    await db.connect()
    with pytest.raises(UniqueConstraintError):
        await db.execute("INSERT INTO users (id) VALUES (1)")
    await db.disconnect()


@pytest.mark.asyncio
async def test_foreign_key_violation_maps_to_domain_error() -> None:
    class ForeignKeyViolationError(Exception):
        pass

    driver = FakeDriver()
    driver.pool.connection.execute_failures = [ForeignKeyViolationError("fk violation")]
    db = Database(
        DatabaseConfig(dsn="postgresql://localhost/exile_orm_test"),
        driver_module=driver,
    )
    await db.connect()
    with pytest.raises(ForeignKeyConstraintError):
        await db.execute("INSERT INTO child (parent_id) VALUES (999)")
    await db.disconnect()
