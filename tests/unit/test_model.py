from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from exile_orm.core.exceptions import ModelNotFoundError, ModelValidationError
from exile_orm.model import BooleanField, IntegerField, Model, StringField


class FakeDatabase:
    def __init__(self) -> None:
        self.fetch_one_responses: list[dict[str, object] | None] = []
        self.fetch_all_responses: list[list[dict[str, object]]] = []
        self.execute_responses: list[str] = []
        self.fetch_one_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetch_all_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    async def fetch_one(self, query: str, *args: object) -> dict[str, object] | None:
        self.fetch_one_calls.append((query, args))
        if not self.fetch_one_responses:
            return None
        return self.fetch_one_responses.pop(0)

    async def execute(self, query: str, *args: object) -> str:
        self.execute_calls.append((query, args))
        if self.execute_responses:
            return self.execute_responses.pop(0)
        return "UPDATE 1"

    async def fetch_all(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_all_calls.append((query, args))
        if not self.fetch_all_responses:
            return []
        return self.fetch_all_responses.pop(0)

    @asynccontextmanager
    async def transaction(self):
        self.transaction_entries += 1
        try:
            yield self
        finally:
            self.transaction_exits += 1


class User(Model):
    __table_name__ = "users"

    id = IntegerField(primary_key=True)
    name = StringField()
    is_active = BooleanField(default=True)


def test_model_metadata_collection() -> None:
    assert User.__table_name__ == "users"
    assert tuple(User.__fields__.keys()) == ("id", "name", "is_active")
    assert User.__primary_key__ is User.__fields__["id"]


@pytest.mark.asyncio
async def test_create_builds_parameterized_insert_sql() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_one_responses = [{"id": 1, "name": "alice", "is_active": True}]
    User.use_database(fake_db)  # type: ignore[arg-type]

    user = await User.create(name="alice")

    assert user.id == 1
    assert user.name == "alice"
    assert user.is_active is True
    assert fake_db.fetch_one_calls[0] == (
        'INSERT INTO "users" ("name", "is_active") VALUES ($1, $2) '
        'RETURNING "id", "name", "is_active"',
        ("alice", True),
    )


@pytest.mark.asyncio
async def test_get_returns_model_instance() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 2, "name": "bob", "is_active": False}]]
    User.use_database(fake_db)  # type: ignore[arg-type]

    user = await User.get(name="bob")

    assert user.id == 2
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name", "is_active" FROM "users" WHERE "name" = $1 LIMIT 2',
        ("bob",),
    )


@pytest.mark.asyncio
async def test_get_raises_when_no_row_found() -> None:
    fake_db = FakeDatabase()
    User.use_database(fake_db)  # type: ignore[arg-type]

    with pytest.raises(ModelNotFoundError):
        await User.get(name="missing")


@pytest.mark.asyncio
async def test_save_updates_dirty_fields_only() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_one_responses = [{"id": 3, "name": "new", "is_active": True}]
    User.use_database(fake_db)  # type: ignore[arg-type]

    user = User(id=3, name="old")
    user.name = "new"
    await user.save()

    assert fake_db.fetch_one_calls[0] == (
        'UPDATE "users" SET "name" = $1 WHERE "id" = $2 RETURNING "id", "name", "is_active"',
        ("new", 3),
    )
    assert user.name == "new"


@pytest.mark.asyncio
async def test_delete_uses_primary_key() -> None:
    fake_db = FakeDatabase()
    User.use_database(fake_db)  # type: ignore[arg-type]

    user = User(id=10, name="to-delete")
    await user.delete()

    assert fake_db.execute_calls[0] == ('DELETE FROM "users" WHERE "id" = $1', (10,))


def test_unknown_field_raises_validation_error() -> None:
    with pytest.raises(ModelValidationError):
        User(unknown="x")


@pytest.mark.asyncio
async def test_bulk_create_builds_multi_values_insert() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {"id": 1, "name": "a", "is_active": True},
            {"id": 2, "name": "b", "is_active": False},
        ]
    ]
    User.use_database(fake_db)  # type: ignore[arg-type]

    created = await User.bulk_create(
        [
            {"name": "a", "is_active": True},
            {"name": "b", "is_active": False},
        ]
    )

    assert [item.id for item in created] == [1, 2]
    assert fake_db.fetch_all_calls[0] == (
        'INSERT INTO "users" ("name", "is_active") VALUES ($1, $2), ($3, $4) '
        'RETURNING "id", "name", "is_active"',
        ("a", True, "b", False),
    )


