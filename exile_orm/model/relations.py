"""Descriptors for model relationship access."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from exile_orm.core.exceptions import ModelValidationError
from exile_orm.query.sql import quote_identifier

if TYPE_CHECKING:
    from exile_orm.model.base import Model
    from exile_orm.model.fields import ManyToMany


class ReverseRelationDescriptor:
    """One-to-many reverse accessor based on a ForeignKey field."""

    def __init__(self, related_model: type[Model], foreign_key_field_name: str) -> None:
        self._related_model = related_model
        self._foreign_key_field_name = foreign_key_field_name

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        if instance is None:
            return self

        primary_key = owner.__primary_key__
        if primary_key is None:
            raise ModelValidationError(
                f"Model '{owner.__name__}' does not define a primary key for reverse relation."
            )

        primary_value = instance._data.get(primary_key.name)
        if primary_value is None:
            raise ModelValidationError(
                "Cannot access reverse relation before primary key is assigned."
            )

        return self._related_model.filter(**{self._foreign_key_field_name: primary_value})


class ReverseOneToOneDescriptor:
    """One-to-one reverse accessor returning one related row or None."""

    def __init__(self, related_model: type[Model], foreign_key_field_name: str) -> None:
        self._related_model = related_model
        self._foreign_key_field_name = foreign_key_field_name

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        if instance is None:
            return self

        primary_key = owner.__primary_key__
        if primary_key is None:
            raise ModelValidationError(
                f"Model '{owner.__name__}' does not define a primary key for reverse relation."
            )

        primary_value = instance._data.get(primary_key.name)
        if primary_value is None:
            raise ModelValidationError(
                "Cannot access reverse relation before primary key is assigned."
            )

        return self._related_model.filter(**{self._foreign_key_field_name: primary_value}).first()


class ManyToManyManager:
    """Runtime helper for managing many-to-many links from a bound instance."""

    def __init__(self, *, instance: Model, relation: ManyToMany, reverse: bool) -> None:
        self._instance = instance
        self._relation = relation
        self._reverse = reverse

    async def all(self) -> list[Model]:
        owner_id = self._owner_primary_value()
        _, related_model = self._owner_and_related_models()
        related_pk = related_model.__primary_key__
        if related_pk is None:
            raise ModelValidationError("ManyToMany models must define primary keys.")

        through_table = quote_identifier(self._relation.through_table())
        related_table = related_model._table_sql()
        owner_column = quote_identifier(self._owner_column_name())
        related_column = quote_identifier(self._related_column_name())
        related_pk_column = quote_identifier(related_pk.column_name or related_pk.name)

        query = (
            f"SELECT {related_model._select_columns_sql()} "
            f"FROM {related_table} AS r "
            f"INNER JOIN {through_table} AS j "
            f"ON r.{related_pk_column} = j.{related_column} "
            f"WHERE j.{owner_column} = $1"
        )
        db = self._database_model()._get_database()
        rows = await db.fetch_all(query, owner_id)
        return [related_model.from_row(dict(row)) for row in rows]

    async def add(self, *items: Any) -> None:
        if not items:
            return
        owner_id = self._owner_primary_value()
        related_ids = self._normalize_related_ids(items)
        if not related_ids:
            return

        through_table = quote_identifier(self._relation.through_table())
        owner_column = quote_identifier(self._owner_column_name())
        related_column = quote_identifier(self._related_column_name())
        query = (
            f"INSERT INTO {through_table} ({owner_column}, {related_column}) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING"
        )

        db = self._database_model()._get_database()
        args_list = [(owner_id, related_id) for related_id in related_ids]
        await db.execute_many(query, args_list)

    async def remove(self, *items: Any) -> None:
        if not items:
            return
        owner_id = self._owner_primary_value()
        related_ids = self._normalize_related_ids(items)
        if not related_ids:
            return

        through_table = quote_identifier(self._relation.through_table())
        owner_column = quote_identifier(self._owner_column_name())
        related_column = quote_identifier(self._related_column_name())
        placeholders = [f"${index}" for index in range(2, len(related_ids) + 2)]
        query = (
            f"DELETE FROM {through_table} "
            f"WHERE {owner_column} = $1 AND {related_column} IN ({', '.join(placeholders)})"
        )

        db = self._database_model()._get_database()
        await db.execute(query, owner_id, *related_ids)

    async def clear(self) -> None:
        owner_id = self._owner_primary_value()
        through_table = quote_identifier(self._relation.through_table())
        owner_column = quote_identifier(self._owner_column_name())
        query = f"DELETE FROM {through_table} WHERE {owner_column} = $1"

        db = self._database_model()._get_database()
        await db.execute(query, owner_id)

    async def set(self, items: Sequence[Any]) -> None:
        db = self._database_model()._get_database()
        async with db.transaction():
            await self.clear()
            await self.add(*items)

    def _database_model(self) -> type[Model]:
        return self._relation._require_owner()

    def _owner_and_related_models(self) -> tuple[type[Model], type[Model]]:
        if self._reverse:
            return self._relation.related_model(), self._relation._require_owner()
        return self._relation._require_owner(), self._relation.related_model()

    def _owner_column_name(self) -> str:
        if self._reverse:
            return self._relation.target_column()
        return self._relation.source_column()

    def _related_column_name(self) -> str:
        if self._reverse:
            return self._relation.source_column()
        return self._relation.target_column()

    def _owner_primary_value(self) -> Any:
        owner_model, _ = self._owner_and_related_models()
        owner_pk = owner_model.__primary_key__
        if owner_pk is None:
            raise ModelValidationError("ManyToMany owner model has no primary key.")
        owner_id = self._instance._data.get(owner_pk.name)
        if owner_id is None:
            raise ModelValidationError(
                "Cannot use many-to-many relation before primary key is set."
            )
        return owner_id

    def _normalize_related_ids(self, items: Sequence[Any]) -> list[Any]:
        _, related_model = self._owner_and_related_models()
        related_pk = related_model.__primary_key__
        if related_pk is None:
            raise ModelValidationError("ManyToMany related model has no primary key.")

        result: list[Any] = []
        seen: set[Any] = set()
        for item in items:
            related_id: Any
            if isinstance(item, related_model):
                related_id = item._data.get(related_pk.name)
                if related_id is None:
                    raise ModelValidationError(
                        "Cannot add unsaved model instance to many-to-many relation."
                    )
            else:
                if not isinstance(item, related_pk.python_types):
                    readable_types = ", ".join(t.__name__ for t in related_pk.python_types)
                    raise ModelValidationError(
                        f"ManyToMany expects related id type {readable_types}, "
                        f"got {type(item).__name__}."
                    )
                related_id = item

            if related_id in seen:
                continue
            seen.add(related_id)
            result.append(related_id)
        return result


class ReverseManyToManyDescriptor:
    """Reverse accessor for a many-to-many relation."""

    def __init__(self, relation: ManyToMany) -> None:
        self._relation = relation

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        del owner
        if instance is None:
            return self
        return ManyToManyManager(instance=instance, relation=self._relation, reverse=True)
