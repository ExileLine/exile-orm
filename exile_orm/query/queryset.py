"""QuerySet implementation for composing model queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from exile_orm.core.exceptions import (
    ModelDefinitionError,
    ModelNotFoundError,
    ModelValidationError,
    QueryError,
)
from exile_orm.model.fields import Field
from exile_orm.query.expressions import BinaryCondition, CombinedCondition, Condition
from exile_orm.query.sql import quote_identifier

if TYPE_CHECKING:
    from exile_orm.model.base import Model

M = TypeVar("M", bound="Model")


@dataclass(frozen=True, slots=True)
class QuerySet(Generic[M]):
    """Immutable query builder for model classes."""

    model_cls: type[M]
    conditions: tuple[Condition, ...] = ()
    orderings: tuple[tuple[str, str], ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None
    select_related_fields: tuple[str, ...] = ()
    prefetch_related_fields: tuple[str, ...] = ()
    cache_ttl_seconds: float | None = None

    def filter(self, *conditions: Condition, **filters: Any) -> QuerySet[M]:
        normalized = self._normalize_conditions(conditions, filters)
        return self._clone(conditions=self.conditions + normalized)

    def exclude(self, *conditions: Condition, **filters: Any) -> QuerySet[M]:
        normalized = self._normalize_conditions(conditions, filters)
        negated = tuple(~condition for condition in normalized)
        return self._clone(conditions=self.conditions + negated)

    def select_related(self, *relation_names: str) -> QuerySet[M]:
        if not relation_names:
            raise ModelValidationError("`select_related()` requires at least one relation.")

        normalized = list(self.select_related_fields)
        for relation_name in relation_names:
            self.model_cls._relation_field_by_name(relation_name)
            if relation_name not in normalized:
                normalized.append(relation_name)
        return self._clone(select_related_fields=tuple(normalized))

    def prefetch_related(self, *relation_names: str) -> QuerySet[M]:
        if not relation_names:
            raise ModelValidationError("`prefetch_related()` requires at least one relation.")

        normalized = list(self.prefetch_related_fields)
        for relation_name in relation_names:
            self.model_cls._relation_field_by_name(relation_name)
            if relation_name not in normalized:
                normalized.append(relation_name)
        return self._clone(prefetch_related_fields=tuple(normalized))

    def order_by(self, *fields: str | Field[Any]) -> QuerySet[M]:
        if not fields:
            raise ModelValidationError("`order_by()` requires at least one field.")

        rendered: list[tuple[str, str]] = list(self.orderings)
        for item in fields:
            direction = "ASC"
            if isinstance(item, str):
                field_name = item
                if field_name.startswith("-"):
                    direction = "DESC"
                    field_name = field_name[1:]
                field = self.model_cls._field_by_name(field_name)
            elif isinstance(item, Field):
                field = item
            else:
                raise ModelValidationError("`order_by()` accepts field names or Field instances.")

            rendered.append((field.column_name or field.name, direction))

        return self._clone(orderings=tuple(rendered))

    def limit(self, value: int) -> QuerySet[M]:
        if value < 0:
            raise ModelValidationError("`limit()` must be >= 0.")
        return self._clone(limit_value=value)

    def offset(self, value: int) -> QuerySet[M]:
        if value < 0:
            raise ModelValidationError("`offset()` must be >= 0.")
        return self._clone(offset_value=value)

    def cache(self, *, ttl_seconds: float) -> QuerySet[M]:
        if ttl_seconds <= 0:
            raise ModelValidationError("`cache(ttl_seconds=...)` requires ttl_seconds > 0.")
        return self._clone(cache_ttl_seconds=ttl_seconds)

    async def all(self) -> list[M]:
        query, params = self._build_select_query()
        rows = await self._fetch_all_rows(query, params)

        if self.select_related_fields:
            instances = [self._from_joined_row(dict(row)) for row in rows]
        else:
            instances = [self.model_cls.from_row(dict(row)) for row in rows]

        if self.prefetch_related_fields:
            await self._apply_prefetch_related(instances)
        return instances

    async def first(self) -> M | None:
        items = await self.limit(1).all()
        if not items:
            return None
        return items[0]

    async def get(self, **filters: Any) -> M:
        queryset = self.filter(**filters) if filters else self
        items = await queryset.limit(2).all()
        if not items:
            raise ModelNotFoundError(f"{self.model_cls.__name__} matching filters was not found.")
        if len(items) > 1:
            raise QueryError(f"Multiple {self.model_cls.__name__} rows returned for `get()`.")
        return items[0]

    async def count(self) -> int:
        params: list[Any] = []
        where_sql = self._build_where_clause(params)
        query = f"SELECT COUNT(*) AS count FROM {self.model_cls._table_sql()}{where_sql}"
        row = await self._fetch_one_row(query, params)
        if row is None:
            return 0
        return int(row["count"])

    async def exists(self) -> bool:
        params: list[Any] = []
        where_sql = self._build_where_clause(params)
        query = f"SELECT 1 AS exists_flag FROM {self.model_cls._table_sql()}{where_sql} LIMIT 1"
        row = await self._fetch_one_row(query, params)
        return row is not None

    def _clone(
        self,
        *,
        conditions: tuple[Condition, ...] | None = None,
        orderings: tuple[tuple[str, str], ...] | None = None,
        limit_value: int | None = None,
        offset_value: int | None = None,
        select_related_fields: tuple[str, ...] | None = None,
        prefetch_related_fields: tuple[str, ...] | None = None,
        cache_ttl_seconds: float | None = None,
    ) -> QuerySet[M]:
        return QuerySet(
            model_cls=self.model_cls,
            conditions=self.conditions if conditions is None else conditions,
            orderings=self.orderings if orderings is None else orderings,
            limit_value=self.limit_value if limit_value is None else limit_value,
            offset_value=self.offset_value if offset_value is None else offset_value,
            select_related_fields=(
                self.select_related_fields
                if select_related_fields is None
                else select_related_fields
            ),
            prefetch_related_fields=(
                self.prefetch_related_fields
                if prefetch_related_fields is None
                else prefetch_related_fields
            ),
            cache_ttl_seconds=(
                self.cache_ttl_seconds if cache_ttl_seconds is None else cache_ttl_seconds
            ),
        )

    def _normalize_conditions(
        self,
        conditions: tuple[Condition, ...],
        filters: dict[str, Any],
    ) -> tuple[Condition, ...]:
        normalized: list[Condition] = list(conditions)
        for name, value in filters.items():
            field = self.model_cls._field_by_name(name)
            normalized.append(BinaryCondition(field=field, operator="=", value=value))
        return tuple(normalized)

    def _build_where_clause(self, params: list[Any], *, table_alias: str | None = None) -> str:
        if not self.conditions:
            return ""
        combined = CombinedCondition("AND", self.conditions)
        return f" WHERE {combined.to_sql(params, table_alias=table_alias)}"

    def _build_order_by_clause(self, *, table_alias: str | None = None) -> str:
        if not self.orderings:
            return ""
        fragments: list[str] = []
        for column_name, direction in self.orderings:
            column_sql = quote_identifier(column_name)
            if table_alias is not None:
                column_sql = f"{quote_identifier(table_alias)}.{column_sql}"
            fragments.append(f"{column_sql} {direction}")
        return f" ORDER BY {', '.join(fragments)}"

    def _build_select_query(self) -> tuple[str, list[Any]]:
        if not self.select_related_fields:
            return self._build_select_query_without_join()
        return self._build_select_query_with_join()

    def _build_select_query_without_join(self) -> tuple[str, list[Any]]:
        params: list[Any] = []
        where_sql = self._build_where_clause(params)

        query = (
            f"SELECT {self.model_cls._select_columns_sql()} FROM {self.model_cls._table_sql()}"
            f"{where_sql}"
        )
        query += self._build_order_by_clause()
        if self.limit_value is not None:
            query += f" LIMIT {self.limit_value}"
        if self.offset_value is not None:
            query += f" OFFSET {self.offset_value}"
        return query, params

    def _build_select_query_with_join(self) -> tuple[str, list[Any]]:
        base_alias = "t0"
        base_alias_sql = quote_identifier(base_alias)

        select_fragments: list[str] = []
        for field in self.model_cls._ordered_fields():
            column_name = field.column_name or field.name
            column_sql = quote_identifier(column_name)
            select_fragments.append(
                f"{base_alias_sql}.{column_sql} AS {quote_identifier(column_name)}"
            )

        join_fragments: list[str] = []
        for relation_name in self.select_related_fields:
            relation = self.model_cls._relation_field_by_name(relation_name)
            related_model = relation.related_model()
            related_pk = related_model.__primary_key__
            if related_pk is None:
                raise ModelDefinitionError(
                    f"Related model '{related_model.__name__}' does not define a primary key."
                )

            related_alias = f"{relation_name}__rel"
            related_alias_sql = quote_identifier(related_alias)

            fk_column = quote_identifier(relation.column_name or relation.name)
            pk_column = quote_identifier(related_pk.column_name or related_pk.name)

            join_fragments.append(
                f" LEFT JOIN {related_model._table_sql()} AS {related_alias_sql} "
                f"ON {base_alias_sql}.{fk_column} = {related_alias_sql}.{pk_column}"
            )

            for related_field in related_model._ordered_fields():
                related_column_name = related_field.column_name or related_field.name
                alias = self._related_column_alias(relation_name, related_column_name)
                related_column_sql = quote_identifier(related_column_name)
                select_fragments.append(
                    f"{related_alias_sql}.{related_column_sql} AS {quote_identifier(alias)}"
                )

        params: list[Any] = []
        where_sql = self._build_where_clause(params, table_alias=base_alias)
        query = (
            f"SELECT {', '.join(select_fragments)} FROM {self.model_cls._table_sql()} "
            f"AS {base_alias_sql}{''.join(join_fragments)}{where_sql}"
        )
        query += self._build_order_by_clause(table_alias=base_alias)
        if self.limit_value is not None:
            query += f" LIMIT {self.limit_value}"
        if self.offset_value is not None:
            query += f" OFFSET {self.offset_value}"
        return query, params

    def _related_column_alias(self, relation_name: str, column_name: str) -> str:
        return f"__rel__{relation_name}__{column_name}"

    def _from_joined_row(self, row: dict[str, Any]) -> M:
        instance = self.model_cls.from_row(row)
        for relation_name in self.select_related_fields:
            relation = self.model_cls._relation_field_by_name(relation_name)
            related_model = relation.related_model()

            payload: dict[str, Any] = {}
            has_non_null = False
            for related_field in related_model._ordered_fields():
                related_column_name = related_field.column_name or related_field.name
                alias = self._related_column_alias(relation_name, related_column_name)
                value = row.get(alias)
                payload[related_field.name] = value
                if value is not None:
                    has_non_null = True

            if not has_non_null:
                instance._set_related_instance(relation_name, None)
                continue

            related_instance = related_model(**payload)
            related_instance._dirty_fields.clear()
            instance._set_related_instance(relation_name, related_instance)
        return instance

    async def _apply_prefetch_related(self, instances: list[M]) -> None:
        if not instances:
            return

        for relation_name in self.prefetch_related_fields:
            relation = self.model_cls._relation_field_by_name(relation_name)
            related_model = relation.related_model()
            related_pk = related_model.__primary_key__
            if related_pk is None:
                raise ModelDefinitionError(
                    f"Related model '{related_model.__name__}' does not define a primary key."
                )

            related_ids: list[Any] = []
            seen: set[Any] = set()
            for instance in instances:
                related_id = instance._data.get(relation.name)
                if related_id is None:
                    instance._set_related_instance(relation_name, None)
                    continue
                if related_id in seen:
                    continue
                seen.add(related_id)
                related_ids.append(related_id)

            if not related_ids:
                continue

            placeholders = [f"${index}" for index in range(1, len(related_ids) + 1)]
            query = (
                f"SELECT {related_model._select_columns_sql()} FROM {related_model._table_sql()} "
                f"WHERE {quote_identifier(related_pk.column_name or related_pk.name)} "
                f"IN ({', '.join(placeholders)})"
            )
            rows = await self._fetch_all_rows(query, related_ids)

            related_by_id: dict[Any, Model] = {}
            for row in rows:
                related_instance = related_model.from_row(dict(row))
                related_id = related_instance._data.get(related_pk.name)
                related_by_id[related_id] = related_instance

            for instance in instances:
                related_id = instance._data.get(relation.name)
                instance._set_related_instance(relation_name, related_by_id.get(related_id))

    async def _fetch_all_rows(self, query: str, params: list[Any]) -> list[Any]:
        db = self.model_cls._get_database()
        ttl = self.cache_ttl_seconds
        if ttl is not None and hasattr(db, "cached_fetch_all"):
            cached_fetch_all = cast(Any, db.cached_fetch_all)
            rows = await cached_fetch_all(query, *params, ttl_seconds=ttl)
            return cast(list[Any], rows)
        return await db.fetch_all(query, *params)

    async def _fetch_one_row(self, query: str, params: list[Any]) -> Any:
        db = self.model_cls._get_database()
        ttl = self.cache_ttl_seconds
        if ttl is not None and hasattr(db, "cached_fetch_one"):
            cached_fetch_one = cast(Any, db.cached_fetch_one)
            return await cached_fetch_one(query, *params, ttl_seconds=ttl)
        return await db.fetch_one(query, *params)
