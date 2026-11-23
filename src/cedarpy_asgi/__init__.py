from collections.abc import Awaitable, Callable

from anyio.to_thread import run_sync
from cedarpy_web import Facts, Permission, Session
from cedarpy_web._mount import validate_mount
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


def require_authorization(
    app: ASGIApp,
    permission: Permission,
    *,
    identity: Callable[[Scope], Awaitable[Session | None]],
    load_facts: Callable[[Session], Awaitable[Facts | None]],
    challenge: str,
) -> ASGIApp:
    """Protect the HTTP app at this mount. Identity must come from authentication."""

    validate_mount(
        permission, challenge, app=app, identity=identity, load_facts=load_facts
    )

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        match scope["type"]:
            case "lifespan":
                await app(scope, receive, send)
                return
            case "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            case "http":
                pass
            case other:
                raise ValueError(f"Unsupported ASGI scope: {other!r}")

        session = await identity(scope)
        if session is None:
            await Response(status_code=401, headers={"WWW-Authenticate": challenge})(
                scope, receive, send
            )
            return
        if not await run_sync(permission.definitely_denies, session.user_id):
            facts = await load_facts(session)
            if facts is not None and await run_sync(
                permission.allows, session.user_id, facts
            ):
                await app(scope, receive, send)
                return
        await Response(status_code=403)(scope, receive, send)

    return guarded
