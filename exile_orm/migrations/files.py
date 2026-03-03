"""Migration file IO utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MigrationFile:
    version: str
    name: str
    up_sql: list[str]
    down_sql: list[str]

    @property
    def filename(self) -> str:
        return f"{self.version}_{self.name}.json"

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "name": self.name,
            "up_sql": self.up_sql,
            "down_sql": self.down_sql,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> MigrationFile:
        up_sql_raw = payload.get("up_sql", [])
        down_sql_raw = payload.get("down_sql", [])
        up_sql_values = up_sql_raw if isinstance(up_sql_raw, list) else []
        down_sql_values = down_sql_raw if isinstance(down_sql_raw, list) else []
        return cls(
            version=str(payload["version"]),
            name=str(payload["name"]),
            up_sql=[str(item) for item in up_sql_values],
            down_sql=[str(item) for item in down_sql_values],
        )


def generate_version() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S%f")


def sanitize_name(name: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or "auto"


def write_migration_file(migrations_dir: Path, migration: MigrationFile) -> Path:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    path = migrations_dir / migration.filename
    path.write_text(json.dumps(migration.to_dict(), ensure_ascii=True, indent=2) + "\n")
    return path


def read_migration_file(path: Path) -> MigrationFile:
    payload = json.loads(path.read_text())
    return MigrationFile.from_dict(payload)


def list_migration_files(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.exists():
        return []
    return sorted(path for path in migrations_dir.glob("*.json") if path.is_file())
