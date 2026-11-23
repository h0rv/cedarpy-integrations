import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from cedarpy_asgi import require_authorization
from cedarpy_web import Facts, Permission, Session
from packages.web.examples.policy import report_export

pytestmark = pytest.mark.anyio


async def test_interleaved_sessions_only_run_cedar_in_worker(monkeypatch):
    waiting = asyncio.Barrier(2)
    loop_thread = threading.get_ident()

    def off_thread(fn):
        def check(*args):
            assert threading.get_ident() != loop_thread
            return fn(*args)

        return check

    monkeypatch.setattr(Permission, "allows", off_thread(Permission.allows))
    monkeypatch.setattr(
        Permission, "definitely_denies", off_thread(Permission.definitely_denies)
    )

    async def identity(scope):
        return Session("same user", scope["sid"])

    async def load(session):
        assert threading.get_ident() == loop_thread
        await waiting.wait()
        return Facts(
            principal_attrs={"can_export": True},
            context={"stepped_up": session.session_id == "verified"},
        )

    app = AsyncMock()
    guarded = require_authorization(
        app, report_export(), identity=identity, load_facts=load, challenge="Bearer"
    )

    async def invoke(sid):
        await guarded({"type": "http", "sid": sid}, AsyncMock(), AsyncMock())

    async with asyncio.timeout(3), asyncio.TaskGroup() as group:
        for sid in ["ordinary", "verified"]:
            group.create_task(invoke(sid))
    app.assert_awaited_once()
    assert app.await_args_list[0].args[0]["sid"] == "verified"


async def test_identity_failure_does_not_load_or_dispatch():
    app, load = AsyncMock(), AsyncMock()
    guarded = require_authorization(
        app,
        report_export(),
        identity=AsyncMock(side_effect=OSError),
        load_facts=load,
        challenge="Bearer",
    )
    with pytest.raises(OSError):
        await guarded({"type": "http"}, AsyncMock(), AsyncMock())
    load.assert_not_awaited()
    app.assert_not_awaited()


@pytest.mark.parametrize("kind", ["websocket", "lifespan", "other"])
async def test_non_http_scopes_never_use_http_permission(kind):
    identity, load, app, receive, send = (AsyncMock() for _ in range(5))
    guarded = require_authorization(
        app, report_export(), identity=identity, load_facts=load, challenge="Bearer"
    )
    scope = {"type": kind}
    if kind == "other":
        with pytest.raises(ValueError, match="Unsupported ASGI scope"):
            await guarded(scope, receive, send)
    else:
        await guarded(scope, receive, send)
    if kind == "websocket":
        send.assert_awaited_once_with({"type": "websocket.close", "code": 1008})
    else:
        send.assert_not_awaited()
    if kind == "lifespan":
        app.assert_awaited_once_with(scope, receive, send)
    else:
        app.assert_not_awaited()
    identity.assert_not_awaited()
    load.assert_not_awaited()
