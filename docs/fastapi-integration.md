# FastAPI Integration

## Install

```bash
uv add fastapi uvicorn
```

## Example app

See [`examples/fastapi_app.py`](/Users/yangyuexiong/Desktop/exile-orm/examples/fastapi_app.py).

## Run

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/dbname"
uv run uvicorn examples.fastapi_app:app --reload
```
