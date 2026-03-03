from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from exile_orm.core.exceptions import ModelValidationError
from exile_orm.model import ForeignKey, IntegerField, Model, OneToOne, StringField


class FakeDatabase:
    def __init__(self) -> None:
        self.fetch_all_responses: list[list[dict[str, object]]] = []
        self.fetch_all_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_all(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_all_calls.append((query, args))
        if not self.fetch_all_responses:
            return []
        return self.fetch_all_responses.pop(0)

    async def fetch_one(self, query: str, *args: object) -> dict[str, object] | None:
        raise NotImplementedError

    async def execute(self, query: str, *args: object) -> str:
        raise NotImplementedError

    @asynccontextmanager
    async def transaction(self):
        yield self


class Author(Model):
    __table_name__ = "authors"

    id = IntegerField(primary_key=True)
    name = StringField()


class Article(Model):
    __table_name__ = "articles"

    id = IntegerField(primary_key=True)
    title = StringField()
    author = ForeignKey(Author, related_name="articles")


class Profile(Model):
    __table_name__ = "profiles"

    id = IntegerField(primary_key=True)
    bio = StringField()
    user = OneToOne(Author, related_name="profile")


def test_foreign_key_assignment_with_related_instance() -> None:
    author = Author(id=9, name="alice")
    article = Article(id=1, title="hello", author=author)
    assert article._data["author"] == 9
    assert article.author is author

    article.author = 8
    assert article.author == 8


def test_one_to_one_assignment_with_related_instance() -> None:
    author = Author(id=4, name="bob")
    profile = Profile(id=2, bio="hello", user=author)
    assert profile._data["user"] == 4
    assert profile.user is author


def test_one_to_one_requires_unique_constraint() -> None:
    with pytest.raises(ModelValidationError, match="must be unique"):

        class _InvalidProfile(Model):
            __table_name__ = "invalid_profiles"

            id = IntegerField(primary_key=True)
            user = OneToOne(Author, unique=False)


@pytest.mark.asyncio
async def test_select_related_builds_join_and_hydrates_related_model() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {
                "id": 1,
                "title": "hello",
                "author_id": 10,
                "__rel__author__id": 10,
                "__rel__author__name": "alice",
            }
        ]
    ]
    Author.use_database(fake_db)  # type: ignore[arg-type]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    rows = await Article.select_related("author").filter(Article.id > 0).order_by("-id").all()

    assert len(rows) == 1
    assert rows[0].author is not None
    assert rows[0].author.name == "alice"
    assert len(fake_db.fetch_all_calls) == 1
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "t0"."id" AS "id", "t0"."title" AS "title", "t0"."author_id" AS "author_id", '
        '"author__rel"."id" AS "__rel__author__id", "author__rel"."name" AS "__rel__author__name" '
        'FROM "articles" AS "t0" LEFT JOIN "authors" AS "author__rel" '
        'ON "t0"."author_id" = "author__rel"."id" WHERE "t0"."id" > $1 ORDER BY "t0"."id" DESC',
        (0,),
    )


@pytest.mark.asyncio
async def test_prefetch_related_uses_secondary_query() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {"id": 1, "title": "a", "author_id": 7},
            {"id": 2, "title": "b", "author_id": 8},
        ],
        [
            {"id": 7, "name": "u7"},
            {"id": 8, "name": "u8"},
        ],
    ]
    Author.use_database(fake_db)  # type: ignore[arg-type]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    rows = await Article.prefetch_related("author").order_by("id").all()

    assert len(rows) == 2
    assert rows[0].author.name == "u7"
    assert rows[1].author.name == "u8"
    assert len(fake_db.fetch_all_calls) == 2
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "title", "author_id" FROM "articles" ORDER BY "id" ASC',
        (),
    )
    assert fake_db.fetch_all_calls[1] == (
        'SELECT "id", "name" FROM "authors" WHERE "id" IN ($1, $2)',
        (7, 8),
    )


@pytest.mark.asyncio
async def test_prefetch_related_keeps_fixed_sql_count_for_list_queries() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [
        [
            {"id": 1, "title": "a", "author_id": 7},
            {"id": 2, "title": "b", "author_id": 7},
            {"id": 3, "title": "c", "author_id": 8},
        ],
        [
            {"id": 7, "name": "u7"},
            {"id": 8, "name": "u8"},
        ],
    ]
    Author.use_database(fake_db)  # type: ignore[arg-type]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    rows = await Article.prefetch_related("author").order_by("id").all()

    assert [row.author.name for row in rows] == ["u7", "u7", "u8"]
    assert len(fake_db.fetch_all_calls) == 2
    assert fake_db.fetch_all_calls[1] == (
        'SELECT "id", "name" FROM "authors" WHERE "id" IN ($1, $2)',
        (7, 8),
    )


@pytest.mark.asyncio
async def test_reverse_relation_descriptor_returns_queryset() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 11, "title": "post", "author_id": 3}]]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    author = Author(id=3, name="alice")
    rows = await author.articles.order_by("id").all()

    assert len(rows) == 1
    assert rows[0].id == 11
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "title", "author_id" FROM "articles" '
        'WHERE "author_id" = $1 ORDER BY "id" ASC',
        (3,),
    )


@pytest.mark.asyncio
async def test_reverse_one_to_one_descriptor_returns_single_model() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 5, "bio": "bio", "user_id": 3}]]
    Profile.use_database(fake_db)  # type: ignore[arg-type]

    author = Author(id=3, name="alice")
    profile = await author.profile

    assert profile is not None
    assert profile.bio == "bio"
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "bio", "user_id" FROM "profiles" WHERE "user_id" = $1 LIMIT 1',
        (3,),
    )
