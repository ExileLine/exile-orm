"""Composable SQL expression objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from exile_orm.query.sql import quote_identifier

if TYPE_CHECKING:
    from exile_orm.model.fields import Field


class Condition:
    """Base SQL condition node."""

    def to_sql(self, params: list[Any], *, table_alias: str | None = None) -> str:
        raise NotImplementedError

    def __and__(self, other: Condition) -> Condition:
        return CombinedCondition("AND", (self, other))

    def __or__(self, other: Condition) -> Condition:
        return CombinedCondition("OR", (self, other))

    def __invert__(self) -> Condition:
        return NotCondition(self)


@dataclass(frozen=True, slots=True)
class BinaryCondition(Condition):
    field: Field[Any]
    operator: str
    value: Any

    def to_sql(self, params: list[Any], *, table_alias: str | None = None) -> str:
        column_sql = quote_identifier(self.field.column_name or self.field.name)
        if table_alias is not None:
            column_sql = f"{quote_identifier(table_alias)}.{column_sql}"

        if self.value is None:
            if self.operator == "=":
                return f"{column_sql} IS NULL"
            if self.operator == "!=":
                return f"{column_sql} IS NOT NULL"

        params.append(self.value)
        return f"{column_sql} {self.operator} ${len(params)}"


@dataclass(frozen=True, slots=True)
class InCondition(Condition):
    field: Field[Any]
    values: tuple[Any, ...]
    negated: bool = False

    def to_sql(self, params: list[Any], *, table_alias: str | None = None) -> str:
        column_sql = quote_identifier(self.field.column_name or self.field.name)
        if table_alias is not None:
            column_sql = f"{quote_identifier(table_alias)}.{column_sql}"
        if not self.values:
            return "TRUE" if self.negated else "FALSE"

        placeholders: list[str] = []
        for value in self.values:
            params.append(value)
            placeholders.append(f"${len(params)}")

        operator = "NOT IN" if self.negated else "IN"
        return f"{column_sql} {operator} ({', '.join(placeholders)})"


@dataclass(frozen=True, slots=True)
class CombinedCondition(Condition):
    operator: str
    conditions: tuple[Condition, ...]

    def to_sql(self, params: list[Any], *, table_alias: str | None = None) -> str:
        rendered = [
            condition.to_sql(params, table_alias=table_alias)
            for condition in self.conditions
        ]
        if len(rendered) == 1:
            return rendered[0]
        return "(" + f" {self.operator} ".join(rendered) + ")"


@dataclass(frozen=True, slots=True)
class NotCondition(Condition):
    condition: Condition

    def to_sql(self, params: list[Any], *, table_alias: str | None = None) -> str:
        return f"NOT ({self.condition.to_sql(params, table_alias=table_alias)})"
