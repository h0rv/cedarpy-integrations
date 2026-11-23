import json
from unittest.mock import AsyncMock, Mock

import pytest
from cedarpy import PolicySet, Schema

import cedarpy_asgi as asgi
import cedarpy_wsgi as wsgi
from cedarpy_web import Facts
from packages.web.examples.policy import SCHEMA, report_export


@pytest.mark.parametrize(
    "config, message",
    [
        ({"schema": "entity User {"}, None),
        ({"policies": "permit("}, "policies"),
        (
            {
                "policies": "permit(principal, action, resource) when { principal.typo };"
            },
            "Invalid policies",
        ),
        ({"action": "unknown"}, "Invalid mount"),
        ({"action": " "}, "action"),
        ({"service": ""}, "service"),
        ({"service": None}, "service"),
        (
            {"schema": SCHEMA.replace("principal: [User]", "principal: [Service]")},
            "mount",
        ),
        (
            {"schema": SCHEMA.replace("resource: [Service]", "resource: [User]")},
            "mount",
        ),
        (
            {
                "schema": SCHEMA.replace(
                    "entity Service;", "entity Service { owner: User };"
                )
            },
            "Invalid mount",
        ),
        (
            {
                "schema": SCHEMA.replace(
                    "entity Service;", 'entity Service enum ["other"];'
                )
            },
            "Invalid mount",
        ),
        ({"service": "bad\x00uid"}, "Invalid mount"),
    ],
)
def test_invalid_permission_fails_at_construction(build_permission, config, message):
    # An unconstrained policy cannot tell us whether the mount itself is valid.
    with pytest.raises(ValueError, match=message):
        build_permission(
            **({"policies": "permit(principal, action, resource);"} | config)
        )


@pytest.mark.parametrize("as_handle", [False, True])
def test_template_policy__should_reject_text_and_handles(build_permission, as_handle):
    template = 'permit(principal == ?principal, action, resource);'
    policies = PolicySet.from_str(template) if as_handle else template
    with pytest.raises(ValueError, match="static policy set"):
        build_permission(policies=policies)


def test_configured_ids_are_not_normalized_or_truncated(build_permission):
    action, service = 'export "週"', "reports\\\\archive "
    schema = SCHEMA.replace('"export"', json.dumps(action, ensure_ascii=False))
    policies = f"permit(principal, action == Action::{json.dumps(action, ensure_ascii=False)}, resource == Service::{json.dumps(service)});"
    permission = build_permission(
        action=action, service=service, schema=schema, policies=policies
    )
    assert permission.allows(
        "caller",
        Facts(principal_attrs={"can_export": True}, context={"stepped_up": True}),
    )


def test_probe_does_not_evaluate_user_policies(build_permission):
    # This well-typed policy overflows only for the placeholder. It must not
    # prevent mounting. The required context stays unknown during the probe.
    permission = build_permission(
        policies="""
        permit(principal == User::"probe", action, resource)
        when { 9223372036854775807 + 1 > 0 };
    """
    )
    assert not permission.definitely_denies("probe")


def test_scope_check_never_grants_access(build_permission):
    permission = build_permission(policies="")
    assert isinstance(permission.policies, PolicySet)
    assert isinstance(permission.schema, Schema)
    assert not permission.allows(
        "caller",
        Facts(principal_attrs={"can_export": True}, context={"stepped_up": True}),
    )


@pytest.fixture(params=[wsgi, asgi])
def guard_config(request):
    adapter = request.param
    callback = AsyncMock if adapter is asgi else Mock
    config = {
        "app": callback(),
        "permission": report_export(),
        "load_facts": callback(),
        "challenge": "Bearer",
    }
    if adapter is asgi:
        config["identity"] = callback()
    return adapter.require_authorization, config


@pytest.mark.parametrize(
    "bad",
    [
        None,
        b"Basic",
        "",
        " ",
        " Bearer",
        "Basic\t",
        "Basic\r\nX: y",
        "a\nb",
        "a\x00b",
        "a\x1fb",
        "a\x7fb",
        'Basic realm="雪"',
    ],
)
def test_invalid_challenge_fails_at_mount(guard_config, bad):
    guard, config = guard_config
    with pytest.raises(ValueError, match="challenge"):
        guard(**(config | {"challenge": bad}))


@pytest.mark.parametrize("key", ["app", "load_facts", "permission"])
def test_invalid_binding_fails_at_mount(guard_config, key):
    guard, config = guard_config
    with pytest.raises(TypeError, match=key):
        guard(**(config | {key: None}))


def test_asgi_requires_callable_identity():
    with pytest.raises(TypeError, match="identity"):
        asgi.require_authorization(
            AsyncMock(),
            report_export(),
            identity=None,
            load_facts=AsyncMock(),
            challenge="Bearer",
        )
