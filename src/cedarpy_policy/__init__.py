"""Build scoped Cedar policies from symbolic Python expressions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from cedarpy import PolicySet, pst

from . import nodes


@dataclass(frozen=True, slots=True)
class Scope:
    action: str
    principal_type: str
    resource_type: str
    resource_id: str | None = None


class _Action(Protocol):
    @property
    def scope(self) -> Scope: ...


@dataclass(frozen=True, slots=True, eq=False)
class _Expression:
    scope: Scope
    _node: pst.Expr

    def _require_scope(self, scope: Scope) -> None:
        if self.scope != scope:
            raise ValueError("Expressions must belong to the same request scope")

    # Type unsupported Python operators as bool so they cannot supply a Condition.
    def __bool__(self) -> bool:
        raise TypeError("A Cedar expression has no Python truth value; use &, |, or ~")

    def __ne__(self, other: object) -> bool:
        raise TypeError("Use ~(left == right) for Cedar inequality")


@dataclass(frozen=True, slots=True, eq=False)
class Condition(_Expression):
    def __eq__(self, other: object) -> bool:
        raise TypeError("This Cedar expression does not support equality")

    def __and__(self, other: Condition) -> Condition:
        return Condition(
            self.scope,
            nodes.and_(self._node, _condition_node(other, self.scope)),
        )

    def __or__(self, other: Condition) -> Condition:
        return Condition(
            self.scope,
            nodes.or_(self._node, _condition_node(other, self.scope)),
        )

    def __invert__(self) -> Condition:
        return Condition(self.scope, nodes.not_(self._node))


def _condition_node(condition: Condition, scope: Scope) -> pst.Expr:
    if not isinstance(condition, Condition):
        raise TypeError("Expected a symbolic Cedar Condition")
    condition._require_scope(scope)
    return condition._node


@dataclass(frozen=True, slots=True, eq=False)
class EntityExpr(_Expression):
    target: str

    def __eq__(self, other: EntityExpr) -> Condition:  # ty: ignore[incompatible-method-override]
        if not isinstance(other, EntityExpr) or self.target != other.target:
            raise TypeError("Expected a symbolic entity of the same Cedar type")
        other._require_scope(self.scope)
        return Condition(self.scope, nodes.eq(self._node, other._node))


@dataclass(frozen=True, slots=True, eq=False)
class EnumExpr[E: StrEnum](_Expression):
    enum: type[E]

    def __eq__(self, other: E) -> Condition:  # ty: ignore[incompatible-method-override]
        if type(other) is not self.enum:
            raise TypeError(f"Expected a member of {self.enum.__name__}")
        return Condition(self.scope, nodes.eq(self._node, pst.StringLit(other.value)))


def entity_principal(scope: Scope) -> EntityExpr:
    return EntityExpr(scope, nodes.principal, scope.principal_type)


def entity_field(scope: Scope, name: str, target: str) -> EntityExpr:
    return EntityExpr(scope, nodes.field(nodes.resource, name), target)


def enum_field[E: StrEnum](scope: Scope, name: str, enum: type[E]) -> EnumExpr[E]:
    if not issubclass(enum, StrEnum):
        raise TypeError("Expected a StrEnum type")
    return EnumExpr(scope, nodes.field(nodes.resource, name), enum)


def bool_field(
    scope: Scope, root: Literal["principal", "context", "resource"], name: str
) -> Condition:
    if root not in ("principal", "context", "resource"):
        raise ValueError("Expected principal, context, or resource")
    return Condition(scope, nodes.field(pst.Var(root), name))


def policy(
    action: _Action, *, permit_when: Condition, forbid_when: Condition | None = None
) -> PolicySet:
    scope = action.scope
    resource = (
        nodes.entity_is(scope.resource_type)
        if scope.resource_id is None
        else nodes.entity_is_id(scope.resource_type, scope.resource_id)
    )

    principal = nodes.entity_is(scope.principal_type)
    action_constraint = nodes.action_is(scope.action)
    rules = {
        "permit": nodes.permit(
            id="permit",
            principal=principal,
            action=action_constraint,
            resource=resource,
            clauses=(pst.When(_condition_node(permit_when, scope)),),
            annotations={},
        )
    }
    if forbid_when is not None:
        rules["forbid"] = nodes.forbid(
            id="forbid",
            principal=principal,
            action=action_constraint,
            resource=resource,
            clauses=(pst.When(_condition_node(forbid_when, scope)),),
            annotations={},
        )
    return PolicySet.from_pst(
        pst.PolicySet(templates={}, static_policies=rules, template_links=())
    )
