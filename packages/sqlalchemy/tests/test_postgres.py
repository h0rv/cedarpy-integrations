"""Run with scripts/test-postgres. The script provisions a private cluster."""

import asyncio
import os
from collections.abc import Iterator

import cedarpy
import pytest
from cedarpy_sqlalchemy import (
    AsyncStore,
    CedarAuthorizationMixin,
    ScanLimitExceeded,
    Store,
    attr,
    ref,
)
from sqlalchemy import create_engine, insert, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Note(Base, CedarAuthorizationMixin):
    __tablename__ = "cedar_parity_notes"
    cedar_type = "Note"

    id: Mapped[str] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(info=attr("state"))
    author: Mapped[str] = mapped_column(info=ref("owner", "User"))


SCHEMA = 'entity User; entity Note = { state: String, owner: User }; action "read" appliesTo {principal: [User], resource: [Note]};'
POLICIES = """permit(principal, action == Action::"read", resource is Note) when {resource.owner == principal || resource.state == "public"};
forbid(principal, action, resource is Note) when {resource.state == "sealed"};"""
ROWS = [
    (
        str(n).zfill(2),
        "sealed" if n == 12 else "public" if n in (19, 41) else "private",
        "alice" if n in (1, 12, 50) else "bob",
    )
    for n in range(52)
]


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    address = os.environ.get("CEDAR_TEST_PG")
    if address is None:
        pytest.skip("use scripts/test-postgres to start a disposable Postgres cluster")
    db = create_engine(address)
    try:
        with db.begin() as c:
            # Refuse to reuse an existing test table in a manually supplied DB.
            c.execute(
                text(
                    "create table cedar_parity_notes (id varchar primary key, state varchar not null, author varchar not null)"
                )
            )
            c.execute(
                insert(Note), [{"id": i, "state": s, "author": a} for i, s, a in ROWS]
            )
        yield address
    finally:
        db.dispose()


def expected_for(policy: str) -> list[str]:
    result = []
    for i, s, a in ROWS:
        uid = {"type": "Note", "id": i}
        principal = {"type": "User", "id": "alice"}
        decision = cedarpy.is_authorized(
            {
                "principal": principal,
                "action": {"type": "Action", "id": "read"},
                "resource": uid,
                "context": {},
            },
            policy,
            [
                {
                    "uid": uid,
                    "attrs": {
                        "state": s,
                        "owner": {"__entity": {"type": "User", "id": a}},
                    },
                    "parents": [],
                },
                {"uid": principal, "attrs": {}, "parents": []},
            ],
            schema=SCHEMA,
        )
        if decision.allowed and not decision.diagnostics.errors:
            result.append(i)
    return result


@pytest.mark.parametrize(
    "policy", [POLICIES, POLICIES.replace('== "public"', 'like "pub*"')]
)
def test_cursor_parity(url: str, policy: str):
    db = create_engine(url)
    try:
        reader = Store(db, Note, policies=policy, schema=SCHEMA).for_user("alice")
        sync = []
        after = None
        while True:
            page = reader.page(limit=2, after=after)
            sync.append(([note.id for note in page.items], page.next_cursor))
            after = page.next_cursor
            if after is None:
                break
        assert reader.get("12") is None
    finally:
        db.dispose()

    async def run():
        db = create_async_engine(url)
        try:
            reader = AsyncStore(db, Note, policies=policy, schema=SCHEMA).for_user(
                "alice"
            )
            pages = []
            after = None
            while True:
                page = await reader.page(limit=2, after=after)
                pages.append(([note.id for note in page.items], page.next_cursor))
                after = page.next_cursor
                if after is None:
                    break
            assert await reader.get("12") is None
            return pages
        finally:
            await db.dispose()

    assert asyncio.run(run()) == sync
    assert [i for ids, _ in sync for i in ids] == expected_for(policy)
    assert sync[0][1] == sync[0][0][-1] and sync[-1][1] is None


