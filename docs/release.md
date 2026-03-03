# Release Guide

## 1. Validate workspace

```bash
./scripts/release_check.sh
```

This script runs:

- lint + type check
- unit tests
- package build
- `twine check dist/*`
- `py.typed` artifact verification
- required files verification in `sdist` (`py.typed`/README/changelog/license)
- wheel install/import smoke test
- optional integration tests (when `EXILE_ORM_TEST_DATABASE_URL` is set)

CI also runs integration tests with a PostgreSQL service container on each PR/push.

If you do not already have a test database, run:

```bash
./scripts/run_local_postgres_checks.sh --skip-examples
```

## 2. Update metadata

```bash
python3 scripts/bump_version.py patch
# or: minor / major
```

This updates:

- `[project].version` in `pyproject.toml`
- a release section in `CHANGELOG.md`

## 3. Build package (manual)

```bash
uv run python -m build
```

## 4. Verify artifact contains typing marker

Ensure built wheel includes `exile_orm/py.typed`.

## 5. Publish

Upload distributions from `dist/` using your package publishing workflow.
