# exile-orm Architecture (MVP)

## Scope

- Language/runtime: Python 3.11+
- ORM style: native async (`async`/`await`)
- First target backend: PostgreSQL
- Driver: `asyncpg`

## Module responsibilities

- `exile_orm/core/`
  - connection pool lifecycle
  - connection/transaction context managers
  - unified ORM exceptions
- `exile_orm/model/`
  - model base class
  - fields and metadata collection (next phase)
- `exile_orm/query/`
  - expression objects
  - SQL builder and QuerySet API (next phase)
- `exile_orm/backends/`
  - backend-specific SQL dialect adapters (PostgreSQL first)

## MVP boundaries

- Must support:
  - database `connect/disconnect`
  - query execution (`execute/fetch_one/fetch_all`)
  - async transaction context (`async with db.transaction()`)
- Out of MVP:
  - relationships
  - migrations
  - cross-database compatibility

