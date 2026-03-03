from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

from exile_orm import makemigrations, migrate, rollback
from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.model import IntegerField, ManyToMany, Model, StringField


async def _table_exists(db: Database, table_name: str) -> bool:
    row = await db.fetch_one(
        "SELECT EXISTS ("
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = $1"
        ") AS exists_flag",
        table_name,
    )
    return bool(row and row["exists_flag"])


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL first.")

    suffix = uuid.uuid4().hex[:8]
    students_table = f"example_students_{suffix}"
    courses_table = f"example_courses_{suffix}"
    through_table = f"example_student_courses_{suffix}"

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

    with tempfile.TemporaryDirectory(prefix="exile_orm_migration_demo_") as tmp_dir:
        root = Path(tmp_dir)
        snapshot_path = root / "migrations" / "schema_snapshot.json"
        versions_dir = root / "migrations" / "versions"
        migration = makemigrations(
            models=[Student, Course],
            name="example many to many migration",
            snapshot_path=snapshot_path,
            migrations_dir=versions_dir,
        )
        if migration is None:
            raise RuntimeError("Expected a migration file to be generated.")

        db = Database(DatabaseConfig(dsn=dsn))
        await db.connect()
        Student.use_database(db)
        Course.use_database(db)

        try:
            applied = await migrate(db, migrations_dir=versions_dir)
            print(f"applied_migrations={applied}")

            alice = await Student.create(id=1, name="alice")
            orm_course = await Course.create(id=1, title="orm")
            await alice.courses.add(orm_course.id)
            linked = await alice.courses.all()
            print(f"linked_courses={[item.title for item in linked]}")

            rolled_back = await rollback(db, migrations_dir=versions_dir, steps=1)
            print(f"rolled_back_migrations={rolled_back}")
            print(
                "tables_exist_after_rollback="
                f"{await _table_exists(db, students_table)},"
                f"{await _table_exists(db, courses_table)},"
                f"{await _table_exists(db, through_table)}"
            )
        finally:
            await db.execute(f'DROP TABLE IF EXISTS "{through_table}"')
            await db.execute(f'DROP TABLE IF EXISTS "{students_table}"')
            await db.execute(f'DROP TABLE IF EXISTS "{courses_table}"')
            await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
