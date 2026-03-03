"""Migration execution primitives."""

from __future__ import annotations

from exile_orm.core.database import Database
from exile_orm.migrations.files import MigrationFile

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


async def ensure_migrations_table(db: Database) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ")"
    )


async def get_applied_migrations(db: Database) -> list[tuple[str, str]]:
    rows = await db.fetch_all(
        "SELECT version, name FROM schema_migrations ORDER BY applied_at ASC, version ASC"
    )
    return [(str(row["version"]), str(row["name"])) for row in rows]


async def apply_migration(db: Database, migration: MigrationFile) -> None:
    async with db.transaction():
        for statement in migration.up_sql:
            await db.execute(statement)
        await db.execute(
            "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
            migration.version,
            migration.name,
        )


async def rollback_migration(db: Database, migration: MigrationFile) -> None:
    async with db.transaction():
        for statement in migration.down_sql:
            await db.execute(statement)
        await db.execute(
            "DELETE FROM schema_migrations WHERE version = $1",
            migration.version,
        )

