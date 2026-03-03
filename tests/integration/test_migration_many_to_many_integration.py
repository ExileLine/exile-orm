from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from exile_orm import makemigrations, migrate, rollback
from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, ManyToMany, Model, StringField

DATABASE_URL = os.getenv("EXILE_ORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="Set EXILE_ORM_TEST_DATABASE_URL to run integration database tests.",
    ),
]


async def _table_exists(db: Database, table_name: str) -> bool:
    row = await db.fetch_one(
        "SELECT EXISTS ("
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = $1"
        ") AS exists_flag",
        table_name,
    )
    assert row is not None
    return bool(row["exists_flag"])


@pytest.mark.asyncio
async def test_migration_many_to_many_end_to_end(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:8]
    students_table = f"mig_students_{suffix}"
    courses_table = f"mig_courses_{suffix}"
    through_table = f"mig_student_courses_{suffix}"

    class Course(Model):
        __table_name__ = courses_table

        id = IntegerField(primary_key=True)
        title = StringField()

    class Student(Model):
        __table_name__ = students_table

        id = IntegerField(primary_key=True)
        name = StringField()
        courses = ManyToMany(
            Course,
            related_name="students",
            through=through_table,
            through_source_column="student_id",
            through_target_column="course_id",
        )

    snapshot_path = tmp_path / "migrations" / "schema_snapshot.json"
    versions_dir = tmp_path / "migrations" / "versions"
    migration = makemigrations(
        models=[Student, Course],
        name="create many to many schema",
        snapshot_path=snapshot_path,
        migrations_dir=versions_dir,
    )
    assert migration is not None

    db = Database(DatabaseConfig(dsn=DATABASE_URL))
    await db.connect()
    Student.use_database(db)
    Course.use_database(db)

    try:
        applied = await migrate(db, migrations_dir=versions_dir)
        assert applied == [migration.version]
        assert await _table_exists(db, students_table) is True
        assert await _table_exists(db, courses_table) is True
        assert await _table_exists(db, through_table) is True

        student = await Student.create(id=1, name="alice")
        course = await Course.create(id=1, title="orm")
        await student.courses.add(course)
        linked = await student.courses.all()
        assert [item.title for item in linked] == ["orm"]

        rolled_back = await rollback(db, migrations_dir=versions_dir, steps=1)
        assert rolled_back == [migration.version]
        assert await _table_exists(db, through_table) is False
        assert await _table_exists(db, students_table) is False
        assert await _table_exists(db, courses_table) is False
    finally:
        await db.execute(f'DROP TABLE IF EXISTS "{through_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{students_table}"')
        await db.execute(f'DROP TABLE IF EXISTS "{courses_table}"')
        await db.disconnect()
