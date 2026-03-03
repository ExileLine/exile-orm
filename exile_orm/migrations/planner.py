"""Schema diff planner that emits up/down SQL statements."""

from __future__ import annotations

from dataclasses import dataclass

from exile_orm.migrations.schema import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
    add_column_sql,
    alter_column_nullable_sql,
    alter_column_type_sql,
    create_index_sql,
    create_table_sql,
    drop_column_sql,
    drop_index_sql,
    drop_table_sql,
)


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    up_sql: list[str]
    down_sql: list[str]


def plan_migration(before: SchemaSnapshot, after: SchemaSnapshot) -> MigrationPlan:
    up_sql: list[str] = []
    down_sql: list[str] = []

    before_tables = before.tables
    after_tables = after.tables

    before_names = set(before_tables)
    after_names = set(after_tables)

    created_tables = _topological_table_order(sorted(after_names - before_names), after_tables)
    dropped_tables = list(
        reversed(_topological_table_order(sorted(before_names - after_names), before_tables))
    )
    shared_tables = sorted(before_names & after_names)

    for table_name in created_tables:
        table = after_tables[table_name]
        up_sql.append(create_table_sql(table))
        for index in sorted(table.indexes.values(), key=lambda item: item.name):
            up_sql.append(create_index_sql(table_name, index))

        rollback_ops = [
            drop_index_sql(index.name)
            for index in sorted(table.indexes.values(), key=lambda item: item.name, reverse=True)
        ]
        rollback_ops.append(drop_table_sql(table_name))
        down_sql = rollback_ops + down_sql

    for table_name in shared_tables:
        before_table = before_tables[table_name]
        after_table = after_tables[table_name]
        table_up, table_down = _plan_table_changes(before_table, after_table)
        up_sql.extend(table_up)
        down_sql = table_down + down_sql

    for table_name in dropped_tables:
        table = before_tables[table_name]
        up_sql.append(drop_table_sql(table_name))
        down_sql.insert(0, create_table_sql(table))
        for index in sorted(table.indexes.values(), key=lambda item: item.name):
            down_sql.insert(1, create_index_sql(table_name, index))

    return MigrationPlan(up_sql=up_sql, down_sql=down_sql)


def _topological_table_order(table_names: list[str], tables: dict[str, TableSchema]) -> list[str]:
    if not table_names:
        return []

    table_set = set(table_names)
    dependencies: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {name: set() for name in table_names}
    for table_name in table_names:
        refs = {
            ref_table
            for ref_table in _referenced_tables(tables[table_name])
            if ref_table in table_set and ref_table != table_name
        }
        dependencies[table_name] = refs
        for ref_table in refs:
            dependents[ref_table].add(table_name)

    ready = sorted(name for name in table_names if not dependencies[name])
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in sorted(dependents[current]):
            child_deps = dependencies[child]
            if current not in child_deps:
                continue
            child_deps.remove(current)
            if not child_deps:
                ready.append(child)
        ready.sort()

    if len(ordered) == len(table_names):
        return ordered

    # Fallback for cycles/self-references: keep deterministic order and append unresolved tables.
    unresolved = sorted(name for name in table_names if name not in ordered)
    return ordered + unresolved


def _referenced_tables(table: TableSchema) -> set[str]:
    refs: set[str] = set()
    for column in table.columns.values():
        if column.references is None:
            continue
        refs.add(column.references[0])
    return refs


def _plan_table_changes(
    before_table: TableSchema,
    after_table: TableSchema,
) -> tuple[list[str], list[str]]:
    up_sql: list[str] = []
    down_sql: list[str] = []

    before_columns = before_table.columns
    after_columns = after_table.columns

    before_column_names = set(before_columns)
    after_column_names = set(after_columns)

    created_columns = sorted(after_column_names - before_column_names)
    dropped_columns = sorted(before_column_names - after_column_names)
    shared_columns = sorted(before_column_names & after_column_names)

    for field_name in created_columns:
        after_column = after_columns[field_name]
        up_sql.append(add_column_sql(after_table.name, after_column))
        down_sql.insert(0, drop_column_sql(after_table.name, after_column.name))

    for field_name in shared_columns:
        before_column = before_columns[field_name]
        after_column = after_columns[field_name]
        column_up, column_down = _plan_column_changes(after_table.name, before_column, after_column)
        up_sql.extend(column_up)
        down_sql = column_down + down_sql

    for field_name in dropped_columns:
        before_column = before_columns[field_name]
        up_sql.append(drop_column_sql(before_table.name, before_column.name))
        down_sql.insert(0, add_column_sql(before_table.name, before_column))

    before_indexes = before_table.indexes
    after_indexes = after_table.indexes

    before_index_names = set(before_indexes)
    after_index_names = set(after_indexes)

    created_indexes = sorted(after_index_names - before_index_names)
    dropped_indexes = sorted(before_index_names - after_index_names)

    for index_name in created_indexes:
        index = after_indexes[index_name]
        up_sql.append(create_index_sql(after_table.name, index))
        down_sql.insert(0, drop_index_sql(index.name))

    for index_name in dropped_indexes:
        index = before_indexes[index_name]
        up_sql.append(drop_index_sql(index.name))
        down_sql.insert(0, create_index_sql(before_table.name, index))

    return up_sql, down_sql


def _plan_column_changes(
    table_name: str,
    before_column: ColumnSchema,
    after_column: ColumnSchema,
) -> tuple[list[str], list[str]]:
    up_sql: list[str] = []
    down_sql: list[str] = []

    if before_column.db_type != after_column.db_type:
        up_sql.append(alter_column_type_sql(table_name, before_column.name, after_column.db_type))
        down_sql.insert(
            0,
            alter_column_type_sql(table_name, before_column.name, before_column.db_type),
        )

    if before_column.nullable != after_column.nullable:
        up_sql.append(
            alter_column_nullable_sql(
                table_name,
                before_column.name,
                nullable=after_column.nullable,
            )
        )
        down_sql.insert(
            0,
            alter_column_nullable_sql(
                table_name,
                before_column.name,
                nullable=before_column.nullable,
            ),
        )

    return up_sql, down_sql
