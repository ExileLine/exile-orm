from __future__ import annotations

import asyncio
import os
import uuid

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, ManyToMany, Model, StringField


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL first.")

    suffix = uuid.uuid4().hex[:8]
    posts_table = f"demo_posts_{suffix}"
    tags_table = f"demo_tags_{suffix}"
    through_table = f"demo_post_tags_{suffix}"

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

    db = Database(DatabaseConfig(dsn=dsn))
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

        post = await Post.create(title="hello")
        python = await Tag.create(name="python")
        orm = await Tag.create(name="orm")
        await post.tags.add(python, orm.id)

        tag_names = [tag.name for tag in await post.tags.all()]
        post_titles = [item.title for item in await python.posts.all()]
        print(f"post_tags={sorted(tag_names)}")
        print(f"reverse_posts={post_titles}")
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{through_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{posts_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{tags_table}"')
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
