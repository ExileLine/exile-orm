from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from exile_orm.migrations import (
    makemigrations,
    migrate,
    plan_migration,
    rollback,
    snapshot_from_models,
)
from exile_orm.migrations.files import MigrationFile, list_migration_files, write_migration_file
from exile_orm.model import (
    BooleanField,
    ForeignKey,
    IntegerField,
    ManyToMany,
    Model,
    StringField,
)


class Team(Model):
    __table_name__ = "teams"

    id = IntegerField(primary_key=True)
    name = StringField(unique=True)


class Member(Model):
    __table_name__ = "members"

    id = IntegerField(primary_key=True)
    name = StringField()
    team = ForeignKey(Team, related_name="members")


class ProductV1(Model):
    __table_name__ = "products"

    id = IntegerField(primary_key=True)
    name = StringField(index=True)
    active = BooleanField(default=True)


class ProductV2(Model):
    __table_name__ = "products"

    id = IntegerField(primary_key=True)
    name = IntegerField()
    quantity = IntegerField(index=True)


class Course(Model):
    __table_name__ = "courses"

    id = IntegerField(primary_key=True)
    title = StringField()


class Student(Model):
    __table_name__ = "students"

    id = IntegerField(primary_key=True)
    name = StringField()
    courses = ManyToMany(
        Course,
        related_name="students",
        through="student_courses",
        through_source_column="student_id",
        through_target_column="course_id",
    )


class FakeMigrationDatabase:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        if query.startswith("INSERT INTO schema_migrations"):
            self.applied.append((str(args[0]), str(args[1])))
            return "INSERT 1"
        if query.startswith("DELETE FROM schema_migrations"):
            version = str(args[0])
            self.applied = [item for item in self.applied if item[0] != version]
            return "DELETE 1"
        return "EXECUTED"

    async def fetch_all(self, query: str, *args: object) -> list[dict[str, object]]:
        del args
        if query.startswith("SELECT version, name FROM schema_migrations"):
            return [{"version": version, "name": name} for version, name in self.applied]
        return []

    @asynccontextmanager
    async def transaction(self):
        self.transaction_entries += 1
        try:
            yield self
        finally:
            self.transaction_exits += 1


def test_plan_migration_for_create_table_and_indexes() -> None:
    before = snapshot_from_models([])
    after = snapshot_from_models([Team, Member])

    plan = plan_migration(before, after)

    assert any(sql.startswith('CREATE TABLE "members"') for sql in plan.up_sql)
    assert any(sql.startswith('CREATE TABLE "teams"') for sql in plan.up_sql)
    assert any('CREATE INDEX "idx_members_team_id" ON "members"' in sql for sql in plan.up_sql)
    assert any(
        'CREATE UNIQUE INDEX "uq_teams_name" ON "teams" ("name")' in sql for sql in plan.up_sql
    )
    assert any(sql.startswith('DROP TABLE "members"') for sql in plan.down_sql)
    assert any(sql.startswith('DROP TABLE "teams"') for sql in plan.down_sql)


def test_plan_migration_for_add_drop_alter_and_index_changes() -> None:
    before = snapshot_from_models([ProductV1])
    after = snapshot_from_models([ProductV2])

    plan = plan_migration(before, after)

    assert 'ALTER TABLE "products" ADD COLUMN "quantity" INTEGER NOT NULL' in plan.up_sql
    assert 'ALTER TABLE "products" DROP COLUMN "active"' in plan.up_sql
    assert 'ALTER TABLE "products" ALTER COLUMN "name" TYPE INTEGER' in plan.up_sql
    assert 'DROP INDEX "idx_products_name"' in plan.up_sql
    assert 'CREATE INDEX "idx_products_quantity" ON "products" ("quantity")' in plan.up_sql

    assert 'ALTER TABLE "products" ADD COLUMN "active" BOOLEAN NOT NULL' in plan.down_sql
    assert 'ALTER TABLE "products" DROP COLUMN "quantity"' in plan.down_sql
    assert 'ALTER TABLE "products" ALTER COLUMN "name" TYPE TEXT' in plan.down_sql
    assert 'CREATE INDEX "idx_products_name" ON "products" ("name")' in plan.down_sql
    assert 'DROP INDEX "idx_products_quantity"' in plan.down_sql


