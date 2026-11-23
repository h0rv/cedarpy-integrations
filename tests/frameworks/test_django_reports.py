from unittest.mock import Mock

from werkzeug.test import Client

from examples.frameworks import django_reports


def test_export__should_recheck_the_authenticated_session(
    monkeypatch, lookups, reports_db
):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", django_reports.__name__)
    client = Client(django_reports.create_app(**lookups))
    (route,) = django_reports.urlpatterns
    handler = Mock(wraps=route.callback)
    monkeypatch.setattr(route, "callback", handler)

    # Drive the protected WSGI entry point, not Django's internal test handler.
    environ = {"REMOTE_USER": "alice"}
    missing = client.get(
        "/export",
        environ_overrides=environ,
        headers={"Cedar-Web-Session-Id": "verified"},
    )
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    handler.assert_not_called()

    environ["cedar_web.session_id"] = "verified"
    allowed = client.get("/export", environ_overrides=environ)
    assert allowed.status_code == 200
    assert allowed.headers["Content-Type"] == "text/csv"
    assert allowed.data == b"report,total\nsales,42\n"
    handler.assert_called_once()

    _, db = reports_db
    db.execute("UPDATE sessions SET expires_at = unixepoch()-1 WHERE id = 'verified'")
    assert client.get("/export", environ_overrides=environ).status_code == 403
    db.execute(
        "UPDATE sessions SET expires_at = 'not a timestamp' WHERE id = 'verified'"
    )
    assert client.get("/export", environ_overrides=environ).status_code == 403
    db.execute("DROP TABLE sessions")
    assert client.get("/export", environ_overrides=environ).status_code == 403
    handler.assert_called_once()
