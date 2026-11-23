"""The supported mapping is a single, fully loaded row, not an ORM graph."""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

import cedarpy
from sqlalchemy import TEXT, VARCHAR, Column, String, Table, Text, Unicode, UnicodeText
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import ColumnProperty, Mapped, class_mapper
from sqlalchemy.orm.attributes import instance_state

from cedarpy_sqlalchemy._rules import Rule


class CedarAuthorizationMixin:
    """Opt an application-owned mapped class into Cedar reads. Adds no columns."""

    cedar_type: ClassVar[str | None] = None
    cedar_rules: ClassVar[tuple[Rule, ...] | None] = None

    if TYPE_CHECKING:
        # The mapper check below requires this existing application column.
        id: Mapped[str]


_INFO_KEY = "cedarpy_sqlalchemy"
_MAPPED_NAME = object()


@dataclass(frozen=True, slots=True)
class _Attribute:
    name: str
    reference: str | None = None

    def encode(self, value: str) -> str | dict[str, dict[str, str]]:
        if self.reference is None:
            return value
        return {"__entity": {"type": self.reference, "id": value}}


def enum_type(enum: type[StrEnum]) -> SqlEnum:
    """Store StrEnum values as text and return enum members on ORM reads."""
    if not issubclass(enum, StrEnum):
        raise TypeError("expected a StrEnum class")
    return SqlEnum(
        enum,
        native_enum=False,
        values_callable=lambda members: [m.value for m in members],
    )


def attr(name: str | None = None) -> dict[str, object]:
    """Expose a Cedar string under the mapped attribute name or an explicit alias."""
    if name is None:
        return {_INFO_KEY: _MAPPED_NAME}
    if not isinstance(name, str) or not name:
        raise ValueError("expected a Cedar attribute name")
    return {_INFO_KEY: _Attribute(name)}


def _type_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise ValueError("expected an unnamespaced Cedar entity type")
    return name


def ref(name: str, target: str) -> dict[str, _Attribute]:
    """Project a non-null string column as the id of a fixed Cedar entity type."""
    if not isinstance(name, str) or not name:
        raise ValueError("expected a Cedar attribute name")
    return {_INFO_KEY: _Attribute(name, _type_name(target))}


@dataclass(frozen=True, slots=True)
class _Field:
    key: str
    fact: _Attribute
    column: Column[str]
    enum_class: type[StrEnum] | None = None

    @classmethod
    def from_column(cls, key: str, fact: _Attribute, column: Column) -> "_Field":
        sql_type = column.type
        if fact.reference is not None or type(sql_type) is not SqlEnum:
            _check_string(column)
            return cls(key, fact, column)

        enum = sql_type.enum_class
        if (
            column.nullable is not False
            or sql_type.native_enum
            or sql_type._variant_mapping
            or enum is None
            or not issubclass(enum, StrEnum)
            or not sql_type.enums
            or len(enum.__members__) != len(enum)  # no alias-dependent ordering
            or len(sql_type.enums) != len(enum)
            or any(
                type(label) is not str
                or type(member.value) is not str
                or label != member.value
                or sql_type._object_lookup.get(label) is not member
                or sql_type._valid_lookup.get(member) != label
                for label, member in zip(
                    sql_type.enums, enum.__members__.values(), strict=True
                )
            )
        ):
            raise ValueError(
                f"{column.key}: expected a non-null, value-storing non-native StrEnum"
            )

        # Only the predicate sees VARCHAR. Bind arbitrary Cedar literals as text
        # even when validate_strings=True; leave the mapper's result type intact.
        predicate_column = Column(column.name, String(), nullable=False)
        predicate_column.table = column.table
        return cls(key, fact, predicate_column, enum)


def _check_string(column: Column) -> None:
    # Reject custom bind/result conversions, non-text affinity and variants.
    if (
        column.nullable is not False
        or type(column.type) not in (String, Text, Unicode, UnicodeText, TEXT, VARCHAR)
        or column.type._variant_mapping
    ):
        raise ValueError(f"{column.key}: expected a non-null plain string column")


