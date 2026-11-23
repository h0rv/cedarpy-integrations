import fastapi
import fastapi.testclient
import pytest

from cedarpy_asgi.fastapi import bearer_session, require_authorization
from cedarpy_web import Permission
from packages.web.examples.policy import POLICIES, SCHEMA


def permission():
    return Permission(
        action="export", service="reports", schema=SCHEMA, policies=POLICIES
    )


def test_factories__invalid_callbacks__should_fail_at_setup():
    with pytest.raises(TypeError, match="verify"):
        bearer_session(None)
    with pytest.raises(TypeError, match="permission"):
        require_authorization(None, identity=lambda: None, load_facts=lambda _: None)
    with pytest.raises(TypeError, match="identity"):
        require_authorization(permission(), identity=None, load_facts=lambda _: None)
    with pytest.raises(TypeError, match="load_facts"):
        require_authorization(permission(), identity=lambda: None, load_facts=None)


def test_authorization__missing_session__should_deny_without_loading_facts():
    app = fastapi.FastAPI()

    def identity():
        return None

    async def load_facts(session):
        raise AssertionError("must not load facts")

    dependency = require_authorization(
        permission(), identity=identity, load_facts=load_facts
    )

    @app.get("/")
    def endpoint(session=fastapi.Depends(dependency)):
        return "allowed"

    with fastapi.testclient.TestClient(app) as client:
        assert client.get("/").status_code == 403
