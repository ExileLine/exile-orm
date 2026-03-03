"""High-level migration commands."""

from __future__ import annotations

from pathlib import Path

from exile_orm.core.database import Database
from exile_orm.migrations.executor import (
    apply_migration,
    ensure_migrations_table,
    get_applied_migrations,
    rollback_migration,
)
from exile_orm.migrations.files import (
    MigrationFile,
    generate_version,
    list_migration_files,
    read_migration_file,
    sanitize_name,
    write_migration_file,
)
from exile_orm.migrations.planner import plan_migration
from exile_orm.migrations.schema import load_snapshot, save_snapshot, snapshot_from_models
from exile_orm.model.base import Model


def default_snapshot_path(project_root: Path | None = None) -> Path:
    root = Path.cwd() if project_root is None else project_root
    return root / "migrations" / "schema_snapshot.json"


def default_migrations_dir(project_root: Path | None = None) -> Path:
    root = Path.cwd() if project_root is None else project_root
    return root / "migrations" / "versions"


def makemigrations(
    models: list[type[Model]],
    *,
    name: str = "auto",
    snapshot_path: Path | None = None,
    migrations_dir: Path | None = None,
) -> MigrationFile | None:
    snapshot_file = default_snapshot_path() if snapshot_path is None else snapshot_path
    versions_dir = default_migrations_dir() if migrations_dir is None else migrations_dir

    before = load_snapshot(snapshot_file)
    after = snapshot_from_models(models)
    plan = plan_migration(before, after)

    save_snapshot(snapshot_file, after)
    if not plan.up_sql and not plan.down_sql:
        return None

    migration = MigrationFile(
        version=generate_version(),
        name=sanitize_name(name),
        up_sql=plan.up_sql,
        down_sql=plan.down_sql,
    )
    write_migration_file(versions_dir, migration)
    return migration


def load_migrations(migrations_dir: Path | None = None) -> list[MigrationFile]:
    versions_dir = default_migrations_dir() if migrations_dir is None else migrations_dir
    paths = list_migration_files(versions_dir)
    migrations = [read_migration_file(path) for path in paths]
    return sorted(migrations, key=lambda item: item.version)


async def migrate(
    db: Database,
    *,
    migrations_dir: Path | None = None,
    to_version: str | None = None,
) -> list[str]:
    await ensure_migrations_table(db)
    migrations = load_migrations(migrations_dir)
    applied = {version for version, _ in await get_applied_migrations(db)}

    applied_now: list[str] = []
    for migration in migrations:
        if to_version is not None and migration.version > to_version:
            break
        if migration.version in applied:
            continue
        await apply_migration(db, migration)
        applied_now.append(migration.version)
    return applied_now


async def rollback(
    db: Database,
    *,
    migrations_dir: Path | None = None,
    steps: int = 1,
    to_version: str | None = None,
) -> list[str]:
    if steps < 1:
        return []

    await ensure_migrations_table(db)
    migrations = load_migrations(migrations_dir)
    by_version = {migration.version: migration for migration in migrations}

    applied_versions = [version for version, _ in await get_applied_migrations(db)]
    if to_version is not None:
        targets = [version for version in applied_versions if version > to_version]
    else:
        targets = applied_versions[-steps:]

    rolled_back: list[str] = []
    for version in reversed(targets):
        migration = by_version.get(version)
        if migration is None:
            raise ValueError(f"Migration file for applied version '{version}' was not found.")
        await rollback_migration(db, migration)
        rolled_back.append(version)

    return rolled_back