@dataclass(frozen=True, slots=True)
class Projection[T: CedarAuthorizationMixin]:
    model: type[T]
    kind: str
    primary: Column[str]
    fields: tuple[_Field, ...]

    @classmethod
    def from_model(cls, model: type[T]) -> "Projection[T]":
        if not issubclass(model, CedarAuthorizationMixin):
            raise TypeError("expected a mapped CedarAuthorizationMixin subclass")
        mapper = class_mapper(model)
        table = mapper.local_table
        if (
            not isinstance(table, Table)
            or any("__mapper_args__" in c.__dict__ for c in model.__mro__)
            or mapper.inherits is not None
            or any(m is not mapper for m in mapper.self_and_descendants)
            or mapper.relationships
        ):
            raise ValueError("only flat models without mapper options are supported")
        primary = mapper.primary_key
        if (
            len(primary) != 1
            or primary[0] is not table.c.get("id")
            or tuple(table.primary_key) != primary
            or mapper.get_property_by_column(primary[0]).key != "id"
        ):
            raise ValueError("expected a single string id primary key")
        _check_string(primary[0])
        fields = []
        for prop in mapper.attrs:
            if (
                not isinstance(prop, ColumnProperty)
                or len(prop.columns) != 1
                or not isinstance(column := prop.columns[0], Column)
                or column.table is not table
                or prop.deferred
            ):
                raise ValueError(f"{prop.key}: expected a loaded table column")
            if _INFO_KEY in column.info:
                fact = column.info[_INFO_KEY]
                if fact is _MAPPED_NAME:
                    fact = _Attribute(prop.key)
                if not isinstance(fact, _Attribute):
                    raise ValueError(f"{prop.key}: expected attr() or ref()")
                fields.append(_Field.from_column(prop.key, fact, column))
        if len({f.fact.name for f in fields}) != len(fields):
            raise ValueError("duplicate Cedar attribute name")
        kind = _type_name(
            model.__name__ if model.cedar_type is None else model.cedar_type
        )
        if kind in ("Action", "User"):
            raise ValueError(
                "resource type cannot also be the principal or action type"
            )
        return cls(model, kind, primary[0], tuple(fields))

    def read_schema(self) -> cedarpy.Schema:
        """Build the schema for model-declared User/read rules from projected facts."""
        attrs = {
            f.fact.name: (
                {"type": "Entity", "name": f.fact.reference}
                if f.fact.reference is not None
                else {"type": "String"}
            )
            for f in self.fields
        }
        entities = {
            f.fact.reference: {} for f in self.fields if f.fact.reference is not None
        }
        entities["User"] = {}
        entities[self.kind] = {"shape": {"type": "Record", "attributes": attrs}}
        read = {"appliesTo": {"principalTypes": ["User"], "resourceTypes": [self.kind]}}
        return cedarpy.Schema.from_json_str(
            json.dumps(
                {
                    "": {"entityTypes": entities, "actions": {"read": read}},
                }
            )
        )

    def validate_schema(self, schema: cedarpy.Schema) -> None:
        """Check the projected entity shapes, not the DDL, stored IDs or action scope.

        Like a real read, the sample contains a flat resource and an empty User.
        Cedar checks the types of UID references without needing target entities.
        """
        sample = "projection-sample"
        attrs = {f.fact.name: f.fact.encode(sample) for f in self.fields}
        entities = [
            {"uid": {"type": self.kind, "id": sample}, "attrs": attrs, "parents": []},
            {"uid": {"type": "User", "id": sample}, "attrs": {}, "parents": []},
        ]
        try:
            cedarpy.Entities.from_json_str(json.dumps(entities), schema=schema)
        except ValueError as exc:
            raise ValueError(
                f"{self.model.__name__}: projection for {self.kind} or empty User "
                f"does not match the Cedar schema: {exc}"
            ) from exc

    def entity(self, row: T) -> dict:
        state = instance_state(row)
        if type(row) is not self.model or state.unloaded or state.mapper.relationships:
            raise ValueError("expected a fully loaded flat resource")
        key = state.attrs["id"].loaded_value
        if type(key) is not str:
            raise TypeError("expected a loaded string id")
        attrs = {}
        for field in self.fields:
            value = state.attrs[field.key].loaded_value
            if field.enum_class is not None:
                if type(value) is not field.enum_class:
                    raise TypeError(
                        f"{field.key}: expected a loaded {field.enum_class.__name__}"
                    )
                value = value.value
            if type(value) is not str:
                raise TypeError(f"{field.key}: expected a loaded string")
            attrs[field.fact.name] = field.fact.encode(value)
        return {"uid": {"type": self.kind, "id": key}, "attrs": attrs, "parents": []}
