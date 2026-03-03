from __future__ import annotations

import pytest

from exile_orm.core.exceptions import QueryError
from exile_orm.model import BooleanField, IntegerField, Model, StringField


class FakeDatabase:
    def __init__(self) -> None:
        self.fetch_one_responses: list[dict[str, object] | None] = []
        self.fetch_all_responses: list[list[dict[str, object]]] = []
        self.fetch_one_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetch_all_calls: list[tuple[str, tuple[object, ...]]] = []
        self.cached_fetch_one_calls: list[tuple[str, tuple[object, ...], float]] = []
        self.cached_fetch_all_calls: list[tuple[str, tuple[object, ...], float]] = []

    async def fetch_one(self, query: str, *args: object) -> dict[str, object] | None:
        self.fetch_one_calls.append((query, args))
        if not self.fetch_one_responses:
            return None
        return self.fetch_one_responses.pop(0)

    async def fetch_all(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_all_calls.append((query, args))
        if not self.fetch_all_responses:
            return []
        return self.fetch_all_responses.pop(0)

    async def cached_fetch_one(
        self,
        query: str,
        *args: object,
        ttl_seconds: float,
    ) -> dict[str, object] | None:
        self.cached_fetch_one_calls.append((query, args, ttl_seconds))
        return await self.fetch_one(query, *args)

    async def cached_fetch_all(
        self,
        query: str,
        *args: object,
        ttl_seconds: float,
    ) -> list[dict[str, object]]:
        self.cached_fetch_all_calls.append((query, args, ttl_seconds))
        return await self.fetch_all(query, *args)


class Item(Model):
    __table_name__ = "items"

    id = IntegerField(primary_key=True)
    name = StringField()
    price = IntegerField()
    is_active = BooleanField(default=True)


@pytest.mark.asyncio
async def test_filter_order_limit_offset_all_builds_sql() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 1, "name": "book", "price": 99, "is_active": True}]]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    items = await (
        Item.filter(Item.price > 10, name="book")
        .order_by("-id", "name")
        .limit(20)
        .offset(5)
        .all()
    )

    assert len(items) == 1
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name", "price", "is_active" FROM "items" '
        'WHERE ("price" > $1 AND "name" = $2) ORDER BY "id" DESC, "name" ASC LIMIT 20 OFFSET 5',
        (10, "book"),
    )


@pytest.mark.asyncio
async def test_count_exists_and_first() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_one_responses = [{"count": 3}, {"exists_flag": 1}]
    fake_db.fetch_all_responses = [[{"id": 9, "name": "box", "price": 1, "is_active": True}]]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    count = await Item.filter(Item.is_active == True).count()  # noqa: E712
    exists = await Item.filter(Item.price >= 1).exists()
    first = await Item.order_by("id").first()

    assert count == 3
    assert exists is True
    assert first is not None
    assert first.id == 9

    assert fake_db.fetch_one_calls[0] == (
        'SELECT COUNT(*) AS count FROM "items" WHERE "is_active" = $1',
        (True,),
    )
    assert fake_db.fetch_one_calls[1] == (
        'SELECT 1 AS exists_flag FROM "items" WHERE "price" >= $1 LIMIT 1',
        (1,),
    )
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name", "price", "is_active" FROM "items" ORDER BY "id" ASC LIMIT 1',
        (),
    )


@pytest.mark.asyncio
async def test_expression_or_and_like() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 2, "name": "alice", "price": 20, "is_active": True}]]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    condition = (Item.price > 10) | Item.name.like("a%")
    await Item.filter(condition).all()

    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name", "price", "is_active" FROM "items" '
        'WHERE ("price" > $1 OR "name" LIKE $2)',
        (10, "a%"),
    )


@pytest.mark.asyncio
async def test_in_condition_and_empty_in_condition() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [{"id": 1, "name": "x", "price": 2, "is_active": True}],
        [],
    ]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    await Item.filter(Item.id.in_([1, 2, 3])).all()
    await Item.filter(Item.id.in_([])).all()

    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name", "price", "is_active" FROM "items" WHERE "id" IN ($1, $2, $3)',
        (1, 2, 3),
    )
    assert fake_db.fetch_all_calls[1] == (
        'SELECT "id", "name", "price", "is_active" FROM "items" WHERE FALSE',
        (),
    )


@pytest.mark.asyncio
async def test_get_raises_when_multiple_rows() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {"id": 1, "name": "dupe", "price": 2, "is_active": True},
            {"id": 2, "name": "dupe", "price": 3, "is_active": True},
        ]
    ]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    with pytest.raises(QueryError):
        await Item.filter(name="dupe").get()


@pytest.mark.asyncio
async def test_cache_uses_cached_fetch_methods() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 1, "name": "cached", "price": 5, "is_active": True}]]
    fake_db.fetch_one_responses = [{"count": 1}]
    Item.use_database(fake_db)  # type: ignore[arg-type]

    rows = await Item.filter(name="cached").cache(ttl_seconds=30.0).all()
    total = await Item.filter(name="cached").cache(ttl_seconds=30.0).count()

    assert len(rows) == 1
    assert total == 1
    assert fake_db.cached_fetch_all_calls[0][2] == 30.0
    assert fake_db.cached_fetch_one_calls[0][2] == 30.0
