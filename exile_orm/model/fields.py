"""Field definitions used by model classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from exile_orm.core.exceptions import ModelValidationError

if TYPE_CHECKING:
    from exile_orm.model.base import Model

T = TypeVar("T")
DefaultFactory = Callable[[], T]


class Field(Generic[T]):
    """Data descriptor with runtime validation and metadata."""

    python_types: tuple[type[Any], ...] = (object,)

    def __init__(
        self,
        *,
        primary_key: bool = False,
        nullable: bool = False,
        default: T | DefaultFactory[T] | None = None,
        index: bool = False,
        unique: bool = False,
        column_name: str | None = None,
    ) -> None:
        self.primary_key = primary_key
        self.nullable = nullable
        self.default = default
        self.index = index
        self.unique = unique
        self.name = ""
        self.column_name = column_name

    def bind(self, name: str) -> None:
        self.name = name
        if self.column_name is None:
            self.column_name = name

    def get_default_value(self) -> T | None:
        if callable(self.default):
            return self.default()
        return self.default

    def validate(self, value: Any) -> None:
        if value is None:
            if self.primary_key or self.nullable:
                return
            raise ModelValidationError(f"Field '{self.name}' cannot be null.")

        if not isinstance(value, self.python_types):
            readable_types = ", ".join(t.__name__ for t in self.python_types)
            raise ModelValidationError(
                f"Field '{self.name}' expects {readable_types}, got {type(value).__name__}."
            )

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        if instance is None:
            return self
        return instance._data.get(self.name)

    def __set__(self, instance: Model, value: Any) -> None:
        instance._set_field(self, value, mark_dirty=not instance._is_initializing)

    def _binary(self, operator: str, value: Any) -> Any:
        from exile_orm.query.expressions import BinaryCondition

        return BinaryCondition(field=self, operator=operator, value=value)

    def __eq__(self, other: object) -> Any:
        return self._binary("=", other)

    def __ne__(self, other: object) -> Any:
        return self._binary("!=", other)

    def __gt__(self, other: Any) -> Any:
        return self._binary(">", other)

    def __ge__(self, other: Any) -> Any:
        return self._binary(">=", other)

    def __lt__(self, other: Any) -> Any:
        return self._binary("<", other)

    def __le__(self, other: Any) -> Any:
        return self._binary("<=", other)

    def in_(self, values: list[Any] | tuple[Any, ...]) -> Any:
        from exile_orm.query.expressions import InCondition

        return InCondition(field=self, values=tuple(values), negated=False)

    def not_in(self, values: list[Any] | tuple[Any, ...]) -> Any:
        from exile_orm.query.expressions import InCondition

        return InCondition(field=self, values=tuple(values), negated=True)

    def like(self, pattern: str) -> Any:
        return self._binary("LIKE", pattern)

    def ilike(self, pattern: str) -> Any:
        return self._binary("ILIKE", pattern)

    def is_null(self) -> Any:
        return self._binary("=", None)

    def is_not_null(self) -> Any:
        return self._binary("!=", None)


class IntegerField(Field[int]):
    python_types = (int,)


class StringField(Field[str]):
    python_types = (str,)


class BooleanField(Field[bool]):
    python_types = (bool,)


class DateTimeField(Field[datetime]):
    python_types = (datetime,)


class JSONField(Field[Any]):
    """Accepts any JSON-serializable Python object at runtime."""

    python_types = (object,)


class ForeignKey(Field[Any]):
    """Foreign key field pointing to another model."""

    python_types = (object,)

    def __init__(
        self,
        to: type[Model] | Callable[[], type[Model]],
        *,
        related_name: str | None = None,
        on_delete: str = "RESTRICT",
        primary_key: bool = False,
        nullable: bool = False,
        default: Any = None,
        index: bool = True,
        unique: bool = False,
        column_name: str | None = None,
    ) -> None:
        super().__init__(
            primary_key=primary_key,
            nullable=nullable,
            default=default,
            index=index,
            unique=unique,
            column_name=column_name,
        )
        self._to = to
        self.related_name = related_name
        self.on_delete = on_delete

    def bind(self, name: str) -> None:
        super().bind(name)
        if self.column_name == name:
            self.column_name = f"{name}_id"

    def related_model(self) -> type[Model]:
        if isinstance(self._to, type):
            return cast("type[Model]", self._to)
        resolved = self._to()
        self._to = resolved
        return resolved

    def validate(self, value: Any) -> None:
        if value is None:
            if self.nullable or self.primary_key:
                return
            raise ModelValidationError(f"Field '{self.name}' cannot be null.")

        related_model = self.related_model()
        if isinstance(value, related_model):
            return

        primary_key = related_model.__primary_key__
        if primary_key is None:
            raise ModelValidationError(
                f"Related model '{related_model.__name__}' does not define primary key."
            )
        if not isinstance(value, primary_key.python_types):
            readable_types = ", ".join(t.__name__ for t in primary_key.python_types)
            raise ModelValidationError(
                f"Field '{self.name}' expects related key type {readable_types}, "
                f"got {type(value).__name__}."
            )

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        if instance is None:
            return self
        if self.name in instance._related_cache:
            return instance._related_cache[self.name]
        return instance._data.get(self.name)

    def __set__(self, instance: Model, value: Any) -> None:
        if value is not None and isinstance(value, self.related_model()):
            related_instance = value
            related_primary_key = related_instance.__class__.__primary_key__
            if related_primary_key is None:
                raise ModelValidationError("Related instance model has no primary key.")
            related_primary_value = related_instance._data.get(related_primary_key.name)
            if related_primary_value is None:
                raise ModelValidationError(
                    f"Cannot assign unsaved related instance to field '{self.name}'."
                )
            instance._related_cache[self.name] = related_instance
            instance._set_field(
                self,
                related_primary_value,
                mark_dirty=not instance._is_initializing,
            )
            return

        instance._related_cache.pop(self.name, None)
        instance._set_field(self, value, mark_dirty=not instance._is_initializing)


class OneToOne(ForeignKey):
    """One-to-one relation modeled as a unique foreign key."""

    def __init__(
        self,
        to: type[Model] | Callable[[], type[Model]],
        *,
        related_name: str | None = None,
        on_delete: str = "RESTRICT",
        primary_key: bool = False,
        nullable: bool = False,
        default: Any = None,
        index: bool = True,
        unique: bool = True,
        column_name: str | None = None,
    ) -> None:
        if not unique:
            raise ModelValidationError("OneToOne field must be unique.")
        super().__init__(
            to,
            related_name=related_name,
            on_delete=on_delete,
            primary_key=primary_key,
            nullable=nullable,
            default=default,
            index=index,
            unique=True,
            column_name=column_name,
        )


class ManyToMany:
    """Many-to-many relation descriptor backed by an explicit join table."""

    def __init__(
        self,
        to: type[Model] | Callable[[], type[Model]],
        *,
        related_name: str | None = None,
        through: str | None = None,
        through_source_column: str | None = None,
        through_target_column: str | None = None,
    ) -> None:
        self._to = to
        self.related_name = related_name
        self.through = through
        self.through_source_column = through_source_column
        self.through_target_column = through_target_column
        self.name = ""
        self.model_cls: type[Model] | None = None

    def bind(self, name: str, owner: type[Model]) -> None:
        self.name = name
        self.model_cls = owner

    def related_model(self) -> type[Model]:
        if isinstance(self._to, type):
            return cast("type[Model]", self._to)
        resolved = self._to()
        self._to = resolved
        return resolved

    def through_table(self) -> str:
        if self.through is not None:
            return self.through
        owner = self._require_owner()
        return f"{owner.__table_name__}_{self.name}"

    def source_column(self) -> str:
        if self.through_source_column is not None:
            return self.through_source_column
        owner = self._require_owner()
        return f"{owner.__name__.lower()}_id"

    def target_column(self) -> str:
        if self.through_target_column is not None:
            return self.through_target_column
        related = self.related_model()
        return f"{related.__name__.lower()}_id"

    def _require_owner(self) -> type[Model]:
        if self.model_cls is None:
            raise ModelValidationError("ManyToMany field is not bound to a model class.")
        return self.model_cls

    def __get__(self, instance: Model | None, owner: type[Model]) -> Any:
        del owner
        if instance is None:
            return self
        from exile_orm.model.relations import ManyToManyManager

        return ManyToManyManager(instance=instance, relation=self, reverse=False)
