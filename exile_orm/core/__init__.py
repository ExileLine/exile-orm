"""Core primitives: database access, transactions and shared exceptions."""

from exile_orm.core.database import Database, DatabaseConfig
from exile_orm.core.exceptions import (
    CheckConstraintError,
    ConnectionError,
    DatabaseNotConnectedError,
    ForeignKeyConstraintError,
    IntegrityError,
    MissingDependencyError,
    ModelDefinitionError,
    ModelNotFoundError,
    ModelValidationError,
    NotNullConstraintError,
    ORMError,
    QueryError,
    UniqueConstraintError,
)

__all__ = [
    "CheckConstraintError",
    "ConnectionError",
    "Database",
    "DatabaseConfig",
    "DatabaseNotConnectedError",
    "ForeignKeyConstraintError",
    "IntegrityError",
    "MissingDependencyError",
    "ModelDefinitionError",
    "ModelNotFoundError",
    "ModelValidationError",
    "NotNullConstraintError",
    "ORMError",
    "QueryError",
    "UniqueConstraintError",
]