@pytest.mark.asyncio
async def test_bulk_create_with_batch_size_splits_into_chunks() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {"id": 1, "name": "a", "is_active": True},
            {"id": 2, "name": "b", "is_active": True},
        ],
        [{"id": 3, "name": "c", "is_active": False}],
    ]
    User.use_database(fake_db)  # type: ignore[arg-type]

    created = await User.bulk_create(
        [
            {"name": "a"},
            {"name": "b"},
            {"name": "c", "is_active": False},
        ],
        batch_size=2,
    )

    assert [item.id for item in created] == [1, 2, 3]
    assert len(fake_db.fetch_all_calls) == 2
    assert fake_db.fetch_all_calls[0] == (
        'INSERT INTO "users" ("name", "is_active") VALUES ($1, $2), ($3, $4) '
        'RETURNING "id", "name", "is_active"',
        ("a", True, "b", True),
    )
    assert fake_db.fetch_all_calls[1] == (
        'INSERT INTO "users" ("name", "is_active") VALUES ($1, $2) '
        'RETURNING "id", "name", "is_active"',
        ("c", False),
    )


@pytest.mark.asyncio
async def test_bulk_update_uses_transaction() -> None:
    fake_db = FakeDatabase()
    User.use_database(fake_db)  # type: ignore[arg-type]

    first = User(id=1, name="a")
    second = User(id=2, name="b")
    first.name = "a1"
    second.name = "b1"

    updated = await User.bulk_update([first, second])

    assert updated == 2
    assert fake_db.transaction_entries == 1
    assert fake_db.transaction_exits == 1
    assert fake_db.execute_calls[0] == ('UPDATE "users" SET "name" = $1 WHERE "id" = $2', ("a1", 1))
    assert fake_db.execute_calls[1] == ('UPDATE "users" SET "name" = $1 WHERE "id" = $2', ("b1", 2))


@pytest.mark.asyncio
async def test_bulk_update_batch_size_uses_multiple_transactions() -> None:
    fake_db = FakeDatabase()
    User.use_database(fake_db)  # type: ignore[arg-type]

    first = User(id=1, name="a")
    second = User(id=2, name="b")
    third = User(id=3, name="c")
    first.name = "a1"
    second.name = "b1"
    third.name = "c1"

    updated = await User.bulk_update([first, second, third], batch_size=2)

    assert updated == 3
    assert fake_db.transaction_entries == 2
    assert fake_db.transaction_exits == 2
    assert len(fake_db.execute_calls) == 3


@pytest.mark.asyncio
async def test_bulk_delete_by_instances_and_filters() -> None:
    fake_db = FakeDatabase()
    fake_db.execute_responses = ["DELETE 2", "DELETE 3"]
    User.use_database(fake_db)  # type: ignore[arg-type]

    first = User(id=10, name="a")
    second = User(id=11, name="b")

    deleted_by_instances = await User.bulk_delete([first, second])
    deleted_by_filter = await User.bulk_delete(is_active=True)

    assert deleted_by_instances == 2
    assert deleted_by_filter == 3
    assert fake_db.execute_calls[0] == (
        'DELETE FROM "users" WHERE "id" IN ($1, $2)',
        (10, 11),
    )
    assert fake_db.execute_calls[1] == (
        'DELETE FROM "users" WHERE "is_active" = $1',
        (True,),
    )


@pytest.mark.asyncio
async def test_bulk_delete_with_batch_size() -> None:
    fake_db = FakeDatabase()
    fake_db.execute_responses = ["DELETE 2", "DELETE 1"]
    User.use_database(fake_db)  # type: ignore[arg-type]

    rows = [User(id=1, name="a"), User(id=2, name="b"), User(id=3, name="c")]
    deleted = await User.bulk_delete(rows, batch_size=2)

    assert deleted == 3
    assert fake_db.execute_calls[0] == ('DELETE FROM "users" WHERE "id" IN ($1, $2)', (1, 2))
    assert fake_db.execute_calls[1] == ('DELETE FROM "users" WHERE "id" IN ($1)', (3,))


@pytest.mark.asyncio
async def test_bulk_batch_size_validation() -> None:
    fake_db = FakeDatabase()
    User.use_database(fake_db)  # type: ignore[arg-type]

    with pytest.raises(ModelValidationError, match="batch_size"):
        await User.bulk_create([{"name": "a"}], batch_size=0)
    with pytest.raises(ModelValidationError, match="batch_size"):
        await User.bulk_update([User(id=1, name="a")], batch_size=0)
    with pytest.raises(ModelValidationError, match="batch_size"):
        await User.bulk_delete([User(id=1, name="a")], batch_size=0)
