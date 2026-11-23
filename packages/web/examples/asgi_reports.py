from starlette.requests import HTTPConnection
from starlette.routing import Mount
from starlette.types import Scope

import cedarpy_asgi
import cedarpy_web


async def identity(scope: Scope) -> cedarpy_web.Session | None:
    # Both values come from outer authentication middleware.
    user = HTTPConnection(scope).user
    session_id = scope.get("cedar_web.session_id")
    if user.is_authenticated and isinstance(session_id, str) and session_id:
        return cedarpy_web.Session(user.identity, session_id)
    return None


def export_mount(export_app, permission: cedarpy_web.Permission, lookup_export_facts):
    protected = cedarpy_asgi.require_authorization(
        export_app,
        permission,
        identity=identity,
        load_facts=lookup_export_facts,
        challenge="Bearer",
    )
    return Mount("/exports", app=protected)
