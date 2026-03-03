# Quickstart

## 1. Install dependencies

```bash
uv sync --all-extras
```

## 2. Configure database URL

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
```

## 3. Define a model

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

## 4. Run basic CRUD

```python
await db.connect()
user = await User.create(name="alice")
same_user = await User.get(id=user.id)
await db.disconnect()
```

## 5. One-command local verification (Docker)

```bash
./scripts/run_local_postgres_checks.sh
```

This command starts PostgreSQL locally, runs integration tests, and executes
the quick examples (`db_ping`, `model_create_get`, `model_many_to_many`,
`migration_many_to_many`).
