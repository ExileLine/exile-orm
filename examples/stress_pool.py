from __future__ import annotations

import argparse
import asyncio
import os
from time import perf_counter

from exile_orm.core.database import Database, DatabaseConfig


async def main() -> None:
    parser = argparse.ArgumentParser(description="Stress test exile-orm connection pool usage.")
    parser.add_argument("--dsn", type=str, default=os.getenv("DATABASE_URL"))
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--queries-per-worker", type=int, default=50)
    parser.add_argument("--min-size", type=int, default=1)
    parser.add_argument("--max-size", type=int, default=20)
    args = parser.parse_args()

    if not args.dsn:
        raise RuntimeError("Provide --dsn or set DATABASE_URL.")

    db = Database(
        DatabaseConfig(
            dsn=args.dsn,
            min_size=args.min_size,
            max_size=args.max_size,
        )
    )
    await db.connect()

    async def worker() -> None:
        for _ in range(args.queries_per_worker):
            await db.fetch_one("SELECT 1 AS value")

    total_queries = args.workers * args.queries_per_worker
    started_at = perf_counter()
    await asyncio.gather(*(worker() for _ in range(args.workers)))
    elapsed = perf_counter() - started_at
    await db.disconnect()

    throughput = total_queries / elapsed if elapsed > 0 else 0.0
    print(f"workers={args.workers}")
    print(f"queries_per_worker={args.queries_per_worker}")
    print(f"total_queries={total_queries}")
    print(f"elapsed_seconds={elapsed:.4f}")
    print(f"throughput_qps={throughput:.2f}")
    print(f"acquire_count={db.acquire_count}")
    print(f"release_count={db.release_count}")
    print(f"peak_in_use_connections={db.peak_in_use_connections}")
    print(f"in_use_connections_after={db.in_use_connections}")
    print(f"leak_free={db.in_use_connections == 0 and db.acquire_count == db.release_count}")


if __name__ == "__main__":
    asyncio.run(main())

