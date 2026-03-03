# exile-orm

Native async ORM framework for Python.

## Docs

- [Architecture](/Users/yangyuexiong/Desktop/exile-orm/docs/architecture.md)
- [Quickstart](/Users/yangyuexiong/Desktop/exile-orm/docs/quickstart.md)
- [Models](/Users/yangyuexiong/Desktop/exile-orm/docs/models.md)
- [Query API](/Users/yangyuexiong/Desktop/exile-orm/docs/query-api.md)
- [Transactions](/Users/yangyuexiong/Desktop/exile-orm/docs/transactions.md)
- [Migrations](/Users/yangyuexiong/Desktop/exile-orm/docs/migrations.md)
- [FastAPI Integration](/Users/yangyuexiong/Desktop/exile-orm/docs/fastapi-integration.md)
- [Release Guide](/Users/yangyuexiong/Desktop/exile-orm/docs/release.md)

## Release check

```bash
./scripts/release_check.sh
python3 scripts/bump_version.py patch
```

## Development bootstrap

```bash
uv sync --all-extras
```

## Run tests

```bash
PYTHONPATH=. uv run pytest
```

Integration test requires a PostgreSQL DSN:

```bash
export EXILE_ORM_TEST_DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
PYTHONPATH=. uv run pytest -m integration
```

Run everything locally with Docker (integration tests + quick examples):

```bash
./scripts/run_local_postgres_checks.sh
```

GitHub Actions CI also runs `pytest -m integration` against a PostgreSQL service.

## Quick ping example

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run python examples/db_ping.py
```

## Minimal model example

```python
from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, Model, StringField


class User(Model):
    __table_name__ = "users"
    id = IntegerField(primary_key=True)
    name = StringField()


db = Database(DatabaseConfig(dsn="postgresql://..."))
User.use_database(db)
```

End-to-end create/get demo:

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run python examples/model_create_get.py
uv run python examples/model_many_to_many.py
uv run python examples/migration_many_to_many.py
```

## Query builder example

```python
adults = await User.filter(User.id > 10).order_by("-id").limit(20).all()
exists = await User.filter(name="alice").exists()
count = await User.filter(User.name.like("a%")).count()
cached = await User.filter(name="alice").cache(ttl_seconds=30).all()
```

## Relations example

```python
from exile_orm.model import ForeignKey, ManyToMany, OneToOne


class Author(Model):
    id = IntegerField(primary_key=True)
    name = StringField()


class Article(Model):
    id = IntegerField(primary_key=True)
    title = StringField()
    author = ForeignKey(Author, related_name="articles")
    tags = ManyToMany(
        lambda: Tag,
        related_name="articles",
        through="article_tags",
        through_source_column="article_id",
        through_target_column="tag_id",
    )


class AuthorProfile(Model):
    id = IntegerField(primary_key=True)
    bio = StringField()
    author = OneToOne(Author, related_name="profile")


class Tag(Model):
    id = IntegerField(primary_key=True)
    name = StringField()


rows = await Article.select_related("author").all()      # join preloading
rows = await Article.prefetch_related("author").all()    # batched preloading
child_rows = await author.articles.all()                 # reverse one-to-many
profile = await author.profile                           # reverse one-to-one
tags = await article.tags.all()                          # many-to-many
```

`ManyToMany` requires an explicit join table (for example `article_tags`) managed via migrations.

## Bulk operations example

```python
rows = await User.bulk_create([{"name": "a"}, {"name": "b"}])
rows[0].name = "a1"
rows[1].name = "b1"
await User.bulk_update(rows, fields=["name"])
await User.bulk_delete(rows)

# chunk/batch execution for large writes
rows = await User.bulk_create(large_rows, batch_size=1000)
await User.bulk_update(rows, fields=["name"], batch_size=500)
await User.bulk_delete(rows, batch_size=500)
```

## SQL logging example

```python
config = DatabaseConfig(
    dsn="postgresql://...",
    log_sql=True,
    log_sql_parameters=False,  # default: redact parameters
    slow_query_threshold_ms=200,
    enable_query_cache=True,
    query_cache_max_entries=2048,
    query_timeout_seconds=2.0,
    idempotent_retry_attempts=2,
    idempotent_retry_backoff_seconds=0.05,
)
db = Database(config)
```

Idempotent SQL can be retried explicitly:

```python
await db.execute_idempotent("VACUUM")
await db.execute_many(
    "INSERT INTO logs (level, message) VALUES ($1, $2)",
    [("INFO", "a"), ("INFO", "b")],
)
```

Constraint violations are mapped to domain errors:

- `UniqueConstraintError`
- `ForeignKeyConstraintError`
- `NotNullConstraintError`
- `CheckConstraintError`

## Migration commands (Python API)

```python
from pathlib import Path

from exile_orm import makemigrations, migrate, rollback

# 1) generate migration files from current model definitions
makemigrations(
    models=[User, Author, Article],
    name="add_article_table",
    snapshot_path=Path("migrations/schema_snapshot.json"),
    migrations_dir=Path("migrations/versions"),
)

# 2) apply unapplied migrations
await migrate(db, migrations_dir=Path("migrations/versions"))

# 3) rollback last migration
await rollback(db, migrations_dir=Path("migrations/versions"), steps=1)
```

## Benchmark script

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run python examples/benchmark_queries.py --rows 1000 --ops 5000 --concurrency 20
uv run python examples/benchmark_queries.py --rows 1000 --ops 5000 --concurrency 20 --cache-ttl 30
uv run python examples/stress_pool.py --workers 100 --queries-per-worker 50 --max-size 20
```

## FastAPI example

```bash
uv add fastapi uvicorn
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run uvicorn examples.fastapi_app:app --reload
```
