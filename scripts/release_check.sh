#!/usr/bin/env bash
set -euo pipefail

echo "[1/9] ruff"
.venv/bin/ruff check .

echo "[2/9] mypy"
.venv/bin/mypy exile_orm

echo "[3/9] unit tests"
PYTHONPATH=. .venv/bin/pytest -m "not integration"

echo "[4/9] build artifacts"
rm -rf dist
uv run --with build python -m build

echo "[5/9] twine metadata check"
uv run --with twine twine check dist/*

echo "[6/9] verify py.typed in wheel"
python3 - <<'PY'
import sys
import zipfile
from pathlib import Path

wheels = sorted(Path("dist").glob("*.whl"))
if not wheels:
    print("No wheel produced in dist/", file=sys.stderr)
    raise SystemExit(1)

wheel = wheels[-1]
with zipfile.ZipFile(wheel) as zf:
    names = set(zf.namelist())
if "exile_orm/py.typed" not in names:
    print(f"'exile_orm/py.typed' missing from {wheel.name}", file=sys.stderr)
    raise SystemExit(1)
print(f"Verified py.typed in {wheel.name}")
PY

echo "[7/9] verify required files in sdist"
python3 - <<'PY'
import sys
import tarfile
from pathlib import Path

sdists = sorted(Path("dist").glob("*.tar.gz"))
if not sdists:
    print("No sdist produced in dist/", file=sys.stderr)
    raise SystemExit(1)

sdist = sdists[-1]
required = {
    "exile_orm/py.typed",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
}
with tarfile.open(sdist, mode="r:gz") as tf:
    names = set(tf.getnames())

missing = []
for required_path in sorted(required):
    has_required = any(
        name == required_path or name.endswith(f"/{required_path}")
        for name in names
    )
    if not has_required:
        missing.append(required_path)

if missing:
    print(
        f"Missing files in {sdist.name}: {', '.join(missing)}",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"Verified required files in {sdist.name}")
PY

echo "[8/9] wheel install smoke test"
python3 - <<'PY'
import os
import subprocess
import tempfile
from pathlib import Path

wheels = sorted(Path("dist").glob("*.whl"))
if not wheels:
    raise SystemExit("No wheel produced in dist/")

wheel = wheels[-1]
with tempfile.TemporaryDirectory(prefix="exile_orm_smoke_") as tmp:
    venv_dir = Path(tmp) / "venv"
    python_bin = venv_dir / "bin" / "python"
    subprocess.run(["python3", "-m", "venv", str(venv_dir)], check=True)
    subprocess.run(
        [
            str(python_bin),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "--no-deps", str(wheel)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    subprocess.run(
        [
            str(python_bin),
            "-c",
            "import exile_orm; print('import_ok', exile_orm.__name__)",
        ],
        check=True,
        env=env,
    )
print(f"Smoke install/import passed for {wheel.name}")
PY

echo "[9/9] optional integration tests"
if [[ -n "${EXILE_ORM_TEST_DATABASE_URL:-}" ]]; then
  PYTHONPATH=. .venv/bin/pytest -m integration
else
  echo "Skipped: set EXILE_ORM_TEST_DATABASE_URL to run integration tests."
fi

echo "Release checks passed."
