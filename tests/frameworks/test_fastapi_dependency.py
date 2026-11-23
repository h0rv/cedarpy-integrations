from dataclasses import dataclass

import cedarpy_asgi.fastapi
import cedarpy_web
import fastapi
import fastapi.testclient

from examples.frameworks.report_access import export_permission


@dataclass(frozen=True)
class AppSession(cedarpy_web.Session):
    business: str


def test_existing_identity_dependency_preserves_app_session():
    app = fastapi.FastAPI()
    verified = AppSession("alice", "laptop", "Acme")
    observed = []

    # Stand-in for an application's existing authentication dependency.
    def identity() -> AppSession:
        return verified

    async def load(session: AppSession) -> cedarpy_web.Facts:
        observed.append(session)
        return cedarpy_web.Facts(
            principal_attrs={"can_export": session.business == "Acme"},
            context={"stepped_up": True},
        )

    require_export = cedarpy_asgi.fastapi.require_authorization(
        export_permission, identity=identity, load_facts=load
    )

    @app.get("/")
    def who(session: AppSession = fastapi.Depends(require_export)):
        assert session is verified
        return session.business

    with fastapi.testclient.TestClient(app) as client:
        assert client.get("/").raise_for_status().json() == "Acme"
    assert observed == [verified]
