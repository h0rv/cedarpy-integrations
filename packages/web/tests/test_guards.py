"""Exercise the same policies and data-access boundary through both mounts."""

from unittest.mock import Mock, call

import pytest

from cedarpy_web import Facts, PermissionEvaluationError, Session
from packages.web.examples.policy import POLICIES, report_export

pytestmark = pytest.mark.anyio


def facts(export=True, stepped_up=True):
    return Facts(
        principal_attrs={"can_export": export}, context={"stepped_up": stepped_up}
    )


async def test_session_pair_and_revocation(mount):
    verified = Session('editor"A', "verified")
    other = Session(verified.user_id, "ordinary")
    table = {verified: facts(), other: facts(stepped_up=False)}
    lookup, read_data = Mock(side_effect=table.get), Mock()
    invoke = mount(report_export(), lookup, read_data)

    for user, sid in [
        (None, verified.session_id),
        (verified.user_id, None),
        (verified.user_id, ""),
    ]:
        response = await invoke(user, sid)
        assert response.status_code == 401 and response.headers["www-authenticate"]
    lookup.assert_not_called()
    read_data.assert_not_called()

    response = await invoke(verified.user_id, verified.session_id)
    assert (response.status_code, response.content, response.headers["x-job"]) == (
        202,
        b"queued",
        "export",
    )
    assert (await invoke(other.user_id, other.session_id)).status_code == 403
    assert (await invoke("different", verified.session_id)).status_code == 403
    table[verified] = facts(stepped_up=False)
    assert (await invoke(verified.user_id, verified.session_id)).status_code == 403
    assert lookup.call_args_list == [
        call(verified),
        call(other),
        call(Session("different", verified.session_id)),
        call(verified),
    ]
    read_data.assert_called_once_with()


async def test_definitive_denial_skips_both_reads(mount, build_permission):
    # A session lookup cannot overcome a forbid for this known principal.
    permission = build_permission(
        policies=POLICIES + 'forbid(principal == User::"blocked", action, resource);'
    )
    lookup, read_data = Mock(), Mock()
    assert (
        await mount(permission, lookup, read_data)("blocked", "session")
    ).status_code == 403
    lookup.assert_not_called()
    read_data.assert_not_called()


async def test_partial_allow_cannot_bypass_failing_source(mount, build_permission):
    permission = build_permission(policies="permit(principal, action, resource);")
    lookup, read_data = Mock(side_effect=OSError("source unavailable")), Mock()
    with pytest.raises(OSError):
        await mount(permission, lookup, read_data)("editor", "session")
    lookup.assert_called_once_with(Session("editor", "session"))
    read_data.assert_not_called()


@pytest.mark.parametrize(
    "attrs, context",
    [
        ({}, {"stepped_up": True}),
        ({"can_export": True}, {}),
        ({"can_export": True}, {"stepped_up": "true"}),
        ({"can_export": True}, {"stepped_up": 1}),
        ({"can_export": True}, None),
    ],
)
async def test_malformed_facts_never_dispatch(mount, build_permission, attrs, context):
    # Without schema checks an absent field would silence this forbid without a diagnostic.
    permission = build_permission(
        policies="""
        permit(principal, action, resource);
        forbid(principal, action, resource) when { context has stepped_up && !context.stepped_up };
    """
    )
    lookup = Mock(
        side_effect=lambda session: Facts(principal_attrs=attrs, context=context)
    )
    read_data = Mock()
    with pytest.raises(PermissionEvaluationError):
        await mount(permission, lookup, read_data)("editor", "session")
    lookup.assert_called_once_with(Session("editor", "session"))
    read_data.assert_not_called()
