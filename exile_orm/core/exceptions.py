"""Base exception hierarchy for exile_orm."""


class ORMError(Exception):
    """Base class for ORM-level errors."""


class MissingDependencyError(ORMError):
    """Raised when required runtime dependencies are missing."""


class ConnectionError(ORMError):
    """Raised when database connection/pool operations fail."""


class DatabaseNotConnectedError(ConnectionError):
    """Raised when trying to use the database before connecting."""


class QueryError(ORMError):
    """Raised when a SQL query execution fails."""


class IntegrityError(QueryError):
    """Raised when a database integrity constraint is violated."""


class UniqueConstraintError(IntegrityError):
    """Raised on unique constraint violations."""


class ForeignKeyConstraintError(IntegrityError):
    """Raised on foreign key constraint violations."""


class NotNullConstraintError(IntegrityError):
    """Raised on not-null constraint violations."""


class CheckConstraintError(IntegrityError):
    """Raised on check constraint violations."""


class ModelDefinitionError(ORMError):
    """Raised when model definition is invalid."""


class ModelValidationError(ORMError):
    """Raised when model data fails validation."""


class ModelNotFoundError(ORMError):
    """Raised when the requested model instance does not exist."""
