"""First-class constructors for native Cedar PST nodes, without scope checks."""

from collections.abc import Callable, Mapping

from cedarpy import pst


def _binary(op: pst.BinaryOpName) -> Callable[[pst.Expr, pst.Expr], pst.BinaryOp]:
    def build(left: pst.Expr, right: pst.Expr) -> pst.BinaryOp:
        return pst.BinaryOp(op, left, right)

    return build


def _unary(op: pst.UnaryOpName) -> Callable[[pst.Expr], pst.UnaryOp]:
    def build(arg: pst.Expr) -> pst.UnaryOp:
        return pst.UnaryOp(op, arg)

    return build


eq = _binary("eq")
not_eq = _binary("not_eq")
less = _binary("less")
less_eq = _binary("less_eq")
greater = _binary("greater")
greater_eq = _binary("greater_eq")
and_ = _binary("and")
or_ = _binary("or")
add = _binary("add")
sub = _binary("sub")
mul = _binary("mul")
in_ = _binary("in")
contains = _binary("contains")
contains_all = _binary("contains_all")
contains_any = _binary("contains_any")
get_tag = _binary("get_tag")
has_tag = _binary("has_tag")
is_in_range = _binary("is_in_range")
offset = _binary("offset")
duration_since = _binary("duration_since")
decimal_less_than = _binary("decimal_less_than")
decimal_less_eq = _binary("decimal_less_eq")
decimal_greater = _binary("decimal_greater")
decimal_greater_eq = _binary("decimal_greater_eq")

not_ = _unary("not")
neg = _unary("neg")
is_empty = _unary("is_empty")
datetime = _unary("datetime")
decimal = _unary("decimal")
duration = _unary("duration")
ip = _unary("ip")
is_ipv4 = _unary("is_ipv4")
is_ipv6 = _unary("is_ipv6")
is_loopback = _unary("is_loopback")
is_multicast = _unary("is_multicast")
to_date = _unary("to_date")
to_time = _unary("to_time")
to_milliseconds = _unary("to_milliseconds")
to_seconds = _unary("to_seconds")
to_minutes = _unary("to_minutes")
to_hours = _unary("to_hours")
to_days = _unary("to_days")

principal = pst.Var("principal")
action = pst.Var("action")
resource = pst.Var("resource")
context = pst.Var("context")

principal_slot = pst.Slot("principal")
resource_slot = pst.Slot("resource")


def field(expr: pst.Expr, name: str) -> pst.GetAttr:
    return pst.GetAttr(expr, name)


def action_is(id: str) -> pst.ActionEq:
    return pst.ActionEq(pst.EntityUid(pst.EntityType("Action"), id))


def entity_is(type: str) -> pst.ScopeIs:
    return pst.ScopeIs(pst.EntityType(type))


def entity_is_id(type: str, id: str) -> pst.ScopeEq:
    return pst.ScopeEq(pst.EntityUid(pst.EntityType(type), id))


def permit(
    *,
    id: str,
    principal: pst.PrincipalOrResourceConstraint,
    action: pst.ActionConstraint,
    resource: pst.PrincipalOrResourceConstraint,
    clauses: tuple[pst.Clause, ...],
    annotations: Mapping[str, str],
) -> pst.Template:
    return pst.Template(id, "permit", principal, action, resource, clauses, annotations)


def forbid(
    *,
    id: str,
    principal: pst.PrincipalOrResourceConstraint,
    action: pst.ActionConstraint,
    resource: pst.PrincipalOrResourceConstraint,
    clauses: tuple[pst.Clause, ...],
    annotations: Mapping[str, str],
) -> pst.Template:
    return pst.Template(id, "forbid", principal, action, resource, clauses, annotations)
