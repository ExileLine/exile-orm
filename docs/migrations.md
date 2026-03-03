# Migrations

## Overview

The migration system includes:

- Schema snapshots (`schema_snapshot.json`)
- SQL diff planning (`create/add/drop/alter/index`)
- Version files (`migrations/versions/*.json`)
- Runtime apply/rollback with `schema_migrations` tracking

`ManyToMany` relations are included in snapshots as explicit join tables. During
`makemigrations`, the planner will emit `CREATE TABLE` and index SQL for those
join tables automatically.

## Generate migration files

```python
from pathlib import Path

from exile_orm import makemigrations

makemigrations(
    models=[User, Author, Article],
    name="add_article_table",
    snapshot_path=Path("migrations/schema_snapshot.json"),
    migrations_dir=Path("migrations/versions"),
)
```

## Apply migrations

```python
from pathlib import Path

from exile_orm import migrate

applied_versions = await migrate(
    db,
    migrations_dir=Path("migrations/versions"),
)
```

## Rollback migrations

```python
from pathlib import Path

from exile_orm import rollback

rolled_back_versions = await rollback(
    db,
    migrations_dir=Path("migrations/versions"),
    steps=1,
)
```

## Runnable demo

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run python examples/migration_many_to_many.py
```
