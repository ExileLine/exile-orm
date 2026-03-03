from __future__ import annotations

import os
import uuid

import pytest

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, ManyToMany, Model, StringField

DATABASE_URL = os.getenv("EXILE_ORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="Set EXILE_ORM_TEST_DATABASE_URL to run integration database tests.",
    ),
]


@pytest.mark.asyncio
async def test_many_to_many_roundtrip_and_reverse_accessor() -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:8]
    tags_table = f"tags_{suffix}"
    posts_table = f"posts_{suffix}"
    through_table = f"post_tags_{suffix}"

    class Tag(Model):
        __table_name__ = tags_table

        id = IntegerField(primary_key=True)
        name = StringField(unique=True)

    class Post(Model):
        __table_name__ = posts_table

        id = IntegerField(primary_key=True)
        title = StringField()
        tags = ManyToMany(
            Tag,
            related_name="posts",
            through=through_table,
            through_source_column="post_id",
            through_target_column="tag_id",
        )

    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    Tag.use_database(db)
    Post.use_database(db)

    try:
        await db.execute(
            f'CREATE TABLE "{tags_table}" ('
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL UNIQUE"
            ")"
        )
        await db.execute(
            f'CREATE TABLE "{posts_table}" ('
            "id SERIAL PRIMARY KEY, "
            "title TEXT NOT NULL"
            ")"
        )
        await db.execute(
            f'CREATE TABLE "{through_table}" ('
            f'"post_id" INTEGER NOT NULL REFERENCES "{posts_table}"("id") ON DELETE CASCADE, '
            f'"tag_id" INTEGER NOT NULL REFERENCES "{tags_table}"("id") ON DELETE CASCADE, '
            'UNIQUE ("post_id", "tag_id")'
            ")"
        )

        post = await Post.create(title="post-1")
        first = await Tag.create(name="first")
        second = await Tag.create(name="second")
        third = await Tag.create(name="third")

        await post.tags.add(first, second.id, second.id)
        linked = await post.tags.all()
        assert sorted(item.name for item in linked) == ["first", "second"]

        reverse_posts = await first.posts.all()
        assert len(reverse_posts) == 1
        assert reverse_posts[0].id == post.id

        await post.tags.remove(first.id)
        after_remove = await post.tags.all()
        assert [item.name for item in after_remove] == ["second"]

        await post.tags.set([third.id])
        after_set = await post.tags.all()
        assert [item.name for item in after_set] == ["third"]

        await post.tags.clear()
        assert await post.tags.all() == []
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{through_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{posts_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{tags_table}"')
        await db.disconnect()
