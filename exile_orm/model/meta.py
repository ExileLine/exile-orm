"""Model metaclass for collecting field metadata."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from exile_orm.core.exceptions import ModelDefinitionError
from exile_orm.model.fields import Field, ForeignKey, ManyToMany, OneToOne
from exile_orm.model.relations import (
    ReverseManyToManyDescriptor,
    ReverseOneToOneDescriptor,
    ReverseRelationDescriptor,
)


class ModelMeta(type):
    """Collects `Field` descriptors and validates model declarations."""

    def __new__(
        mcls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
    ) -> type[Any]:
        inherited_fields: OrderedDict[str, Field[Any]] = OrderedDict()
        for base in bases:
            base_fields = getattr(base, "__fields__", None)
            if base_fields:
                inherited_fields.update(base_fields)

        own_fields: OrderedDict[str, Field[Any]] = OrderedDict()
        own_many_to_many: OrderedDict[str, ManyToMany] = OrderedDict()
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, Field):
                attr_value.bind(attr_name)
                own_fields[attr_name] = attr_value
                continue
            if isinstance(attr_value, ManyToMany):
                own_many_to_many[attr_name] = attr_value

        fields = OrderedDict[str, Field[Any]]()
        fields.update(inherited_fields)
        fields.update(own_fields)
        inherited_many_to_many: OrderedDict[str, ManyToMany] = OrderedDict()
        for base in bases:
            base_many_to_many = getattr(base, "__many_to_many__", None)
            if base_many_to_many:
                inherited_many_to_many.update(base_many_to_many)

        many_to_many = OrderedDict[str, ManyToMany]()
        many_to_many.update(inherited_many_to_many)
        many_to_many.update(own_many_to_many)
        relations = OrderedDict[str, ForeignKey]()
        for field_name, field in fields.items():
            if isinstance(field, ForeignKey):
                relations[field_name] = field

        cls = super().__new__(mcls, name, bases, namespace)
        runtime_cls = cast(Any, cls)
        runtime_cls.__fields__ = fields
        runtime_cls.__relations__ = relations
        runtime_cls.__many_to_many__ = many_to_many
        for relation_name, relation in own_many_to_many.items():
            relation.bind(relation_name, cast(Any, cls))

        table_name = namespace.get("__table_name__", name.lower())
        runtime_cls.__table_name__ = table_name

        primary_keys = [field for field in fields.values() if field.primary_key]
        if len(primary_keys) > 1:
            raise ModelDefinitionError(
                f"Model '{name}' defines multiple primary keys. "
                "Composite keys are not supported yet."
            )

        primary_key = primary_keys[0] if primary_keys else None
        runtime_cls.__primary_key__ = primary_key

        if not hasattr(cls, "__database__"):
            runtime_cls.__database__ = None

        for relation_field_name, fk_relation in relations.items():
            try:
                related_model = fk_relation.related_model()
            except Exception:  # noqa: BLE001
                continue

            descriptor: object
            if isinstance(fk_relation, OneToOne):
                related_name = fk_relation.related_name or name.lower()
                descriptor = ReverseOneToOneDescriptor(cast(Any, cls), relation_field_name)
            else:
                related_name = fk_relation.related_name or f"{name.lower()}_set"
                descriptor = ReverseRelationDescriptor(cast(Any, cls), relation_field_name)
            if hasattr(related_model, related_name):
                continue
            setattr(related_model, related_name, descriptor)

        for m2m_relation in many_to_many.values():
            try:
                related_model = m2m_relation.related_model()
            except Exception:  # noqa: BLE001
                continue

            related_name = m2m_relation.related_name or f"{name.lower()}_set"
            if hasattr(related_model, related_name):
                continue
            setattr(related_model, related_name, ReverseManyToManyDescriptor(m2m_relation))

        return cls
