"""FastAPI dependency factories. Install cedarpy-integrations[fastapi]."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import anyio.to_thread
import cedarpy_web
import fastapi
import fastapi.security

_Bearer = Annotated[
    fastapi.security.HTTPAuthorizationCredentials | None,
    fastapi.Security(fastapi.security.HTTPBearer(auto_error=False)),
]


def bearer_session[S: cedarpy_web.Session](
    verify: Callable[[str], Awaitable[S | None]],
) -> Callable[..., Awaitable[S]]:
    """Adapt an app's async bearer-token verifier into a FastAPI session dependency."""

    if not callable(verify):
        raise TypeError("verify must be callable")

    async def authenticated(credential: _Bearer) -> S:
        if credential is not None:
            session = await verify(credential.credentials)
            if session is not None:
                return session
        raise fastapi.HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    return authenticated


def require_authorization[S: cedarpy_web.Session](
    permission: cedarpy_web.Permission,
    *,
    identity: Callable[..., S | Awaitable[S]],
    load_facts: Callable[[S], Awaitable[cedarpy_web.Facts | None]],
) -> Callable[..., Awaitable[S]]:
    """Authorize the session returned by an existing FastAPI authentication dependency."""

    if not isinstance(permission, cedarpy_web.Permission):
        raise TypeError("permission must be a Permission")
    if not callable(identity):
        raise TypeError("identity must be callable")
    if not callable(load_facts):
        raise TypeError("load_facts must be callable")

    async def authorized(session: Annotated[S, fastapi.Depends(identity)]) -> S:
        if not isinstance(session, cedarpy_web.Session):
            raise fastapi.HTTPException(403, "Forbidden")
        if not await anyio.to_thread.run_sync(
            permission.definitely_denies, session.user_id
        ):
            facts = await load_facts(session)
            if facts is not None and await anyio.to_thread.run_sync(
                permission.allows, session.user_id, facts
            ):
                return session
        raise fastapi.HTTPException(403, "Forbidden")

    return authorized
