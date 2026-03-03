"""Base async model implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Self

from exile_orm.core.database import Database
from exile_orm.core.exceptions import (
    ModelDefinitionError,
    ModelNotFoundError,
    ModelValidationError,
    QueryError,
)
from exile_orm.model.fields import Field, ForeignKey, ManyToMany
from exile_orm.model.meta import ModelMeta
from exile_orm.query.expressions import Condition
from exile_orm.query.sql import quote_identifier

if TYPE_CHECKING:
    from exile_orm.query.queryset import QuerySet


def _extract_affected_rows(status: str) -> int:
    parts = status.split()
    if not parts:
        return 0
    tail = parts[-1]
    if tail.isdigit():
        return int(tail)
    return 0


def _normalize_batch_size(total_items: int, batch_size: int | None) -> int:
    if total_items <= 0:
        return 0
    if batch_size is None:
        return total_items
    if batch_size <= 0:
        raise ModelValidationError("batch_size must be > 0.")
    return batch_size


def _chunk_list(items: list[Any], batch_size: int) -> list[list[Any]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


class Model(metaclass=ModelMeta):
    """Base class for async ORM models."""

    __table_name__: ClassVar[str]
    __fields__: ClassVar[dict[str, Field[Any]]]
    __relations__: ClassVar[dict[str, ForeignKey]]
    __many_to_many__: ClassVar[dict[str, ManyToMany]]
    __primary_key__: ClassVar[Field[Any] | None]
    __database__: ClassVar[Database | None] = None

    def __init__(self, **values: Any) -> None:
        self._data: dict[str, Any] = {}
        self._related_cache: dict[str, Any] = {}
        self._dirty_fields: set[str] = set()
        self._is_initializing = True

        for field_name, field in self.__fields__.items():
            if field_name in values:
                setattr(self, field_name, values.pop(field_name))
                continue

            default_value = field.get_default_value()
            if default_value is None:
                self._data[field_name] = None
            else:
                self._set_field(field, default_value, mark_dirty=False)

        if values:
            unknown_keys = ", ".join(sorted(values))
            raise ModelValidationError(f"Unknown field(s): {unknown_keys}")

        self._is_initializing = False
        self._dirty_fields.clear()

    @classmethod
    def use_database(cls, database: Database) -> None:
        cls.__database__ = database

    @classmethod
    def _get_database(cls) -> Database:
        if cls.__database__ is None:
            raise QueryError(f"Model '{cls.__name__}' is not bound to a Database.")
        return cls.__database__

    @classmethod
    def _ordered_fields(cls) -> list[Field[Any]]:
        return list(cls.__fields__.values())

    @classmethod
    def _select_columns_sql(cls) -> str:
        return ", ".join(
            quote_identifier(field.column_name or field.name) for field in cls._ordered_fields()
        )

    @classmethod
    def _table_sql(cls) -> str:
        return quote_identifier(cls.__table_name__)

    @classmethod
    def _field_by_name(cls, name: str) -> Field[Any]:
        field = cls.__fields__.get(name)
        if field is None:
            raise ModelValidationError(f"Unknown field '{name}' for model '{cls.__name__}'.")
        return field

    @classmethod
    def _relation_field_by_name(cls, name: str) -> ForeignKey:
        relation = cls.__relations__.get(name)
        if relation is None:
            raise ModelDefinitionError(f"Unknown relation '{name}' for model '{cls.__name__}'.")
        return relation

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Self:
        payload: dict[str, Any] = {}
        for field_name, field in cls.__fields__.items():
            key = field.column_name or field.name
            payload[field_name] = row.get(key)
        instance = cls(**payload)
        instance._dirty_fields.clear()
        return instance

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def validate(self) -> None:
        for field_name, field in self.__fields__.items():
            value = self._data.get(field_name)
            if (
                value is None
                and not field.primary_key
                and not field.nullable
                and field.default is None
            ):
                raise ModelValidationError(f"Field '{field_name}' is required.")
            if value is not None:
                field.validate(value)

    def _set_field(self, field: Field[Any], value: Any, *, mark_dirty: bool) -> None:
        field.validate(value)
        self._data[field.name] = value
        if mark_dirty:
            self._dirty_fields.add(field.name)

    def _set_related_instance(self, relation_name: str, value: Any) -> None:
        self._related_cache[relation_name] = value

    @classmethod
    def query(cls) -> QuerySet[Self]:
        from exile_orm.query.queryset import QuerySet

        return QuerySet(cls)

    @classmethod
    def filter(cls, *conditions: Condition, **filters: Any) -> QuerySet[Self]:
        return cls.query().filter(*conditions, **filters)

    @classmethod
    def exclude(cls, *conditions: Condition, **filters: Any) -> QuerySet[Self]:
        return cls.query().exclude(*conditions, **filters)

    @classmethod
    def select_related(cls, *relation_names: str) -> QuerySet[Self]:
        return cls.query().select_related(*relation_names)

    @classmethod
    def prefetch_related(cls, *relation_names: str) -> QuerySet[Self]:
        return cls.query().prefetch_related(*relation_names)

    @classmethod
    def order_by(cls, *fields: str | Field[Any]) -> QuerySet[Self]:
        return cls.query().order_by(*fields)

    @classmethod
    def limit(cls, value: int) -> QuerySet[Self]:
        return cls.query().limit(value)

    @classmethod
    def offset(cls, value: int) -> QuerySet[Self]:
        return cls.query().offset(value)

    @classmethod
    def cache(cls, *, ttl_seconds: float) -> QuerySet[Self]:
        return cls.query().cache(ttl_seconds=ttl_seconds)

    @classmethod
    async def all(cls) -> list[Self]:
        return await cls.query().all()

    @classmethod
    async def first(cls) -> Self | None:
        return await cls.query().first()

    @classmethod
    async def count(cls) -> int:
        return await cls.query().count()

    @classmethod
    async def exists(cls) -> bool:
        return await cls.query().exists()

    @classmethod
    async def create(cls, **values: Any) -> Self:
        instance = cls(**values)
        instance.validate()

        columns: list[str] = []
        args: list[Any] = []
        placeholders: list[str] = []

        for field in cls._ordered_fields():
            value = instance._data.get(field.name)
            if field.primary_key and value is None:
                continue
            columns.append(quote_identifier(field.column_name or field.name))
            args.append(value)
            placeholders.append(f"${len(args)}")

        table_sql = cls._table_sql()
        returning_sql = cls._select_columns_sql()

        if columns:
            query = (
                f"INSERT INTO {table_sql} ({', '.join(columns)}) "
                f"VALUES ({', '.join(placeholders)}) RETURNING {returning_sql}"
            )
        else:
            query = f"INSERT INTO {table_sql} DEFAULT VALUES RETURNING {returning_sql}"

        db = cls._get_database()
        row = await db.fetch_one(query, *args)
        if row is None:
            raise QueryError("Insert did not return a row.")
        return cls.from_row(dict(row))

    @classmethod
    async def bulk_create(
        cls,
        rows: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[Self]:
        if not rows:
            return []

        instances = [cls(**row) for row in rows]
        resolved_batch_size = _normalize_batch_size(len(instances), batch_size)
        for instance in instances:
            instance.validate()

        insert_fields: list[Field[Any]] = []
        for field in cls._ordered_fields():
            if not field.primary_key:
                insert_fields.append(field)
                continue

            values = [instance._data.get(field.name) for instance in instances]
            has_any_value = any(value is not None for value in values)
            has_all_values = all(value is not None for value in values)
            if has_any_value and not has_all_values:
                raise ModelValidationError(
                    "bulk_create() primary key values must be provided for all rows or none."
                )
            if has_all_values:
                insert_fields.append(field)

        if not insert_fields:
            raise ModelValidationError("bulk_create() has no insertable columns.")

        columns_sql = ", ".join(
            quote_identifier(field.column_name or field.name) for field in insert_fields
        )
        db = cls._get_database()
        created: list[Self] = []
        for batch in _chunk_list(instances, resolved_batch_size):
            args: list[Any] = []
            row_fragments: list[str] = []
            for instance in batch:
                placeholders: list[str] = []
                for field in insert_fields:
                    args.append(instance._data.get(field.name))
                    placeholders.append(f"${len(args)}")
                row_fragments.append(f"({', '.join(placeholders)})")

            query = (
                f"INSERT INTO {cls._table_sql()} ({columns_sql}) "
                f"VALUES {', '.join(row_fragments)} RETURNING {cls._select_columns_sql()}"
            )
            result_rows = await db.fetch_all(query, *args)
            created.extend(cls.from_row(dict(row)) for row in result_rows)

        return created

    @classmethod
    async def get(cls, **filters: Any) -> Self:
        if not filters:
            raise ModelValidationError("`get()` requires at least one filter.")
        return await cls.query().filter(**filters).get()

    async def save(self) -> None:
        primary_key = self.__class__.__primary_key__
        if primary_key is None:
            raise ModelValidationError(
                f"Model '{self.__class__.__name__}' does not define a primary key."
            )

        primary_value = self._data.get(primary_key.name)
        if primary_value is None:
            created = await self.__class__.create(**self.to_dict())
            self._data = created.to_dict()
            self._dirty_fields.clear()
            return

        update_fields = [name for name in self._dirty_fields if name != primary_key.name]
        if not update_fields:
            return

        args: list[Any] = []
        assignments: list[str] = []
        for field_name in update_fields:
            field = self._field_by_name(field_name)
            value = self._data[field_name]
            field.validate(value)
            args.append(value)
            assignments.append(
                f'{quote_identifier(field.column_name or field.name)} = ${len(args)}'
            )

        args.append(primary_value)
        primary_column = quote_identifier(primary_key.column_name or primary_key.name)
        query = (
            f"UPDATE {self._table_sql()} SET {', '.join(assignments)} "
            f"WHERE {primary_column} = ${len(args)} "
            f"RETURNING {self._select_columns_sql()}"
        )

        row = await self._get_database().fetch_one(query, *args)
        if row is None:
            raise ModelNotFoundError(
                f"{self.__class__.__name__} with {primary_key.name}={primary_value} was not found."
            )
        refreshed = self.from_row(dict(row))
        self._data = refreshed.to_dict()
        self._dirty_fields.clear()

    @classmethod
    async def bulk_update(
        cls,
        instances: list[Self],
        *,
        fields: list[str] | None = None,
        batch_size: int | None = None,
    ) -> int:
        if not instances:
            return 0
        resolved_batch_size = _normalize_batch_size(len(instances), batch_size)

        primary_key = cls.__primary_key__
        if primary_key is None:
            raise ModelValidationError(f"Model '{cls.__name__}' does not define a primary key.")

        db = cls._get_database()
        updated_rows = 0
        for batch in _chunk_list(instances, resolved_batch_size):
            async with db.transaction():
                for instance in batch:
                    if not isinstance(instance, cls):
                        raise ModelValidationError(
                            f"bulk_update() expected instances of '{cls.__name__}'."
                        )

                    primary_value = instance._data.get(primary_key.name)
                    if primary_value is None:
                        raise ModelValidationError(
                            f"bulk_update() requires '{primary_key.name}' for every instance."
                        )

                    if fields is None:
                        field_names = [
                            name for name in instance._dirty_fields if name != primary_key.name
                        ]
                    else:
                        field_names = [name for name in fields if name != primary_key.name]

                    if not field_names:
                        continue

                    args: list[Any] = []
                    assignments: list[str] = []
                    for field_name in field_names:
                        field = cls._field_by_name(field_name)
                        value = instance._data.get(field_name)
                        field.validate(value)
                        args.append(value)
                        assignments.append(
                            f'{quote_identifier(field.column_name or field.name)} = ${len(args)}'
                        )

                    args.append(primary_value)
                    primary_column = quote_identifier(primary_key.column_name or primary_key.name)
                    query = (
                        f"UPDATE {cls._table_sql()} SET {', '.join(assignments)} "
                        f"WHERE {primary_column} = ${len(args)}"
                    )
                    status = await db.execute(query, *args)
                    affected = _extract_affected_rows(status)
                    if affected == 0:
                        raise ModelNotFoundError(
                            f"{cls.__name__} with {primary_key.name}={primary_value} was not found."
                        )
                    updated_rows += affected
                    instance._dirty_fields.difference_update(field_names)

        return updated_rows

    @classmethod
    async def bulk_delete(
        cls,
        instances: list[Self] | None = None,
        batch_size: int | None = None,
        **filters: Any,
    ) -> int:
        if instances is not None and filters:
            raise ModelValidationError(
                "bulk_delete() accepts either instances or filters, not both."
            )

        db = cls._get_database()

        if instances is not None:
            if not instances:
                return 0
            resolved_batch_size = _normalize_batch_size(len(instances), batch_size)

            primary_key = cls.__primary_key__
            if primary_key is None:
                raise ModelValidationError(
                    f"Model '{cls.__name__}' does not define a primary key."
                )

            ids: list[Any] = []
            for instance in instances:
                if not isinstance(instance, cls):
                    raise ModelValidationError(
                        f"bulk_delete() expected instances of '{cls.__name__}'."
                    )
                value = instance._data.get(primary_key.name)
                if value is None:
                    raise ModelValidationError(
                        f"bulk_delete() requires '{primary_key.name}' for every instance."
                    )
                ids.append(value)

            affected = 0
            for batch in _chunk_list(ids, resolved_batch_size):
                placeholders = [f"${index}" for index in range(1, len(batch) + 1)]
                query = (
                    f"DELETE FROM {cls._table_sql()} "
                    f"WHERE {quote_identifier(primary_key.column_name or primary_key.name)} "
                    f"IN ({', '.join(placeholders)})"
                )
                status = await db.execute(query, *batch)
                affected += _extract_affected_rows(status)
            for instance in instances:
                instance._dirty_fields.clear()
            return affected

        if not filters:
            raise ModelValidationError("bulk_delete() requires instances or at least one filter.")

        conditions: list[str] = []
        args: list[Any] = []
        for name, value in filters.items():
            field = cls._field_by_name(name)
            args.append(value)
            conditions.append(f'{quote_identifier(field.column_name or field.name)} = ${len(args)}')

        query = f"DELETE FROM {cls._table_sql()} WHERE {' AND '.join(conditions)}"
        status = await db.execute(query, *args)
        return _extract_affected_rows(status)

    async def delete(self) -> None:
        primary_key = self.__class__.__primary_key__
        if primary_key is None:
            raise ModelValidationError(
                f"Model '{self.__class__.__name__}' does not define a primary key."
            )
        primary_value = self._data.get(primary_key.name)
        if primary_value is None:
            raise ModelValidationError("Cannot delete without a primary key value.")

        query = (
            f"DELETE FROM {self._table_sql()} "
            f"WHERE {quote_identifier(primary_key.column_name or primary_key.name)} = $1"
        )
        await self._get_database().execute(query, primary_value)
        self._dirty_fields.clear()
