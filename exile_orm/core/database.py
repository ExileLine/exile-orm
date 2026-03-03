"""Async database primitives built on top of asyncpg."""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter
from types import TracebackType
from typing import Any, Protocol, cast

from exile_orm.core.exceptions import (
    CheckConstraintError,
    ConnectionError,
    DatabaseNotConnectedError,
    ForeignKeyConstraintError,
    IntegrityError,
    MissingDependencyError,
    NotNullConstraintError,
    QueryError,
    UniqueConstraintError,
)


class ConnectionProtocol(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...

    async def executemany(self, query: str, args: list[tuple[Any, ...]]) -> Any: ...

    async def fetchrow(self, query: str, *args: Any) -> Any: ...

    async def fetch(self, query: str, *args: Any) -> Any: ...

    def transaction(self) -> Any: ...


class PoolProtocol(Protocol):
    async def acquire(self) -> ConnectionProtocol: ...

    async def release(self, connection: ConnectionProtocol) -> None: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class DatabaseConfig:
    """Runtime configuration for connection pool creation."""

    dsn: str
    min_size: int = 1
    max_size: int = 10
    command_timeout: float = 60.0
    log_sql: bool = False
    log_sql_parameters: bool = False
    slow_query_threshold_ms: float | None = None
    sql_logger: Callable[[str, tuple[Any, ...], float, bool], None] | None = None
    enable_query_cache: bool = False
    query_cache_max_entries: int = 1024
    query_timeout_seconds: float | None = None
    idempotent_retry_attempts: int = 0
    idempotent_retry_backoff_seconds: float = 0.0


@dataclass(slots=True)
class _QueryCacheEntry:
    expires_at: float
    value: Any


class Database:
    """Async database wrapper with pool, queries and transactional helpers."""

    _fallback_sql_logger = logging.getLogger("exile_orm.sql")
    _CACHE_MISS = object()

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        driver_module: Any | None = None,
        time_source: Callable[[], float] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._driver = driver_module if driver_module is not None else self._load_default_driver()
        self._time_source = perf_counter if time_source is None else time_source
        self._sleep_func = asyncio.sleep if sleep_func is None else sleep_func
        self._pool: PoolProtocol | None = None
        self._active_connection: contextvars.ContextVar[ConnectionProtocol | None] = (
            contextvars.ContextVar("exile_orm_active_connection", default=None)
        )
        self._transaction_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
            "exile_orm_transaction_depth",
            default=0,
        )
        self._query_cache: dict[tuple[str, str, tuple[Any, ...]], _QueryCacheEntry] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._acquire_count = 0
        self._release_count = 0
        self._in_use_connections = 0
        self._peak_in_use_connections = 0

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    @property
    def transaction_depth(self) -> int:
        return self._transaction_depth.get()

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses

    @property
    def acquire_count(self) -> int:
        return self._acquire_count

    @property
    def release_count(self) -> int:
        return self._release_count

    @property
    def in_use_connections(self) -> int:
        return self._in_use_connections

    @property
    def peak_in_use_connections(self) -> int:
        return self._peak_in_use_connections

    async def connect(self) -> None:
        if self.is_connected:
            return
        if self._driver is None:
            raise MissingDependencyError(
                "asyncpg is required. Install it with: pip install asyncpg"
            )
        try:
            pool = await self._driver.create_pool(
                dsn=self._config.dsn,
                min_size=self._config.min_size,
                max_size=self._config.max_size,
                command_timeout=self._config.command_timeout,
            )
            self._pool = cast(PoolProtocol, pool)
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"Failed to create database pool: {exc}") from exc

    async def disconnect(self) -> None:
        if not self.is_connected:
            return
        assert self._pool is not None
        try:
            await self._pool.close()
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"Failed to close database pool: {exc}") from exc
        finally:
            self._pool = None
            self.clear_query_cache()

    async def acquire(self) -> ConnectionProtocol:
        pool = self._require_pool()
        try:
            connection = await pool.acquire()
            self._acquire_count += 1
            self._in_use_connections += 1
            if self._in_use_connections > self._peak_in_use_connections:
                self._peak_in_use_connections = self._in_use_connections
            return connection
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"Failed to acquire connection: {exc}") from exc

    async def release(self, connection: ConnectionProtocol) -> None:
        pool = self._require_pool()
        decremented = False
        if self._in_use_connections > 0:
            self._in_use_connections -= 1
            decremented = True
        try:
            await pool.release(connection)
            self._release_count += 1
        except Exception as exc:  # noqa: BLE001
            if decremented:
                self._in_use_connections += 1
            raise ConnectionError(f"Failed to release connection: {exc}") from exc

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[ConnectionProtocol]:
        existing_connection = self._active_connection.get()
        if existing_connection is not None:
            yield existing_connection
            return

        connection = await self.acquire()
        token = self._active_connection.set(connection)
        try:
            yield connection
        finally:
            self._active_connection.reset(token)
            await self.release(connection)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ConnectionProtocol]:
        async with self.connection() as connection:
            async with connection.transaction():
                depth_token = self._transaction_depth.set(self._transaction_depth.get() + 1)
                try:
                    yield connection
                finally:
                    self._transaction_depth.reset(depth_token)

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator[ConnectionProtocol]:
        if self._transaction_depth.get() <= 0:
            raise QueryError("`savepoint()` requires an active transaction.")

        connection = self._active_connection.get()
        if connection is None:
            raise QueryError("`savepoint()` requires an active transaction connection.")

        async with connection.transaction():
            depth_token = self._transaction_depth.set(self._transaction_depth.get() + 1)
            try:
                yield connection
            finally:
                self._transaction_depth.reset(depth_token)

    async def execute(self, query: str, *args: Any) -> str:
        start = perf_counter()
        success = False
        try:
            status = await self._run_query(
                query,
                args,
                idempotent=False,
                error_prefix="Failed to execute query",
                runner=lambda connection: connection.execute(query, *args),
            )
            success = True
            self.clear_query_cache()
            return cast(str, status)
        finally:
            self._log_query(query, args, perf_counter() - start, success)

    async def execute_idempotent(self, query: str, *args: Any) -> str:
        start = perf_counter()
        success = False
        try:
            status = await self._run_query(
                query,
                args,
                idempotent=True,
                error_prefix="Failed to execute idempotent query",
                runner=lambda connection: connection.execute(query, *args),
            )
            success = True
            self.clear_query_cache()
            return cast(str, status)
        finally:
            self._log_query(query, args, perf_counter() - start, success)

    async def execute_many(
        self,
        query: str,
        args_list: list[tuple[Any, ...]],
        *,
        idempotent: bool = False,
    ) -> None:
        if not args_list:
            return

        start = perf_counter()
        success = False
        try:
            await self._run_query(
                query,
                tuple(),
                idempotent=idempotent,
                error_prefix="Failed to execute many queries",
                runner=lambda connection: connection.executemany(query, args_list),
            )
            success = True
            self.clear_query_cache()
        finally:
            self._log_query(query, tuple(), perf_counter() - start, success)

    async def fetch_one(self, query: str, *args: Any) -> Any:
        start = perf_counter()
        success = False
        try:
            row = await self._run_query(
                query,
                args,
                idempotent=True,
                error_prefix="Failed to fetch row",
                runner=lambda connection: connection.fetchrow(query, *args),
            )
            success = True
            return row
        finally:
            self._log_query(query, args, perf_counter() - start, success)

    async def fetch_all(self, query: str, *args: Any) -> list[Any]:
        start = perf_counter()
        success = False
        try:
            rows = await self._run_query(
                query,
                args,
                idempotent=True,
                error_prefix="Failed to fetch rows",
                runner=lambda connection: connection.fetch(query, *args),
            )
            success = True
            return list(rows)
        finally:
            self._log_query(query, args, perf_counter() - start, success)

    async def cached_fetch_one(
        self,
        query: str,
        *args: Any,
        ttl_seconds: float,
    ) -> Any:
        if not self._config.enable_query_cache or ttl_seconds <= 0:
            return await self.fetch_one(query, *args)

        key = self._cache_key("one", query, args)
        cached_value = self._get_cached_value(key)
        if cached_value is not self._CACHE_MISS:
            return self._clone_cache_value(cached_value)

        row = await self.fetch_one(query, *args)
        self._set_cached_value(key, row, ttl_seconds)
        return row

    async def cached_fetch_all(
        self,
        query: str,
        *args: Any,
        ttl_seconds: float,
    ) -> list[Any]:
        if not self._config.enable_query_cache or ttl_seconds <= 0:
            return await self.fetch_all(query, *args)

        key = self._cache_key("all", query, args)
        cached_value = self._get_cached_value(key)
        if cached_value is not self._CACHE_MISS:
            cloned = self._clone_cache_value(cached_value)
            return cast(list[Any], cloned)

        rows = await self.fetch_all(query, *args)
        self._set_cached_value(key, rows, ttl_seconds)
        return rows

    def _require_pool(self) -> PoolProtocol:
        if self._pool is None:
            raise DatabaseNotConnectedError(
                "Database pool is not initialized. Call await db.connect() first."
            )
        return self._pool

    async def _run_query(
        self,
        query: str,
        args: tuple[Any, ...],
        *,
        idempotent: bool,
        error_prefix: str,
        runner: Callable[[ConnectionProtocol], Awaitable[Any]],
    ) -> Any:
        attempts = 0

        while True:
            try:
                async with self.connection() as connection:
                    return await self._await_with_timeout(runner(connection))
            except asyncio.CancelledError:
                raise
            except DatabaseNotConnectedError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._should_retry(exc, idempotent=idempotent, attempts=attempts):
                    attempts += 1
                    delay = self._config.idempotent_retry_backoff_seconds * (2 ** (attempts - 1))
                    if delay > 0:
                        await self._sleep_func(delay)
                    continue

                if isinstance(exc, (ConnectionError, QueryError)):
                    raise
                mapped = self._map_integrity_exception(exc)
                if mapped is not None:
                    raise mapped from exc
                raise QueryError(f"{error_prefix}: {exc}") from exc

    async def _await_with_timeout(self, awaitable: Awaitable[Any]) -> Any:
        timeout_seconds = self._config.query_timeout_seconds
        if timeout_seconds is None:
            return await awaitable
        async with asyncio.timeout(timeout_seconds):
            return await awaitable

    def _should_retry(self, exc: Exception, *, idempotent: bool, attempts: int) -> bool:
        if not idempotent:
            return False
        if attempts >= self._config.idempotent_retry_attempts:
            return False
        if isinstance(exc, DatabaseNotConnectedError):
            return False
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        return False

    def _map_integrity_exception(self, exc: Exception) -> IntegrityError | None:
        class_name = exc.__class__.__name__
        message = str(exc)

        if class_name == "UniqueViolationError":
            return UniqueConstraintError(message)
        if class_name == "ForeignKeyViolationError":
            return ForeignKeyConstraintError(message)
        if class_name == "NotNullViolationError":
            return NotNullConstraintError(message)
        if class_name == "CheckViolationError":
            return CheckConstraintError(message)

        return None

    def clear_query_cache(self) -> None:
        self._query_cache.clear()

    def _cache_key(
        self,
        kind: str,
        query: str,
        args: tuple[Any, ...],
    ) -> tuple[str, str, tuple[Any, ...]]:
        return (kind, query, tuple(self._freeze_cache_value(arg) for arg in args))

    def _freeze_cache_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(
                sorted(
                    (
                        str(key),
                        self._freeze_cache_value(item_value),
                    )
                    for key, item_value in value.items()
                )
            )
        if isinstance(value, (list, tuple)):
            return tuple(self._freeze_cache_value(item) for item in value)
        if isinstance(value, set):
            frozen_items = [self._freeze_cache_value(item) for item in value]
            return tuple(sorted(frozen_items, key=repr))
        try:
            hash(value)
            return value
        except TypeError:
            return repr(value)

    def _get_cached_value(self, key: tuple[str, str, tuple[Any, ...]]) -> Any:
        entry = self._query_cache.get(key)
        if entry is None:
            self._cache_misses += 1
            return self._CACHE_MISS

        if entry.expires_at <= self._time_source():
            self._query_cache.pop(key, None)
            self._cache_misses += 1
            return self._CACHE_MISS

        self._cache_hits += 1
        return entry.value

    def _set_cached_value(
        self,
        key: tuple[str, str, tuple[Any, ...]],
        value: Any,
        ttl_seconds: float,
    ) -> None:
        if self._config.query_cache_max_entries <= 0:
            return
        if (
            key not in self._query_cache
            and len(self._query_cache) >= self._config.query_cache_max_entries
        ):
            oldest_key = next(iter(self._query_cache))
            self._query_cache.pop(oldest_key, None)
        self._query_cache[key] = _QueryCacheEntry(
            expires_at=self._time_source() + ttl_seconds,
            value=self._clone_cache_value(value),
        )

    def _clone_cache_value(self, value: Any) -> Any:
        if isinstance(value, list):
            cloned: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    cloned.append(dict(item))
                else:
                    cloned.append(item)
            return cloned
        if isinstance(value, dict):
            return dict(value)
        return value

    def _log_query(
        self,
        query: str,
        args: tuple[Any, ...],
        elapsed_seconds: float,
        success: bool,
    ) -> None:
        elapsed_ms = elapsed_seconds * 1000.0
        is_slow = (
            self._config.slow_query_threshold_ms is not None
            and elapsed_ms >= self._config.slow_query_threshold_ms
        )

        if not self._config.log_sql and not is_slow:
            return

        if self._config.log_sql_parameters:
            logged_args = args
        else:
            logged_args = tuple("<redacted>" for _ in args)

        if self._config.sql_logger is not None:
            self._config.sql_logger(query, logged_args, elapsed_ms, success)
            return

        level = logging.WARNING if is_slow or not success else logging.INFO
        self._fallback_sql_logger.log(
            level,
            "query=%s args=%s duration_ms=%.2f success=%s",
            query,
            logged_args,
            elapsed_ms,
            success,
        )

    @staticmethod
    def _load_default_driver() -> Any | None:
        try:
            return importlib.import_module("asyncpg")
        except ModuleNotFoundError:
            return None

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()
