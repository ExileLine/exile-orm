# Changelog

All notable changes to this project are documented in this file.
## [0.2.0] - 2026-03-03

### Added

- Relationship system expansion:
  - `OneToOne` field and reverse one-to-one accessor.
  - `ManyToMany` field with manager API: `all/add/remove/clear/set`.
  - reverse many-to-many accessor support.
- Migration support for many-to-many:
  - schema snapshot auto-includes explicit join tables.
  - planner now respects foreign-key dependency order for create/drop.
- Integration test coverage expansion:
  - many-to-many CRUD roundtrip.
  - migration -> apply -> rollback end-to-end with many-to-many models.
  - connection-pool stability integration test scaffold.
- Developer experience upgrades:
  - new many-to-many runnable example: `examples/model_many_to_many.py`.
  - local Docker-based verification workflow:
    - `docker-compose.integration.yml`
    - `scripts/run_local_postgres_checks.sh`


## [0.1.0] - 2026-03-03

### Added

- Async database core with pooling, query execution, transactions, savepoints.
- SQL logging, slow-query tracking, timeout and idempotent retry policy.
- Native model layer: fields, metadata, CRUD, bulk operations with batch support.
- QuerySet API with expressions, filtering, sorting, pagination, count/exists/get.
- Relationship support: `ForeignKey`, `select_related`, `prefetch_related`, reverse accessors.
- Migration system: schema snapshot, diff planning, migration files, apply/rollback.
- Query cache (explicit TTL), cache metrics, and cache invalidation on writes.
- Benchmark and stress scripts:
  - `examples/benchmark_queries.py`
  - `examples/stress_pool.py`
- Documentation set under `docs/`.

### Quality

- Type checking (`mypy --strict`) support and `py.typed` marker.
- Linting (`ruff`) and automated tests (`pytest`).
