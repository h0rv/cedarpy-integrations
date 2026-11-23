from unittest.mock import create_autospec

import pytest
from cedarpy_web import Session
from fastapi import FastAPI
from fastapi.testclient import TestClient

from examples.frameworks.fastapi_reports import install_exports
from examples.frameworks.report_identity import AuthServiceClient, ReportIdentity
from examples.frameworks.report_access import ExportEntitlements


@pytest.fixture
def auth():
    client = create_autospec(AuthServiceClient, instance=True, spec_set=True)
    client.verify_token.side_effect = {
        "opaque": Session("alice", "verified"),
        "phone-token": Session("alice", "phone"),
    }.get
    client.step_up_status.return_value = {
        "user_id": "alice",
        "session_id": "verified",
        "stepped_up": True,
    }
    return client


@pytest.fixture
def client(reports_db, auth):
    path, _ = reports_db
    app = FastAPI()
    install_exports(app, ReportIdentity(auth, ExportEntitlements(path).can_export))
    with TestClient(app, headers={"Authorization": "Bearer opaque"}) as client:
        yield client


def test_export_then_revoke_step_up(client, auth):
    response = client.post("/exports")
    assert response.status_code == 200
    assert response.text == "report,total\nsales,42\n"
    auth.step_up_status.assert_awaited_once_with(user_id="alice", session_id="verified")
    auth.step_up_status.return_value["stepped_up"] = False
    denied = client.post("/exports")
    assert denied.status_code == 403
    assert "sales" not in denied.text


def test_two_verified_sessions_do_not_share_step_up(client, auth):
    assert client.post("/exports").status_code == 200
    response = client.post("/exports", headers={"Authorization": "Bearer phone-token"})
    auth.step_up_status.assert_awaited_with(user_id="alice", session_id="phone")
    assert response.status_code == 403


def test_revoked_token(client, auth):
    assert client.post("/exports").status_code == 200
    auth.verify_token.side_effect = None
    auth.verify_token.return_value = None
    assert client.post("/exports").status_code == 401
    assert auth.step_up_status.await_count == 1


@pytest.mark.parametrize("header", [None, "Basic opaque", "Bearer unknown"])
def test_missing_or_invalid_token(client, header):
    del client.headers["Authorization"]
    response = client.post(
        "/exports", headers={"Authorization": header} if header else {}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("grant", [0, "true", 2, None])
def test_step_up_is_not_an_export_grant(client, reports_db, grant):
    _, db = reports_db
    assert client.post("/exports").status_code == 200
    db.execute("UPDATE users SET can_export = ? WHERE id = 'alice'", (grant,))
    assert client.post("/exports").status_code == 403


@pytest.mark.parametrize(
    "status",
    [
        {"user_id": "alice", "session_id": "other", "stepped_up": True},
        {"user_id": "bob", "session_id": "verified", "stepped_up": True},
        {"user_id": "alice", "session_id": "verified", "stepped_up": 1},
        {"user_id": "alice", "session_id": "verified", "stepped_up": "true"},
        {"stepped_up": True},
        None,
    ],
)
def test_wrong_or_malformed_step_up_reply(client, auth, status):
    auth.step_up_status.return_value = status
    assert client.post("/exports").status_code == 403


def test_auth_service_unavailable(client, auth):
    assert client.post("/exports").status_code == 200
    auth.step_up_status.side_effect = TimeoutError()
    assert client.post("/exports").status_code == 403
    auth.verify_token.side_effect = ConnectionError()
    assert client.post("/exports").status_code == 401


def test_malformed_verified_identity(client, auth):
    auth.verify_token.side_effect = None
    auth.verify_token.return_value = {"user_id": "alice"}
    assert client.post("/exports").status_code == 401
    auth.step_up_status.assert_not_awaited()


def test_entitlements_unavailable(client, reports_db):
    _, db = reports_db
    db.execute("DROP TABLE users")
    assert client.post("/exports").status_code == 403


def test_openapi_advertises_bearer(client):
    spec = client.get("/openapi.json").json()
    assert {"HTTPBearer": []} in spec["paths"]["/exports"]["post"]["security"]