def test_makemigrations_writes_file_and_is_noop_without_changes(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "migrations" / "schema_snapshot.json"
    versions_dir = tmp_path / "migrations" / "versions"

    first = makemigrations(
        [Team, Member],
        name="init schema",
        snapshot_path=snapshot_path,
        migrations_dir=versions_dir,
    )
    second = makemigrations(
        [Team, Member],
        name="init schema",
        snapshot_path=snapshot_path,
        migrations_dir=versions_dir,
    )

    assert first is not None
    assert first.name == "init_schema"
    assert second is None
    assert snapshot_path.exists()
    assert len(list_migration_files(versions_dir)) == 1


def test_snapshot_and_plan_include_many_to_many_join_table() -> None:
    before = snapshot_from_models([])
    after = snapshot_from_models([Student, Course])
    plan = plan_migration(before, after)

    assert "student_courses" in after.tables
    assert any(sql.startswith('CREATE TABLE "student_courses"') for sql in plan.up_sql)
    create_students_sql = 'CREATE TABLE "students" ("id" INTEGER PRIMARY KEY, "name" TEXT NOT NULL)'
    create_courses_sql = 'CREATE TABLE "courses" ("id" INTEGER PRIMARY KEY, "title" TEXT NOT NULL)'
    create_join_sql = next(
        sql for sql in plan.up_sql if sql.startswith('CREATE TABLE "student_courses"')
    )
    assert plan.up_sql.index(create_students_sql) < plan.up_sql.index(create_join_sql)
    assert plan.up_sql.index(create_courses_sql) < plan.up_sql.index(create_join_sql)
    assert any(
        'REFERENCES "students"("id") ON DELETE CASCADE' in sql
        and 'CREATE TABLE "student_courses"' in sql
        for sql in plan.up_sql
    )
    assert any(
        'REFERENCES "courses"("id") ON DELETE CASCADE' in sql
        and 'CREATE TABLE "student_courses"' in sql
        for sql in plan.up_sql
    )
    assert any(
        sql
        == 'CREATE UNIQUE INDEX "uq_student_courses_student_id_course_id" '
        'ON "student_courses" ("student_id", "course_id")'
        for sql in plan.up_sql
    )
    assert 'DROP TABLE "student_courses"' in plan.down_sql
    assert 'DROP TABLE "students"' in plan.down_sql
    assert 'DROP TABLE "courses"' in plan.down_sql
    assert plan.down_sql.index('DROP TABLE "student_courses"') < plan.down_sql.index(
        'DROP TABLE "students"'
    )
    assert plan.down_sql.index('DROP TABLE "student_courses"') < plan.down_sql.index(
        'DROP TABLE "courses"'
    )


def test_snapshot_raises_on_conflicting_many_to_many_through_table() -> None:
    class Label(Model):
        __table_name__ = "labels"

        id = IntegerField(primary_key=True)
        name = StringField()

    class Story(Model):
        __table_name__ = "stories"

        id = IntegerField(primary_key=True)
        title = StringField()
        labels = ManyToMany(
            Label,
            through="story_links",
            through_source_column="story_id",
            through_target_column="label_id",
        )

    class Event(Model):
        __table_name__ = "events"

        id = IntegerField(primary_key=True)
        name = StringField()
        labels = ManyToMany(
            Label,
            through="story_links",
            through_source_column="event_id",
            through_target_column="label_id",
        )

    with pytest.raises(ValueError, match="Conflicting schema definitions"):
        snapshot_from_models([Story, Event, Label])


def test_plan_migration_drop_order_respects_foreign_key_dependencies() -> None:
    before = snapshot_from_models([Student, Course])
    after = snapshot_from_models([])
    plan = plan_migration(before, after)

    drop_join = 'DROP TABLE "student_courses"'
    drop_students = 'DROP TABLE "students"'
    drop_courses = 'DROP TABLE "courses"'
    assert drop_join in plan.up_sql
    assert drop_students in plan.up_sql
    assert drop_courses in plan.up_sql
    assert plan.up_sql.index(drop_join) < plan.up_sql.index(drop_students)
    assert plan.up_sql.index(drop_join) < plan.up_sql.index(drop_courses)


@pytest.mark.asyncio
async def test_migrate_and_rollback_are_idempotent(tmp_path: Path) -> None:
    versions_dir = tmp_path / "migrations" / "versions"
    write_migration_file(
        versions_dir,
        MigrationFile(
            version="20260101010101000000",
            name="create_users",
            up_sql=['CREATE TABLE "users" ("id" INTEGER PRIMARY KEY)'],
            down_sql=['DROP TABLE "users"'],
        ),
    )
    write_migration_file(
        versions_dir,
        MigrationFile(
            version="20260101010202000000",
            name="add_user_name",
            up_sql=['ALTER TABLE "users" ADD COLUMN "name" TEXT NOT NULL'],
            down_sql=['ALTER TABLE "users" DROP COLUMN "name"'],
        ),
    )

    db = FakeMigrationDatabase()
    applied_first = await migrate(db, migrations_dir=versions_dir)  # type: ignore[arg-type]
    applied_second = await migrate(db, migrations_dir=versions_dir)  # type: ignore[arg-type]
    rolled_back = await rollback(  # type: ignore[arg-type]
        db,
        migrations_dir=versions_dir,
        steps=1,
    )

    assert applied_first == ["20260101010101000000", "20260101010202000000"]
    assert applied_second == []
    assert rolled_back == ["20260101010202000000"]
    assert db.applied == [("20260101010101000000", "create_users")]
    assert db.transaction_entries == 3
    assert db.transaction_exits == 3
