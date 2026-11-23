from dataclasses import dataclass
from enum import StrEnum
from operator import and_, or_

import cedarpy
import pytest
from cedarpy_policy import (
    Condition,
    Scope,
    bool_field,
    entity_field,
    entity_principal,
    enum_field,
    policy,
)


class State(StrEnum):
    SEALED = "sealed"


class OtherState(StrEnum):
    SEALED = "sealed"


@dataclass(frozen=True)
class Action:
    scope: Scope


read = Action(Scope("read", "User", "Document"))
state = enum_field(read.scope, "state", State)
sealed = state == State.SEALED


@pytest.mark.parametrize("value", ["sealed", OtherState.SEALED])
def test_enum__should_reject_wrong_type_even_when_values_match(value):
    with pytest.raises(TypeError, match="State"):
        _ = state == value


def test_policy__should_reject_host_booleans():
    with pytest.raises(TypeError, match="truth value"):
        bool(sealed)
    with pytest.raises(TypeError, match="Condition"):
        policy(read, permit_when=True)  # ty: ignore[invalid-argument-type]


def test_condition__should_reject_host_comparisons():
    with pytest.raises(TypeError, match="does not support equality"):
        _ = sealed == ~sealed
    with pytest.raises(TypeError, match="inequality"):
        _ = state != State.SEALED
    with pytest.raises(TypeError, match="same Cedar type"):
        _ = entity_principal(read.scope) == "alice"


def test_policy__should_reject_condition_from_another_operation():
    write = Scope("write", "User", "Document")
    with pytest.raises(ValueError, match="scope"):
        policy(read, permit_when=bool_field(write, "context", "approved"))


@pytest.mark.parametrize("combine", [and_, or_])
def test_condition__should_reject_combining_scopes(combine):
    write = Scope("write", "User", "Document")
    other: Condition = bool_field(write, "context", "approved")
    with pytest.raises(ValueError, match="scope"):
        combine(sealed, other)


def test_entity__should_reject_comparison_across_entity_types():
    with pytest.raises(TypeError, match="same Cedar type"):
        _ = entity_field(read.scope, "group", "Group") == entity_principal(read.scope)


def test_policy__should_match_cedar_when_ids_and_enum_values_need_escaping():
    class Label(StrEnum):
        PUBLIC = 'share "publicly"\\now\n'

    action = Action(Scope('read "draft"', "User", "Document", 'notes\\"draft"'))
    condition = enum_field(action.scope, "label", Label) == Label.PUBLIC
    compiled = policy(action, permit_when=condition)
    reference = cedarpy.PolicySet.from_str(
        r"""permit(principal is User, action == Action::"read \"draft\"",
                   resource == Document::"notes\\\"draft\"")
            when { resource.label == "share \"publicly\"\\now\n" };"""
    )
    expected = {
        "principal": {"type": "User", "id": "alice"},
        "action": {"type": "Action", "id": 'read "draft"'},
        "resource": {"type": "Document", "id": 'notes\\"draft"'},
    }
    for key, kind in (
        (None, ""),
        ("principal", "Group"),
        ("action", "Other"),
        ("resource", "Photo"),
    ):
        request = expected.copy()
        if key is not None:
            request[key] = {**request[key], "type": kind}
        entities = [
            {
                "uid": request["resource"],
                "attrs": {"label": Label.PUBLIC.value},
                "parents": [],
            }
        ]
        for rules in (compiled, reference):
            result = cedarpy.is_authorized({**request, "context": {}}, rules, entities)
            assert not result.diagnostics.errors
            assert result.allowed is (key is None)
