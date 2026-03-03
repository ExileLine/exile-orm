from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, Model, StringField


class User(Model):
    __table_name__ = "users"

    id = IntegerField(primary_key=True)
    name = StringField()


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL before starting the FastAPI app.")

db = Database(DatabaseConfig(dsn=DATABASE_URL))
User.use_database(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    try:
        yield
    finally:
        await db.disconnect()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    row = await db.fetch_one("SELECT 1 AS value")
    if row is None:
        raise HTTPException(status_code=500, detail="database_unreachable")
    return {"status": "ok"}


@app.get("/users/{user_id}")
async def get_user(user_id: int) -> dict[str, object]:
    user = await User.filter(id=user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user.to_dict()

