"""Projection-checked equality rules compiled to static Cedar policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Final

import cedarpy
from cedarpy import pst

if TYPE_CHECKING:
    from cedarpy_sqlalchemy._model import Projection


class _Principal(Enum):
    REQUEST = auto()


principal: Final = _Principal.REQUEST
type _Value = str | _Principal


@dataclass(frozen=True, slots=True, init=False)
class Rule:
    effect: pst.Effect
    conditions: tuple[tuple[str, _Value], ...]

    def __init__(self, effect: pst.Effect, /, **conditions: _Value) -> None:
        if effect not in ("permit", "forbid"):
            raise ValueError("expected a permit or forbid rule")
        if not conditions:
            raise ValueError("a rule requires at least one condition")
        for name, value in conditions.items():
            if type(value) is not str and value is not principal:
                raise TypeError(f"{name!r}: expected a string or principal")
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "conditions", tuple(conditions.items()))


def permit_if(**conditions: _Value) -> Rule:
    """Permit when all named resource facts equal their supplied values."""
    return Rule("permit", **conditions)


def forbid_if(**conditions: _Value) -> Rule:
    """Forbid when all named resource facts equal their supplied values."""
    return Rule("forbid", **conditions)


def _condition(name: str, value: _Value, references: dict[str, str | None]) -> pst.When:
    if name not in references:
        raise ValueError(f"unknown projected fact {name!r}")
    target = references[name]
    if isinstance(value, str):
        if target is not None:
            raise ValueError(
                f"{name!r}: cannot compare a {target} reference to a string"
            )
        rhs = pst.StringLit(value)
    else:
        if target != "User":
            raise ValueError(f"{name!r}: principal requires a User reference")
        rhs = pst.Var("principal")
    return pst.When(pst.BinaryOp("eq", pst.GetAttr(pst.Var("resource"), name), rhs))


def compile_rules(projection: Projection, action: str, rules: tuple[Rule, ...]) -> str:
    """Build one scoped policy per rule; Cedar conjoins its when clauses."""
    if type(action) is not str:
        raise TypeError("expected a Cedar action ID string")
    references = {field.fact.name: field.fact.reference for field in projection.fields}
    action_scope = pst.ActionEq(pst.EntityUid(pst.EntityType("Action"), action))
    policies = {}
    for index, rule in enumerate(rules):
        policy_id = f"policy{index}"
        policies[policy_id] = pst.Template(
            id=policy_id,
            effect=rule.effect,
            principal=pst.ScopeIs(pst.EntityType("User")),
            action=action_scope,
            resource=pst.ScopeIs(pst.EntityType(projection.kind)),
            clauses=tuple(_condition(k, v, references) for k, v in rule.conditions),
            annotations={},
        )
    tree = pst.PolicySet(templates={}, static_policies=policies, template_links=())
    return str(cedarpy.PolicySet.from_pst(tree))
