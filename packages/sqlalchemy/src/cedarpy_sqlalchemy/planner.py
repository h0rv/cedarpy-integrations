"""Cedar selects candidates; only concrete authorization releases a row."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import cedarpy
from cedarpy import pst
from sqlalchemy import (
    TEXT,
    VARCHAR,
    Column,
    String,
    Text,
    Unicode,
    UnicodeText,
    and_,
    case,
    false,
    not_,
    or_,
    true,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect
from sqlalchemy.sql import ColumnElement


@dataclass(frozen=True, slots=True)
class Denied:
    """The read needs no candidate query."""


@dataclass(frozen=True, slots=True)
class Candidates:
    """SQL can narrow this read. It cannot authorize a row."""

    candidate_predicate: ColumnElement[bool]
    residuals: Mapping[str, pst.Template]
    widened_permits: tuple[str, ...]


type ReadPlan = Denied | Candidates


class UnsupportedForbid(ValueError):
    """A relevant forbid cannot be translated exactly for this projection."""


class _Unsupported(ValueError):
    """No exact SQL translation for this entire residual policy."""


@dataclass(frozen=True, slots=True)
class Reference:
    """A Cedar UID attribute projected from (one fixed type, one SQL ID)."""

    entity_type: str
    column: Column[str]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.entity_type):
            raise ValueError("expected an unnamespaced Cedar reference type")


@dataclass(frozen=True, slots=True)
class _Columns:
    fields: Mapping[str, Column[str] | Reference]
    dialect: Dialect
    collation: str


_DIALECTS = {
    "sqlite": (sqlite.dialect(), "BINARY"),
    "postgresql": (postgresql.dialect(), "C"),
}
_PLAIN_TEXT = (String, Text, VARCHAR, TEXT, Unicode, UnicodeText)


def _checked_column(
    attr: str, col: Column[str], columns: _Columns
) -> ColumnElement[str]:
    if col.nullable is not False or type(col.type) not in _PLAIN_TEXT:
        raise _Unsupported(f"{attr!r} is not a declared nonnull string column")
    # A dialect variant can change affinity, comparison, or bound values.
    impl = col.type.dialect_impl(columns.dialect)
    if (
        not isinstance(impl, String)
        or type(impl) not in _PLAIN_TEXT
        or (impl.collation is not None and impl.collation != columns.collation)
    ):
        raise _Unsupported(f"{attr!r} is not a plain binary-comparable string column")
    return col.collate(columns.collation)


def _equal(
    attr: str, literal: pst.StringLit | pst.EntityLit, columns: _Columns
) -> ColumnElement[bool]:
    match columns.fields.get(attr), literal:
        case Column() as col, pst.StringLit(value):
            return _checked_column(attr, col, columns) == value
        case Reference(entity_type, col), pst.EntityLit(uid):
            column = _checked_column(attr, col, columns)
            return (
                column == uid.id if uid.type == pst.EntityType(entity_type) else false()
            )
        case _:
            raise _Unsupported(
                f"no matching projection for {attr!r} and {type(literal).__name__}"
            )


def _expr(node: pst.Expr, columns: _Columns) -> ColumnElement[bool]:
    # Either every operand is exact and total, or the whole policy is unsupported.
    # In particular, substituting TRUE *inside* a negation could lose candidates.
    match node:
        case pst.BoolLit(value=v):
            return true() if v else false()
        case pst.BinaryOp(op="eq" | "not_eq" as op, left=left, right=right):
            match left, right:
                case (
                    pst.GetAttr(pst.Var("resource"), attr),
                    (pst.StringLit() | pst.EntityLit()) as literal,
                ) | (
                    (pst.StringLit() | pst.EntityLit()) as literal,
                    pst.GetAttr(pst.Var("resource"), attr),
                ):
                    pred = _equal(attr, literal, columns)
                    return pred if op == "eq" else not_(pred)
        case pst.UnaryOp(op="not", arg=arg):
            return not_(_expr(arg, columns))
        case pst.BinaryOp(op="and" | "or" as op, left=left, right=right):
            lhs, rhs = _expr(left, columns), _expr(right, columns)
            return and_(lhs, rhs) if op == "and" else or_(lhs, rhs)
        case pst.IfThenElse(cond=cond, then_expr=t, else_expr=f):
            return case(
                (_expr(cond, columns), _expr(t, columns)), else_=_expr(f, columns)
            )
    raise _Unsupported(f"unsupported Cedar expression: {type(node).__name__}")


def _policy(policy: pst.Template, columns: _Columns) -> ColumnElement[bool]:
    # In this TPE revision nontrivial head constraints move into clauses.
    # Never drop one if a residual still has it in the head.
    if not all(
        isinstance(scope, pst.ScopeAny)
        for scope in (policy.principal, policy.action, policy.resource)
    ):
        raise _Unsupported("remaining policy scope")
    parts: list[ColumnElement[bool]] = []
    for clause in policy.clauses:
        match clause:
            case pst.When(expr):
                parts.append(_expr(expr, columns))
            case pst.Unless(expr):
                parts.append(not_(_expr(expr, columns)))
            case _:
                raise _Unsupported("unknown clause")
    return and_(true(), *parts)


def _evaluate(
    policies: cedarpy.PolicySet,
    schema: cedarpy.Schema,
    principal_id: str,
    resource_type: str,
    action: str,
    context: dict[str, str | bool | int] | None,
    resource_id: str | None = None,
) -> cedarpy.TpeAuthzResult:
    principal = {"type": "User", "id": principal_id}
    entities = [{"uid": principal}]
    resource: pst.EntityType | dict[str, str] = pst.EntityType(resource_type)
    if resource_id is not None:
        resource = {"type": resource_type, "id": resource_id}
        entities.append(
            {"uid": resource}
        )  # Known UID; row attributes are still unknown.
    return cedarpy.tpe_authorize(
        principal=principal,
        action={"type": "Action", "id": action},
        resource=resource,
        policies=policies,
        entities=cedarpy.PartialEntities.from_json(entities),
        schema=schema,
        context=context,
    )


def _cannot_return_rows(result: cedarpy.TpeAuthzResult) -> bool:
    # Concrete reads reject any decision with evaluation errors, including Allow.
    return result.decision == cedarpy.Decision.Deny or bool(
        result.permits.error_ids or result.forbids.error_ids
    )


def denied_without_context(
    policies: cedarpy.PolicySet,
    schema: cedarpy.Schema,
    principal_id: str,
    resource_type: str,
    *,
    action: str = "read",
    resource_id: str | None = None,
) -> bool:
    """Only a definite deny with context *unknown* can skip its trusted loader."""
    return _cannot_return_rows(
        _evaluate(
            policies, schema, principal_id, resource_type, action, None, resource_id
        )
    )


def plan(
    policies: cedarpy.PolicySet,
    schema: cedarpy.Schema,
    principal_id: str,
    resource_type: str,
    columns: Mapping[str, Column[str]],
    *,
    dialect: str,
    action: str = "read",
    context: Mapping[str, str | bool | int] = MappingProxyType({}),
    references: Mapping[str, Reference] | None = None,
) -> ReadPlan:
    """Return a typed plan for a superset of allowed resources, not a filter safe to expose alone.

    The caller supplies only columns projected verbatim to Cedar string attributes
    on each resource. References separately declare a fixed UID type and ID column;
    no graph traversal is implied. DDL must match those declarations. The reader
    checks every candidate against the original policies before returning it.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", resource_type):
        raise ValueError("expected an unnamespaced Cedar resource type")
    projection: dict[str, Column[str] | Reference] = dict(columns)
    if references:
        if projection.keys() & references.keys():
            raise ValueError(
                "a Cedar attribute cannot be both a string and a reference"
            )
        projection.update(references)
    sql_columns = _Columns(projection, *_DIALECTS[dialect])
    result = _evaluate(
        policies,
        schema,
        principal_id,
        resource_type,
        action,
        dict(context),
    )
    if _cannot_return_rows(result):
        return Denied()

    # Check every residual forbid before allowing even a known-true permit.
    excludes: list[ColumnElement[bool]] = []
    for policy_id in result.forbids.residual_ids:
        try:
            excludes.append(
                not_(_policy(result.residual_policies[policy_id], sql_columns))
            )
        except _Unsupported as exc:
            raise UnsupportedForbid(f"{policy_id}: {exc}") from exc

    permits: list[ColumnElement[bool]] = []
    widened: list[str] = []
    if result.permits.true_ids:
        permits.append(true())
    else:
        for policy_id in result.permits.residual_ids:
            try:
                permits.append(
                    _policy(result.residual_policies[policy_id], sql_columns)
                )
            except _Unsupported:
                widened.append(policy_id)
                permits.append(true())
    predicate = and_(or_(false(), *permits), *excludes)
    if predicate.compare(false()):
        return Denied()
    return Candidates(
        predicate, MappingProxyType(dict(result.residual_policies)), tuple(widened)
    )
