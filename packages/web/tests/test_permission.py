from collections import UserDict
from itertools import product

import pytest

from cedarpy_web import Facts, PermissionEvaluationError
from packages.web.examples.policy import POLICIES, SCHEMA, report_export


@pytest.mark.parametrize("can_export, stepped_up", [(False, True), (True, False)])
def test_later_source_mutations_cannot_turn_denial_into_allow(can_export, stepped_up):
    attrs = UserDict({"can_export": can_export})
    context = {"stepped_up": stepped_up}
    facts = Facts(principal_attrs=attrs, context=context)
    attrs["can_export"] = context["stepped_up"] = True

    assert not report_export().allows("caller", facts)


@pytest.mark.parametrize("invalid", [{"nested": []}, {1: "value"}, [("flag", True)]])
def test_facts_reject_invalid_records_at_construction(invalid):
    with pytest.raises(PermissionEvaluationError):
        Facts(principal_attrs=invalid, context={})
    with pytest.raises(PermissionEvaluationError):
        Facts(principal_attrs={}, context=invalid)


def test_diagnostic_overrides_allow(build_permission):
    # The forbid type checks but overflows for this particular input.
    permission = build_permission(
        schema=SCHEMA.replace("stepped_up: Bool", "n: Long"),
        policies="""permit(principal, action, resource);
            forbid(principal, action, resource) when { context.n + 1 > 0 };""",
    )
    with pytest.raises(PermissionEvaluationError, match="overflow"):
        permission.allows(
            "caller",
            Facts(principal_attrs={"can_export": True}, context={"n": 2**63 - 1}),
        )


def test_preview_never_skips_a_possible_allow(build_permission):
    permission = build_permission(
        policies=POLICIES + 'forbid(principal == User::"blocked", action, resource);'
    )
    for user, can_export, stepped_up in product(
        ["blocked", "editor"], [False, True], [False, True]
    ):
        facts = Facts(
            principal_attrs={"can_export": can_export},
            context={"stepped_up": stepped_up},
        )
        assert permission.definitely_denies(user) == (user == "blocked")
        assert permission.allows(user, facts) == (
            user != "blocked" and can_export and stepped_up
        )


def test_partial_error_is_not_a_definitive_deny():
    # Classic PE cannot parse the JSON escape for NUL in a text UID. The
    # complete evaluator uses structured IDs and accepts the exact identity.
    permission = report_export()
    assert not permission.definitely_denies("bad\x00uid")
    assert permission.allows(
        "bad\x00uid",
        Facts(principal_attrs={"can_export": True}, context={"stepped_up": True}),
    )
