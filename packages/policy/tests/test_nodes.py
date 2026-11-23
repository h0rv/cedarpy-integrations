from collections.abc import Callable
from typing import get_args

import cedarpy
from cedarpy import pst
from cedarpy_policy import nodes


# Typed callback tables check the signatures as well as the installed operator set.
BINARY: dict[pst.BinaryOpName, Callable[[pst.Expr, pst.Expr], pst.BinaryOp]] = {
    "eq": nodes.eq,
    "not_eq": nodes.not_eq,
    "less": nodes.less,
    "less_eq": nodes.less_eq,
    "greater": nodes.greater,
    "greater_eq": nodes.greater_eq,
    "and": nodes.and_,
    "or": nodes.or_,
    "add": nodes.add,
    "sub": nodes.sub,
    "mul": nodes.mul,
    "in": nodes.in_,
    "contains": nodes.contains,
    "contains_all": nodes.contains_all,
    "contains_any": nodes.contains_any,
    "get_tag": nodes.get_tag,
    "has_tag": nodes.has_tag,
    "is_in_range": nodes.is_in_range,
    "offset": nodes.offset,
    "duration_since": nodes.duration_since,
    "decimal_less_than": nodes.decimal_less_than,
    "decimal_less_eq": nodes.decimal_less_eq,
    "decimal_greater": nodes.decimal_greater,
    "decimal_greater_eq": nodes.decimal_greater_eq,
}
UNARY: dict[pst.UnaryOpName, Callable[[pst.Expr], pst.UnaryOp]] = {
    "not": nodes.not_,
    "neg": nodes.neg,
    "is_empty": nodes.is_empty,
    "datetime": nodes.datetime,
    "decimal": nodes.decimal,
    "duration": nodes.duration,
    "ip": nodes.ip,
    "is_ipv4": nodes.is_ipv4,
    "is_ipv6": nodes.is_ipv6,
    "is_loopback": nodes.is_loopback,
    "is_multicast": nodes.is_multicast,
    "to_date": nodes.to_date,
    "to_time": nodes.to_time,
    "to_milliseconds": nodes.to_milliseconds,
    "to_seconds": nodes.to_seconds,
    "to_minutes": nodes.to_minutes,
    "to_hours": nodes.to_hours,
    "to_days": nodes.to_days,
}


def test_operators__should_build_every_native_operation():
    assert BINARY.keys() == set(get_args(pst.BinaryOpName))
    assert UNARY.keys() == set(get_args(pst.UnaryOpName))
    left, right = nodes.principal, nodes.resource
    for binary, combine in BINARY.items():
        assert combine(left, right) == pst.BinaryOp(binary, left, right)
    for unary, transform in UNARY.items():
        assert transform(left) == pst.UnaryOp(unary, left)


def test_helpers__should_build_native_nodes():
    assert nodes.principal == pst.Var("principal")
    assert nodes.action == pst.Var("action")
    assert nodes.resource == pst.Var("resource")
    assert nodes.context == pst.Var("context")
    assert nodes.principal_slot == pst.Slot("principal")
    assert nodes.resource_slot == pst.Slot("resource")
    assert nodes.field(nodes.context, "n") == pst.GetAttr(pst.Var("context"), "n")
    assert nodes.action_is("read") == pst.ActionEq(
        pst.EntityUid(pst.EntityType("Action"), "read")
    )
    assert nodes.entity_is("User") == pst.ScopeIs(pst.EntityType("User"))
    assert nodes.entity_is_id("Doc", "a") == pst.ScopeEq(
        pst.EntityUid(pst.EntityType("Doc"), "a")
    )


def test_templates__should_render_and_enforce_native_conditions():
    principal = nodes.entity_is("User")
    action = nodes.action_is("read")
    resource = nodes.entity_is_id("Doc", "a")
    clauses = (
        pst.When(nodes.greater(nodes.field(nodes.context, "n"), pst.LongLit(1))),
    )
    denied = (pst.When(nodes.not_(nodes.field(nodes.context, "ready"))),)
    annotations = {"note": "example"}
    permit = nodes.permit(
        id="p",
        principal=principal,
        action=action,
        resource=resource,
        clauses=clauses,
        annotations=annotations,
    )
    forbid = nodes.forbid(
        id="f",
        principal=principal,
        action=action,
        resource=resource,
        clauses=denied,
        annotations=annotations,
    )
    assert permit == pst.Template(
        "p", "permit", principal, action, resource, clauses, annotations
    )
    assert forbid == pst.Template(
        "f", "forbid", principal, action, resource, denied, annotations
    )
    policies = cedarpy.PolicySet.from_pst(
        pst.PolicySet({}, {"p": permit, "f": forbid}, ())
    )
    rendered = str(policies)
    assert "context.n" in rendered and "context.ready" in rendered
    for n, ready, expected in [(2, True, True), (1, True, False), (2, False, False)]:
        request = {
            "principal": 'User::"alice"',
            "action": 'Action::"read"',
            "resource": 'Doc::"a"',
            "context": {"n": n, "ready": ready},
        }
        result = cedarpy.is_authorized(request, policies, [])
        assert not result.diagnostics.errors
        assert result.allowed is expected
