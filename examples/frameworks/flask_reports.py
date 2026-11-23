"""Serve this export-only app behind trusted WSGI authentication."""

from collections.abc import Callable

import cedarpy_web
import cedarpy_wsgi
import flask

from .report_access import export_facts, export_permission

reports = flask.Blueprint("reports", __name__)


@reports.get("/export")
def export() -> flask.Response:
    return flask.Response("report,total\nsales,42\n", mimetype="text/csv")


def create_app(
    *,
    can_export: Callable[[str], bool],
    is_stepped_up: Callable[[cedarpy_web.Session], bool],
    challenge: str = "Bearer",
) -> flask.Flask:
    app = flask.Flask(__name__, static_folder=None)
    app.register_blueprint(reports)
    app.wsgi_app = cedarpy_wsgi.require_authorization(
        app.wsgi_app,
        export_permission,
        load_facts=export_facts(can_export, is_stepped_up),
        challenge=challenge,
    )
    return app
