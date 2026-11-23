"""Add the guarded reports endpoint to an existing FastAPI app."""

from cedarpy_asgi.fastapi import bearer_session, require_authorization
from fastapi import Depends, FastAPI, Response

from .report_access import export_permission
from .report_identity import ReportIdentity


def export_reports() -> Response:
    return Response("report,total\nsales,42\n", media_type="text/csv")


def install_exports(app: FastAPI, identity: ReportIdentity) -> None:
    require_export = require_authorization(
        export_permission,
        identity=bearer_session(identity.verify_token),
        load_facts=identity.export_facts,
    )
    app.add_api_route(
        "/exports",
        export_reports,
        methods=["POST"],
        dependencies=[Depends(require_export)],
    )
