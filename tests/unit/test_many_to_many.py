from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from exile_orm.core.exceptions import ModelValidationError
from exile_orm.model import IntegerField, ManyToMany, Model, StringField


class FakeDatabase:
    def __init__(self) -> None:
        self.fetch_all_responses: list[list[dict[str, object]]] = []
        self.fetch_all_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_many_calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    async def fetch_all(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_all_calls.append((query, args))
        if not self.fetch_all_responses:
            return []
        return self.fetch_all_responses.pop(0)

    async def execute(self, query: str, *args: object) -> str:
        self.execute_calls.append((query, args))
        return "EXECUTED"

    async def execute_many(self, query: str, args_list: list[tuple[object, ...]]) -> None:
        self.execute_many_calls.append((query, args_list))

    @asynccontextmanager
    async def transaction(self):
        self.transaction_entries += 1
        try:
            yield self
        finally:
            self.transaction_exits += 1


class Tag(Model):
    __table_name__ = "tags"

    id = IntegerField(primary_key=True)
    name = StringField()


class Article(Model):
    __table_name__ = "articles"

    id = IntegerField(primary_key=True)
    title = StringField()
    tags = ManyToMany(
        Tag,
        related_name="articles",
        through="article_tags",
        through_source_column="article_id",
        through_target_column="tag_id",
    )


class Course(Model):
    __table_name__ = "courses"

    id = IntegerField(primary_key=True)
    name = StringField()


class Student(Model):
    __table_name__ = "students"

    id = IntegerField(primary_key=True)
    name = StringField()
    courses = ManyToMany(Course)


@pytest.mark.asyncio
async def test_many_to_many_all_builds_join_query() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 1, "name": "python"}, {"id": 2, "name": "orm"}]]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    article = Article(id=10, title="hello")
    rows = await article.tags.all()

    assert [item.name for item in rows] == ["python", "orm"]
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name" FROM "tags" AS r INNER JOIN "article_tags" AS j '
        'ON r."id" = j."tag_id" WHERE j."article_id" = $1',
        (10,),
    )


@pytest.mark.asyncio
async def test_many_to_many_add_remove_clear_set() -> None:
    fake_db = FakeDatabase()
    Article.use_database(fake_db)  # type: ignore[arg-type]

    article = Article(id=7, title="post")
    await article.tags.add(Tag(id=3, name="x"), 4, 4)
    await article.tags.remove(3, 4)
    await article.tags.clear()
    await article.tags.set([5, 6])

    assert fake_db.execute_many_calls[0] == (
        'INSERT INTO "article_tags" ("article_id", "tag_id") '
        "VALUES ($1, $2) ON CONFLICT DO NOTHING",
        [(7, 3), (7, 4)],
    )
    assert fake_db.execute_calls[0] == (
        'DELETE FROM "article_tags" WHERE "article_id" = $1 AND "tag_id" IN ($2, $3)',
        (7, 3, 4),
    )
    assert fake_db.execute_calls[1] == ('DELETE FROM "article_tags" WHERE "article_id" = $1', (7,))
    assert fake_db.transaction_entries == 1
    assert fake_db.transaction_exits == 1
    assert fake_db.execute_many_calls[1] == (
        'INSERT INTO "article_tags" ("article_id", "tag_id") '
        "VALUES ($1, $2) ON CONFLICT DO NOTHING",
        [(7, 5), (7, 6)],
    )


@pytest.mark.asyncio
async def test_many_to_many_reverse_accessor_works() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 9, "title": "a"}]]
    Article.use_database(fake_db)  # type: ignore[arg-type]

    tag = Tag(id=2, name="tag")
    rows = await tag.articles.all()

    assert len(rows) == 1
    assert rows[0].title == "a"
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "title" FROM "articles" AS r INNER JOIN "article_tags" AS j '
        'ON r."id" = j."article_id" WHERE j."tag_id" = $1',
        (2,),
    )


@pytest.mark.asyncio
async def test_many_to_many_default_through_and_columns() -> None:
    fake_db = FakeDatabase()
    fake_db.fetch_all_responses = [[{"id": 1, "name": "math"}]]
    Student.use_database(fake_db)  # type: ignore[arg-type]

    student = Student(id=3, name="s")
    rows = await student.courses.all()

    assert len(rows) == 1
    assert fake_db.fetch_all_calls[0] == (
        'SELECT "id", "name" FROM "courses" AS r INNER JOIN "students_courses" AS j '
        'ON r."id" = j."course_id" WHERE j."student_id" = $1',
        (3,),
    )


@pytest.mark.asyncio
async def test_many_to_many_requires_owner_primary_key() -> None:
    fake_db = FakeDatabase()
    Article.use_database(fake_db)  # type: ignore[arg-type]

    article = Article(title="unsaved")
    with pytest.raises(ModelValidationError, match="primary key"):
        await article.tags.all()