def test_scan_limit_parity(url: str):
    broad = POLICIES.replace('== "public"', 'like "pub*"')
    db = create_engine(url)
    try:
        reader = Store(db, Note, policies=broad, schema=SCHEMA, scan_limit=2).for_user(
            "alice"
        )
        with pytest.raises(ScanLimitExceeded):
            reader.page(limit=2)
    finally:
        db.dispose()

    async def run():
        db = create_async_engine(url)
        try:
            reader = AsyncStore(
                db, Note, policies=broad, schema=SCHEMA, scan_limit=2
            ).for_user("alice")
            with pytest.raises(ScanLimitExceeded):
                await reader.page(limit=2)
        finally:
            await db.dispose()

    asyncio.run(run())


def test_step_up_from_postgres__should_skip_known_denials_and_observe_revocation(
    url: str,
):
    schema = SCHEMA.replace(
        "resource: [Note]", "resource: [Note], context: {stepped_up: Bool}"
    )
    policy = 'permit(principal == User::"alice", action, resource) when {context.stepped_up};'
    db = create_engine(url)
    statements: list[str] = []
    from sqlalchemy import event

    event.listen(
        db,
        "before_cursor_execute",
        lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt),
    )
    try:
        with db.begin() as conn:
            conn.execute(
                text(
                    "create table cedar_steps (actor text, session_key text, active boolean not null, primary key(actor, session_key))"
                )
            )
            conn.execute(
                text(
                    "insert into cedar_steps values ('alice','fresh',true), ('alice','old',false)"
                )
            )
        store = Store(db, Note, policies=policy, schema=schema)

        def scoped(actor: str, authenticated_session: str):
            def fetch() -> dict[str, bool]:
                with db.connect() as conn:
                    active = conn.scalar(
                        text(
                            "select active from cedar_steps where actor=:actor and session_key=:sid"
                        ),
                        {"actor": actor, "sid": authenticated_session},
                    )
                return {"stepped_up": active is True}

            return store.for_user(actor, load_context=fetch)

        statements.clear()
        assert not scoped("bob", "fresh").page(limit=1).items
        assert not statements
        assert not scoped("alice", "old").page(limit=1).items
        assert len(statements) == 1 and "cedar_steps" in statements[0]
        fresh = scoped("alice", "fresh")
        assert fresh.get("01") is not None
        with db.begin() as conn:
            conn.execute(
                text(
                    "update cedar_steps set active=false where actor='alice' and session_key='fresh'"
                )
            )
        statements.clear()
        assert fresh.get("01") is None
        assert len(statements) == 1 and "cedar_steps" in statements[0]
    finally:
        db.dispose()


def test_cancel_blocked_page_releases_connection(url: str):
    async def run():
        locker = create_async_engine(url)
        pool = create_async_engine(
            url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=2,
            connect_args={"application_name": "cedar_cancel_test"},
        )
        try:
            reader = AsyncStore(pool, Note, policies=POLICIES, schema=SCHEMA).for_user(
                "alice"
            )
            async with locker.begin() as lock:
                await lock.execute(
                    text("lock table cedar_parity_notes in access exclusive mode")
                )
                async with asyncio.TaskGroup() as group:
                    task = group.create_task(reader.page(limit=1))
                    async with asyncio.timeout(8):
                        while not await lock.scalar(
                            text(
                                "select exists (select 1 from pg_stat_activity where application_name='cedar_cancel_test' and wait_event_type='Lock')"
                            )
                        ):
                            # Postgres snapshots stats per transaction by default.
                            await lock.execute(text("select pg_stat_clear_snapshot()"))
                            await asyncio.sleep(0.02)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            async with asyncio.timeout(3):
                note = await reader.get("01")
                assert note is not None and note.id == "01"
        finally:
            await pool.dispose()
            await locker.dispose()

    asyncio.run(run())
