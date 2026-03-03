"""Model schema snapshot and SQL generation for migrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exile_orm.model.base import Model
from exile_orm.model.fields import (
    BooleanField,
    DateTimeField,
    Field,
    ForeignKey,
    IntegerField,
    JSONField,
    ManyToMany,
    StringField,
)
from exile_orm.query.sql import quote_identifier


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    db_type: str
    nullable: bool
    primary_key: bool
    unique: bool
    references: tuple[str, str, str] | None = None


@dataclass(frozen=True, slots=True)
class IndexSchema:
    name: str
    columns: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True, slots=True)
class TableSchema:
    name: str
    columns: dict[str, ColumnSchema]
    indexes: dict[str, IndexSchema]


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    tables: dict[str, TableSchema]

    def to_dict(self) -> dict[str, Any]:
        tables: dict[str, Any] = {}
        for table_name in sorted(self.tables):
            table = self.tables[table_name]
            columns: dict[str, Any] = {}
            for column_name in sorted(table.columns):
                column = table.columns[column_name]
                columns[column_name] = {
                    "name": column.name,
                    "db_type": column.db_type,
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "unique": column.unique,
                    "references": (
                        {
                            "table": column.references[0],
                            "column": column.references[1],
                            "on_delete": column.references[2],
                        }
                        if column.references is not None
                        else None
                    ),
                }

            indexes: dict[str, Any] = {}
            for index_name in sorted(table.indexes):
                index = table.indexes[index_name]
                indexes[index_name] = {
                    "name": index.name,
                    "columns": list(index.columns),
                    "unique": index.unique,
                }

            tables[table_name] = {"name": table.name, "columns": columns, "indexes": indexes}
        return {"tables": tables}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SchemaSnapshot:
        tables_payload = payload.get("tables", {})
        tables: dict[str, TableSchema] = {}
        for table_name, table_data in tables_payload.items():
            columns: dict[str, ColumnSchema] = {}
            for column_name, column_data in table_data.get("columns", {}).items():
                references_data = column_data.get("references")
                references: tuple[str, str, str] | None
                if references_data is None:
                    references = None
                else:
                    references = (
                        str(references_data["table"]),
                        str(references_data["column"]),
                        str(references_data.get("on_delete", "RESTRICT")),
                    )
                columns[column_name] = ColumnSchema(
                    name=str(column_data["name"]),
                    db_type=str(column_data["db_type"]),
                    nullable=bool(column_data["nullable"]),
                    primary_key=bool(column_data["primary_key"]),
                    unique=bool(column_data["unique"]),
                    references=references,
                )

            indexes: dict[str, IndexSchema] = {}
            for index_name, index_data in table_data.get("indexes", {}).items():
                indexes[index_name] = IndexSchema(
                    name=str(index_data["name"]),
                    columns=tuple(str(item) for item in index_data.get("columns", [])),
                    unique=bool(index_data["unique"]),
                )

            tables[table_name] = TableSchema(name=table_name, columns=columns, indexes=indexes)
        return cls(tables=tables)

    @classmethod
    def empty(cls) -> SchemaSnapshot:
        return cls(tables={})


def save_snapshot(path: Path, snapshot: SchemaSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=True, indent=2) + "\n")


def load_snapshot(path: Path) -> SchemaSnapshot:
    if not path.exists():
        return SchemaSnapshot.empty()
    payload = json.loads(path.read_text())
    return SchemaSnapshot.from_dict(payload)


def snapshot_from_models(models: list[type[Model]]) -> SchemaSnapshot:
    tables: dict[str, TableSchema] = {}
    for model_cls in models:
        table_name = model_cls.__table_name__
        columns: dict[str, ColumnSchema] = {}
        indexes: dict[str, IndexSchema] = {}
        for field in model_cls._ordered_fields():
            column_name = field.column_name or field.name
            db_type = db_type_for_field(field)
            nullable = False if field.primary_key else field.nullable
            references: tuple[str, str, str] | None = None

            if isinstance(field, ForeignKey):
                related_model = field.related_model()
                related_pk = related_model.__primary_key__
                if related_pk is None:
                    raise ValueError(
                        f"Related model '{related_model.__name__}' has no primary key."
                    )
                references = (
                    related_model.__table_name__,
                    related_pk.column_name or related_pk.name,
                    field.on_delete.upper(),
                )

            columns[field.name] = ColumnSchema(
                name=column_name,
                db_type=db_type,
                nullable=nullable,
                primary_key=field.primary_key,
                unique=field.unique,
                references=references,
            )

            if field.unique:
                index_name = f"uq_{table_name}_{column_name}"
                indexes[index_name] = IndexSchema(
                    name=index_name,
                    columns=(column_name,),
                    unique=True,
                )
            elif field.index:
                index_name = f"idx_{table_name}_{column_name}"
                indexes[index_name] = IndexSchema(
                    name=index_name,
                    columns=(column_name,),
                    unique=False,
                )

        _register_table(
            tables,
            TableSchema(name=table_name, columns=columns, indexes=indexes),
        )

        for m2m_relation in model_cls.__many_to_many__.values():
            _register_table(
                tables,
                _build_many_to_many_table_schema(model_cls, m2m_relation),
            )
    return SchemaSnapshot(tables=tables)


def _register_table(tables: dict[str, TableSchema], table: TableSchema) -> None:
    existing = tables.get(table.name)
    if existing is None:
        tables[table.name] = table
        return
    if existing != table:
        raise ValueError(
            f"Conflicting schema definitions for table '{table.name}'. "
            "Please ensure through-table definitions are consistent."
        )


def _build_many_to_many_table_schema(
    model_cls: type[Model],
    relation: ManyToMany,
) -> TableSchema:
    source_pk = model_cls.__primary_key__
    if source_pk is None:
        raise ValueError(f"Model '{model_cls.__name__}' has no primary key for many-to-many.")

    related_model = relation.related_model()
    target_pk = related_model.__primary_key__
    if target_pk is None:
        raise ValueError(
            f"Related model '{related_model.__name__}' has no primary key for many-to-many."
        )

    through_table_name = relation.through_table()
    source_column_name = relation.source_column()
    target_column_name = relation.target_column()
    if source_column_name == target_column_name:
        raise ValueError(
            f"ManyToMany through-table '{through_table_name}' has duplicate column name "
            f"'{source_column_name}'. Configure through_source_column/through_target_column."
        )

    source_column = ColumnSchema(
        name=source_column_name,
        db_type=db_type_for_field(source_pk),
        nullable=False,
        primary_key=False,
        unique=False,
        references=(
            model_cls.__table_name__,
            source_pk.column_name or source_pk.name,
            "CASCADE",
        ),
    )
    target_column = ColumnSchema(
        name=target_column_name,
        db_type=db_type_for_field(target_pk),
        nullable=False,
        primary_key=False,
        unique=False,
        references=(
            related_model.__table_name__,
            target_pk.column_name or target_pk.name,
            "CASCADE",
        ),
    )

    columns = {
        source_column_name: source_column,
        target_column_name: target_column,
    }
    indexes = {
        f"uq_{through_table_name}_{source_column_name}_{target_column_name}": IndexSchema(
            name=f"uq_{through_table_name}_{source_column_name}_{target_column_name}",
            columns=(source_column_name, target_column_name),
            unique=True,
        ),
        f"idx_{through_table_name}_{source_column_name}": IndexSchema(
            name=f"idx_{through_table_name}_{source_column_name}",
            columns=(source_column_name,),
            unique=False,
        ),
        f"idx_{through_table_name}_{target_column_name}": IndexSchema(
            name=f"idx_{through_table_name}_{target_column_name}",
            columns=(target_column_name,),
            unique=False,
        ),
    }
    return TableSchema(name=through_table_name, columns=columns, indexes=indexes)


def db_type_for_field(field: Field[Any]) -> str:
    if isinstance(field, ForeignKey):
        related_model = field.related_model()
        related_pk = related_model.__primary_key__
        if related_pk is None:
            raise ValueError(f"Related model '{related_model.__name__}' has no primary key.")
        return db_type_for_field(related_pk)
    if isinstance(field, IntegerField):
        return "INTEGER"
    if isinstance(field, StringField):
        return "TEXT"
    if isinstance(field, BooleanField):
        return "BOOLEAN"
    if isinstance(field, DateTimeField):
        return "TIMESTAMP"
    if isinstance(field, JSONField):
        return "JSONB"
    return "TEXT"


def column_sql(column: ColumnSchema) -> str:
    tokens = [quote_identifier(column.name), column.db_type]
    if column.primary_key:
        tokens.append("PRIMARY KEY")
    elif not column.nullable:
        tokens.append("NOT NULL")
    if column.unique:
        tokens.append("UNIQUE")
    if column.references is not None:
        ref_table, ref_column, on_delete = column.references
        tokens.append(
            f"REFERENCES {quote_identifier(ref_table)}({quote_identifier(ref_column)}) "
            f"ON DELETE {on_delete}"
        )
    return " ".join(tokens)


def create_table_sql(table: TableSchema) -> str:
    ordered_columns = [table.columns[name] for name in sorted(table.columns)]
    columns_sql = ", ".join(column_sql(column) for column in ordered_columns)
    return f"CREATE TABLE {quote_identifier(table.name)} ({columns_sql})"


def drop_table_sql(table_name: str) -> str:
    return f"DROP TABLE {quote_identifier(table_name)}"


def add_column_sql(table_name: str, column: ColumnSchema) -> str:
    return f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {column_sql(column)}"


def drop_column_sql(table_name: str, column_name: str) -> str:
    return f"ALTER TABLE {quote_identifier(table_name)} DROP COLUMN {quote_identifier(column_name)}"


def alter_column_type_sql(table_name: str, column_name: str, new_type: str) -> str:
    return (
        f"ALTER TABLE {quote_identifier(table_name)} "
        f"ALTER COLUMN {quote_identifier(column_name)} TYPE {new_type}"
    )


def alter_column_nullable_sql(table_name: str, column_name: str, *, nullable: bool) -> str:
    if nullable:
        action = "DROP NOT NULL"
    else:
        action = "SET NOT NULL"
    return (
        f"ALTER TABLE {quote_identifier(table_name)} "
        f"ALTER COLUMN {quote_identifier(column_name)} {action}"
    )


def create_index_sql(table_name: str, index: IndexSchema) -> str:
    unique = "UNIQUE " if index.unique else ""
    columns_sql = ", ".join(quote_identifier(column) for column in index.columns)
    return (
        f"CREATE {unique}INDEX {quote_identifier(index.name)} "
        f"ON {quote_identifier(table_name)} ({columns_sql})"
    )


def drop_index_sql(index_name: str) -> str:
    return f"DROP INDEX {quote_identifier(index_name)}"
