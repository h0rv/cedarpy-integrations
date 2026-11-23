from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from cedarpy_web import Facts, Permission, Session
from cedarpy_web._mount import validate_mount

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment


def require_authorization(
    app: WSGIApplication,
    permission: Permission,
    *,
    load_facts: Callable[[Session], Facts | None],
    challenge: str,
) -> WSGIApplication:
    """Protect a WSGI app behind a server that authenticates REMOTE_USER."""

    validate_mount(permission, challenge, app=app, load_facts=load_facts)

    def guarded(
        environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        user_id = environ.get("REMOTE_USER")
        session_id = environ.get("cedar_web.session_id")
        if not (
            isinstance(user_id, str)
            and user_id
            and isinstance(session_id, str)
            and session_id
        ):
            start_response(
                "401 Unauthorized",
                [("WWW-Authenticate", challenge), ("Content-Length", "0")],
            )
            return []
        if not permission.definitely_denies(user_id):
            facts = load_facts(Session(user_id, session_id))
            if facts is not None and permission.allows(user_id, facts):
                return app(environ, start_response)
        start_response("403 Forbidden", [("Content-Length", "0")])
        return []

    return guarded
