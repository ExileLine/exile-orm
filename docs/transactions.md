# Transactions

## Transaction context

```python
async with db.transaction():
    await User.create(name="alice")
    await User.create(name="bob")
```

## Savepoint (nested transaction)

```python
async with db.transaction():
    await User.create(name="outer")
    async with db.savepoint():
        await User.create(name="inner")
```

## Timeout and retry configuration

```python
from exile_orm.core.database import DatabaseConfig

config = DatabaseConfig(
    dsn="postgresql://...",
    query_timeout_seconds=2.0,
    idempotent_retry_attempts=2,
    idempotent_retry_backoff_seconds=0.05,
)
```

## Idempotent retry execution

```python
await db.execute_idempotent("VACUUM")
```
