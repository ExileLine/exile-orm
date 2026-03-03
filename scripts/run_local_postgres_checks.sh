#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.integration.yml"

KEEP_UP=0
RUN_EXAMPLES=1
RUN_INTEGRATION=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-up)
      KEEP_UP=1
      shift
      ;;
    --skip-examples)
      RUN_EXAMPLES=0
      shift
      ;;
    --skip-integration)
      RUN_INTEGRATION=0
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--keep-up] [--skip-examples] [--skip-integration]" >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required." >&2
  exit 1
fi

DB_HOST="127.0.0.1"
DB_PORT="${EXILE_ORM_PG_PORT:-55432}"
DB_USER="${EXILE_ORM_PG_USER:-exile}"
DB_PASSWORD="${EXILE_ORM_PG_PASSWORD:-exile}"
DB_NAME="${EXILE_ORM_PG_DB:-exile_orm_test}"

export DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
export EXILE_ORM_TEST_DATABASE_URL="${DATABASE_URL}"

cleanup() {
  if [[ "${KEEP_UP}" -eq 0 ]]; then
    docker compose -f "${COMPOSE_FILE}" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[1/4] starting local postgres container"
docker compose -f "${COMPOSE_FILE}" up -d

echo "[2/4] waiting for postgres health"
for _ in $(seq 1 120); do
  if docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
  echo "postgres did not become ready in time." >&2
  docker compose -f "${COMPOSE_FILE}" logs postgres >&2 || true
  exit 1
fi
sleep 2

if [[ "${RUN_INTEGRATION}" -eq 1 ]]; then
  echo "[3/4] running integration tests"
  if [[ -x "${ROOT_DIR}/.venv/bin/pytest" ]]; then
    PYTHONPATH="${ROOT_DIR}" "${ROOT_DIR}/.venv/bin/pytest" -m integration
  else
    PYTHONPATH="${ROOT_DIR}" uv run pytest -m integration
  fi
else
  echo "[3/4] integration tests skipped"
fi

if [[ "${RUN_EXAMPLES}" -eq 1 ]]; then
  echo "[4/4] running quick examples"
  PYTHONPATH="${ROOT_DIR}" uv run python "${ROOT_DIR}/examples/db_ping.py"
  PYTHONPATH="${ROOT_DIR}" uv run python "${ROOT_DIR}/examples/model_create_get.py"
  PYTHONPATH="${ROOT_DIR}" uv run python "${ROOT_DIR}/examples/model_many_to_many.py"
  PYTHONPATH="${ROOT_DIR}" uv run python "${ROOT_DIR}/examples/migration_many_to_many.py"
else
  echo "[4/4] examples skipped"
fi

if [[ "${KEEP_UP}" -eq 1 ]]; then
  echo "postgres is still running (requested by --keep-up)."
fi

echo "Local postgres checks completed."
