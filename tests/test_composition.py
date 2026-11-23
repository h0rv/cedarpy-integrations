"""A protected HTTP operation can use a checked reader; neither implies the other."""

import asyncio
import os

import httpx2
from cedarpy_sqlalchemy import AsyncStore, CedarAuthorizationMixin, attr, ref
from cedarpy_asgi import require_authorization
from cedarpy_web import Facts, Session
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

# Reuse the public example policy rather than a second hand-written permission.
from packages.web.examples.policy import report_export


class Base(DeclarativeBase):
    pass


class Invoice(Base, CedarAuthorizationMixin):
    __tablename__ = "cedar_composition_invoices"
    cedar_type = "Invoice"

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
    state: Mapped[str] = mapped_column(info=attr("state"))


SCHEMA = "entity User; entity Invoice = {owner: User, state: String}; action export appliesTo {principal: [User], resource: [Invoice]};"
POLICIES = """permit(principal, action == Action::"export", resource is Invoice) when {resource.owner == principal};
forbid(principal, action, resource is Invoice) when {resource.state == "sealed"};"""


def test_export__should_require_both_session_permission_and_visible_rows():
    async def run() -> None:
        db = create_async_engine(os.environ["CEDAR_TEST_PG"])
        try:
            async with db.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    insert(Invoice),
                    [
                        {"id": "1", "owner_id": "alice", "state": "open"},
                        {"id": "2", "owner_id": "alice", "state": "sealed"},
                        {"id": "3", "owner_id": "bob", "state": "open"},
                    ],
                )
            store = AsyncStore(
                db, Invoice, schema=SCHEMA, policies=POLICIES, action="export"
            )
            queries: list[str] = []
            event.listen(
                db.sync_engine,
                "before_cursor_execute",
                lambda conn, cur, stmt, params, ctx, many: queries.append(stmt),
            )
            verified = Session(
                "alice", "session-1"
            )  # Supplied by upstream authentication.

            async def identity(scope: Scope) -> Session:
                return verified

            stepped_up = {("alice", "session-1"): True}

            async def load(session: Session) -> Facts:
                return Facts(
                    principal_attrs={"can_export": True},
                    context={
                        "stepped_up": stepped_up[(session.user_id, session.session_id)]
                    },
                )

            async def export(scope: Scope, receive: Receive, send: Send) -> None:
                session = await identity(scope)
                rows = await store.for_user(session.user_id).page(limit=2)
                await JSONResponse([row.id for row in rows.items])(scope, receive, send)

            app = require_authorization(
                export,
                report_export(),
                identity=identity,
                load_facts=load,
                challenge="Bearer",
            )
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/export")).raise_for_status().json() == ["1"]
                assert len(queries) == 1
                stepped_up[("alice", "session-1")] = False
                queries.clear()
                assert (await client.get("/export")).status_code == 403
                assert not queries
        finally:
            await db.dispose()

    asyncio.run(run())
