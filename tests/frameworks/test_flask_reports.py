from unittest.mock import Mock

from examples.frameworks import flask_reports


def test_export__should_recheck_the_authenticated_session(lookups, reports_db):
    app = flask_reports.create_app(**lookups)
    handler = Mock(wraps=flask_reports.export)
    app.view_functions["reports.export"] = handler
    client = app.test_client()

    # Only the server can set these WSGI keys. A lookalike header isn't a session.
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
    assert allowed.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert allowed.data == b"report,total\nsales,42\n"
    handler.assert_called_once()

    for user, session in [("alice", "other"), ("bob", "verified")]:
        wrong = {"REMOTE_USER": user, "cedar_web.session_id": session}
        assert client.get("/export", environ_overrides=wrong).status_code == 403
    _, db = reports_db
    db.execute("DELETE FROM sessions WHERE id = 'verified'")
    assert client.get("/export", environ_overrides=environ).status_code == 403
    handler.assert_called_once()
