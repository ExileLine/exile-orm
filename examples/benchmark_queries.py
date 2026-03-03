from __future__ import annotations

import argparse
import asyncio
import os
import random
import uuid
from time import perf_counter

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, Model, StringField


class BenchmarkItem(Model):
    __table_name__ = "benchmark_items"

    id = IntegerField(primary_key=True)
    name = StringField()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int((len(sorted_values) - 1) * p)
    return sorted_values[index]


async def run_benchmark(
    db: Database,
    *,
    rows: int,
    ops: int,
    concurrency: int,
    cache_ttl: float | None,
) -> tuple[float, list[float]]:
    durations: list[float] = []
    worker_count = max(1, concurrency)
    ops_per_worker = [ops // worker_count] * worker_count
    for i in range(ops % worker_count):
        ops_per_worker[i] += 1

    async def worker(loop_count: int) -> None:
        for _ in range(loop_count):
            target_id = random.randint(1, rows)
            query = BenchmarkItem.filter(id=target_id)
            if cache_ttl is not None:
                query = query.cache(ttl_seconds=cache_ttl)
            start = perf_counter()
            await query.first()
            durations.append((perf_counter() - start) * 1000.0)

    started_at = perf_counter()
    await asyncio.gather(*(worker(count) for count in ops_per_worker))
    total_seconds = perf_counter() - started_at
    return total_seconds, durations


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run exile-orm query throughput benchmark.")
    parser.add_argument("--dsn", type=str, default=os.getenv("DATABASE_URL"))
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--ops", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--cache-ttl", type=float, default=0.0)
    args = parser.parse_args()

    if not args.dsn:
        raise RuntimeError("Provide --dsn or set DATABASE_URL.")

    cache_ttl: float | None = args.cache_ttl if args.cache_ttl > 0 else None
    config = DatabaseConfig(
        dsn=args.dsn,
        enable_query_cache=cache_ttl is not None,
    )
    db = Database(config)
    await db.connect()

    table_name = f'benchmark_items_{uuid.uuid4().hex[:8]}'
    BenchmarkItem.__table_name__ = table_name
    BenchmarkItem.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{table_name}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL"
            ")"
        )
        await BenchmarkItem.bulk_create([{"name": f"item-{index}"} for index in range(args.rows)])

        total_seconds, durations = await run_benchmark(
            db,
            rows=args.rows,
            ops=args.ops,
            concurrency=args.concurrency,
            cache_ttl=cache_ttl,
        )

        throughput = args.ops / total_seconds if total_seconds > 0 else 0.0
        print(f"table={table_name}")
        print(f"ops={args.ops} concurrency={args.concurrency} rows={args.rows}")
        print(f"cache_ttl={cache_ttl}")
        print(f"total_seconds={total_seconds:.4f}")
        print(f"throughput_ops_per_sec={throughput:.2f}")
        print(f"latency_ms_p50={percentile(durations, 0.5):.2f}")
        print(f"latency_ms_p95={percentile(durations, 0.95):.2f}")
        print(f"cache_hits={db.cache_hits} cache_misses={db.cache_misses}")
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

