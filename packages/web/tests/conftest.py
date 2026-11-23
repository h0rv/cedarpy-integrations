import asyncio

import httpx2
import pytest
from starlette.authentication import SimpleUser, UnauthenticatedUser
from starlette.responses import Response
from starlette.routing import Router

from cedarpy_web import Permission
from packages.web.examples.asgi_reports import export_mount
from packages.web.examples.policy import POLICIES, SCHEMA
from packages.web.examples.wsgi_reports import protect_exports


@pytest.fixture
def build_permission():
    def build(*, policies=POLICIES, schema=SCHEMA, action="export", service="reports"):
        return Permission(
            policies=policies, schema=schema, action=action, service=service
        )

    return build


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["wsgi", "asgi"])
def mount(request):
    # Spoofed inputs deliberately disagree with the server authentication state.
    url = "https://example.org/exports/?action=read&stepped_up=true"
    headers = {
        "Remote-User": "editor",
        "Cedar-Web-Session-Id": "verified",
        "Stepped-Up": "true",
    }

    def build(permission, lookup, read_data):
        if request.param == "wsgi":

            def app(environ, start_response):
                read_data()
                start_response("202 Accepted", [("X-Job", "export")])
                return [b"queued"]

            protected = protect_exports(app, permission, lookup)

            async def invoke(user, sid):
                def server(environ, start_response):
                    if user is not None:
                        environ["REMOTE_USER"] = user
                    if sid is not None:
                        environ["cedar_web.session_id"] = sid
                    return protected(environ, start_response)

                with httpx2.Client(
                    transport=httpx2.WSGITransport(app=server)
                ) as client:
                    return client.post(url, headers=headers)
        else:

            async def asgi_app(scope, receive, send):
                read_data()
                await Response("queued", status_code=202, headers={"X-Job": "export"})(
                    scope, receive, send
                )

            async def load(session):
                await asyncio.sleep(0)
                return lookup(session)

            router = Router(routes=[export_mount(asgi_app, permission, load)])

            async def invoke(user, sid):
                async def server(scope, receive, send):
                    scope["user"] = (
                        UnauthenticatedUser() if user is None else SimpleUser(user)
                    )
                    if sid is not None:
                        scope["cedar_web.session_id"] = sid
                    await router(scope, receive, send)

                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=server)
                ) as client:
                    return await client.post(url, headers=headers)

        return invoke

    return build
