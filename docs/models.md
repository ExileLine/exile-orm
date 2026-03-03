# Models

## Built-in fields

- `IntegerField`
- `StringField`
- `BooleanField`
- `DateTimeField`
- `JSONField`
- `ForeignKey`
- `OneToOne`
- `ManyToMany`

## Common field options

- `primary_key`
- `nullable`
- `default`
- `index`
- `unique`
- `column_name`

## Example

```python
from exile_orm.model import ForeignKey, IntegerField, ManyToMany, Model, OneToOne, StringField


class Author(Model):
    __table_name__ = "authors"
    id = IntegerField(primary_key=True)
    name = StringField(unique=True)


class Article(Model):
    __table_name__ = "articles"
    id = IntegerField(primary_key=True)
    title = StringField()
    author = ForeignKey(Author, related_name="articles")
    tags = ManyToMany(
        lambda: Tag,
        related_name="articles",
        through="article_tags",
        through_source_column="article_id",
        through_target_column="tag_id",
    )


class AuthorProfile(Model):
    __table_name__ = "author_profiles"
    id = IntegerField(primary_key=True)
    bio = StringField()
    author = OneToOne(Author, related_name="profile")


class Tag(Model):
    __table_name__ = "tags"
    id = IntegerField(primary_key=True)
    name = StringField()
```

`ManyToMany` uses an explicit join table (`through`). `makemigrations` will include
that join table automatically using the two configured link columns.

## Bulk operations

```python
rows = await Article.bulk_create(payloads, batch_size=1000)
await Article.bulk_update(rows, fields=["title"], batch_size=500)
await Article.bulk_delete(rows, batch_size=500)
```
