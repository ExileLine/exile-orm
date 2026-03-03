# Query API

## Core methods

- `filter(...)`
- `exclude(...)`
- `order_by(...)`
- `limit(...)`
- `offset(...)`
- `all()`
- `first()`
- `get()`
- `count()`
- `exists()`
- `cache(ttl_seconds=...)`

## Expressions

- Comparison: `==`, `!=`, `>`, `>=`, `<`, `<=`
- Membership: `in_([...])`, `not_in([...])`
- Pattern: `like("a%")`, `ilike("a%")`
- Null checks: `is_null()`, `is_not_null()`
- Boolean composition: `cond_a & cond_b`, `cond_a | cond_b`, `~cond`

## Examples

```python
rows = await User.filter(User.id > 10, name="alice").order_by("-id").limit(20).all()
total = await User.filter(User.name.like("a%")).count()
has_alice = await User.filter(name="alice").exists()
cached_rows = await User.filter(name="alice").cache(ttl_seconds=30).all()
```

## Relation preloading

```python
rows = await Article.select_related("author").all()
rows = await Article.prefetch_related("author").all()
```

## Many-to-many manager

```python
tags = await article.tags.all()
await article.tags.add(tag1, tag2.id)
await article.tags.remove(tag1.id)
await article.tags.clear()
await article.tags.set([tag2.id, tag3.id])
```
