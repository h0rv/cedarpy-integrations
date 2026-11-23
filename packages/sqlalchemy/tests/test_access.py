"""The same read contract on sync SQLite and native asyncio SQLite."""

import asyncio
import inspect as py_inspect
import threading
from pathlib import Path

import aiosqlite
import cedarpy
import pytest
from cedarpy_sqlalchemy import (
    AsyncStore,
    Candidates,
    CedarAuthorizationMixin,
    Denied,
    Page,
    ScanLimitExceeded,
    Store,
    UnsupportedForbid,
    attr,
    ref,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import (
    Engine,
    ForeignKey,
    String,
    create_engine,
    event,
    insert,
    inspect,
    select,
)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.pool import QueuePool


class AccessBase(DeclarativeBase):
    pass


class Document(AccessBase, CedarAuthorizationMixin):
    __tablename__ = "access_documents"
    cedar_type = "Document"

    # Caller-defined collation must not affect equality, order or resume.
    id: Mapped[str] = mapped_column(String(collation="NOCASE"), primary_key=True)
    state: Mapped[str] = mapped_column(info=attr("state"))
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))


SCHEMA = """
entity User;
entity Document = { state: String, owner: User };
action "read" appliesTo { principal: [User], resource: [Document] };
"""
POLICIES = """
permit(principal, action == Action::"read", resource is Document)
when { resource.owner == principal || resource.state == "published" };
forbid(principal, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
"""
WIDENED = POLICIES.replace(
    'resource.state == "published"', 'resource.state like "publish*"'
)


def _database(records: list[tuple[str, str, str]], path: Path | None = None) -> Engine:
    db = create_engine(f"sqlite:///{path}" if path else "sqlite://")
    with db.begin() as conn:
        AccessBase.metadata.tables[Document.__tablename__].create(conn)
        if records:
            conn.execute(
                insert(Document),
                [{"id": i, "state": s, "owner_id": o} for i, s, o in records],
            )
    return db


async def _resolve(result):
    return await result if py_inspect.isawaitable(result) else result


@pytest.mark.parametrize("native_async", [False, True], ids=["sync", "async"])
def test_read__should_enforce_one_contract(native_async, tmp_path):
    path = tmp_path / "contract.sqlite"
    alice = 'alice"\\\n雪'
    db = _database(
        [
            ("B", "draft", alice),
            ("a", "sealed", alice),
            ("cc", "published", "bob"),
            ("z", "draft", "bob"),
        ],
        path,
    )

    async def contract():
        adb = (
            create_async_engine(f"sqlite+aiosqlite:///{path}") if native_async else None
        )
        target = adb.sync_engine if adb else db
        statements = []
        event.listen(
            target,
            "before_cursor_execute",
            lambda c, cur, sql, args, ctx, many: statements.append(sql),
        )
        try:

            def store(policies=POLICIES, scan_limit=500):
                if adb:
                    return AsyncStore(
                        adb,
                        Document,
                        policies=policies,
                        schema=SCHEMA,
                        scan_limit=scan_limit,
                    )
                return Store(
                    db,
                    Document,
                    policies=policies,
                    schema=SCHEMA,
                    scan_limit=scan_limit,
                )

            with pytest.raises(ValueError, match="validate"):
                store(
                    'permit(principal, action, resource) when {resource.bad == "no"};'
                )
            with pytest.raises(UnsupportedForbid):
                unsupported = store(
                    POLICIES.replace(
                        'resource.state == "sealed"', 'resource.state like "seal*"'
                    )
                ).for_user(alice)
                await _resolve(unsupported.partial())
            docs = store()
            with pytest.raises(ValueError):
                docs.for_user("")
            assert (
                py_inspect.signature(docs.for_user)
                .parameters["authenticated_id"]
                .default
                is py_inspect.Parameter.empty
            )
            reads = docs.for_user(alice)
            bob = docs.for_user("bob")
            with pytest.raises(ValueError):
                await _resolve(reads.page(limit=0))
            assert not statements

            first = await _resolve(reads.page(limit=1))
            assert len(statements) == 1
            sql = statements[0].split("WHERE")[1]
            assert (
                "state" in sql
                and "owner_id" in sql
                and 'ORDER BY access_documents.id COLLATE "BINARY"' in sql
            )
            assert [r.id for r in first.items] == ["B"] and first.next_cursor == "B"
            assert (
                inspect(first.items[0]).detached
                and not inspect(first.items[0]).unloaded
            )
            second = await _resolve(reads.page(limit=1, after=first.next_cursor))
            assert [r.id for r in second.items] == ["cc"] and second.next_cursor is None
            # With NOCASE, 'a' < 'B'. Binary comparison must not accept that.
            assert [
                r.id for r in (await _resolve(reads.page(limit=5, after="a"))).items
            ] == ["cc"]
            assert await _resolve(reads.get("b")) is None
            assert await _resolve(reads.get("a")) is None
            assert await _resolve(reads.get("missing")) is None
            assert await _resolve(bob.get("B")) is None
            got = await _resolve(reads.get("B"))
            assert (
                got.owner_id == alice
                and inspect(got).detached
                and not inspect(got).unloaded
            )
            # No identity map or writeback is shared across protected reads.
            got.state = "locally changed"
            assert (await _resolve(reads.get("B"))).state == "draft"

            # Try an unsupported permit: SQL deliberately has false positives.
            widened = store(WIDENED, scan_limit=2).for_user(alice)
            assert await _resolve(widened.get("z")) is None
            page = await _resolve(widened.page(limit=1))
            assert page.next_cursor == "B"  # exactly two verified candidates suffice
            with pytest.raises(ScanLimitExceeded):
                await _resolve(
                    widened.page(limit=2)
                )  # inconclusive, not a partial result
            assert (
                await _resolve(widened.page(limit=1, after="B"))
            ).next_cursor is None
        finally:
            if adb:
                await adb.dispose()

    try:
        asyncio.run(contract())
        with Session(db) as other:
            assert len(other.scalars(select(Document)).all()) == 4
    finally:
        db.dispose()


@pytest.mark.parametrize("native_async", [False, True], ids=["sync", "async"])
def test_store__should_bind_action_and_check_its_scope_at_startup(
    native_async, tmp_path
):
    schema = (
        SCHEMA
        + """
    entity Service;
    action export appliesTo {principal: [User], resource: [Document],
                             context: {stepped_up: Bool, reason?: String}};
    action syncJob appliesTo {principal: [Service], resource: [Document]};
    action viewService appliesTo {principal: [User], resource: [Service]};
    """
    )
    policies = """
    permit(principal == User::"alice", action == Action::"read", resource);
    permit(principal == User::"bob", action == Action::"export", resource)
    when { context.stepped_up && resource.state like "publish*" };
    """
    path = tmp_path / "actions.sqlite"
    db = _database([("1", "published", "alice"), ("2", "draft", "alice")], path)

    async def contract():
        adb = (
            create_async_engine(f"sqlite+aiosqlite:///{path}") if native_async else None
        )
        facts = {"stepped_up": True}

        async def load_async():
            return facts

        def store(**kwargs):
            if adb:
                return AsyncStore(
                    adb, Document, policies=policies, schema=schema, **kwargs
                )
            return Store(db, Document, policies=policies, schema=schema, **kwargs)

        try:
            for action, error in [
                ("typo", "not declared"),
                ("syncJob", "principal type"),
                ("viewService", "resource type"),
            ]:
                with pytest.raises(ValueError, match=error):
                    store(action=action)

            default = store().for_user("bob")
            exports = store(action="export").for_user(
                "bob", load_context=load_async if adb else lambda: facts
            )
            assert isinstance(await _resolve(default.partial()), Denied)
            assert await _resolve(default.get("1")) is None
            assert await _resolve(default.page(limit=2)) == Page((), None)

            plan = await _resolve(exports.partial())
            assert isinstance(plan, Candidates) and plan.widened_permits
            assert (await _resolve(exports.get("1"))).id == "1"
            assert await _resolve(exports.get("2")) is None
            assert [
                row.id for row in (await _resolve(exports.page(limit=2))).items
            ] == ["1"]
            facts["stepped_up"] = False
            assert isinstance(await _resolve(exports.partial()), Denied)
            assert await _resolve(exports.get("1")) is None
        finally:
            if adb:
                await adb.dispose()

    try:
        asyncio.run(contract())
    finally:
        db.dispose()


@pytest.mark.parametrize("native_async", [False, True], ids=["sync", "async"])
def test_context__should_snapshot_once_and_skip_io_on_denial(native_async, tmp_path):
    path = tmp_path / "context.sqlite"
    db = _database([("1", "draft", "alice"), ("2", "published", "alice")], path)
    session_schema = SCHEMA.replace(
        "resource: [Document]", "resource: [Document], context: {revoked: Bool}"
    )
    policy = WIDENED + "forbid(principal, action, resource) when {context.revoked};"

    async def contract():
        adb = (
            create_async_engine(f"sqlite+aiosqlite:///{path}") if native_async else None
        )
        target = adb.sync_engine if adb else db
        calls = []
        checkouts = []
        sessions = {"A": {"revoked": False}, "B": {"revoked": False}}

        def checkout(*_):
            checkouts.append(1)
            # Mutate the loader's original mapping between planning and checking
            # rows. It must affect future operations but not the one in progress.
            sessions["A"]["revoked"] = True

        event.listen(target, "checkout", checkout)

        def bind(source, schema, session=None):
            def load():
                assert session is not None
                calls.append(session)
                if session == "failed":
                    raise LookupError("session service is down")
                if session == "incomplete":
                    return {}
                return sessions[session]

            if adb:

                async def load_async():
                    await asyncio.sleep(0)
                    return load()

                return AsyncStore(
                    adb, Document, policies=source, schema=schema
                ).for_user("alice", load_context=load_async if session else None)
            return Store(db, Document, policies=source, schema=schema).for_user(
                "alice", load_context=load if session else None
            )

        try:
            # A known denial takes priority over an absent required context,
            # with or without a loader. Inputs are checked even on fast paths.
            for session in (None, "failed"):
                denied = bind(
                    'permit(principal == User::"bob", action, resource);',
                    session_schema,
                    session,
                )
                assert isinstance(await _resolve(denied.partial()), Denied)
                assert await _resolve(denied.get("1")) is None
                assert await _resolve(denied.page(limit=1, after="0")) == Page((), None)
                with pytest.raises(ValueError):
                    await _resolve(denied.page(limit=-1))
                only_one = bind(
                    'permit(principal, action, resource == Document::"1");',
                    SCHEMA,
                    session,
                )
                assert await _resolve(only_one.get("2")) is None
            assert not calls and not checkouts

            with pytest.raises(ValueError, match="context"):
                await _resolve(bind(policy, session_schema).partial())
            with pytest.raises(ValueError, match="context"):
                await _resolve(bind(policy, session_schema, "incomplete").get("1"))
            with pytest.raises(LookupError, match="service is down"):
                await _resolve(bind(policy, session_schema, "failed").page(limit=1))
            assert calls == ["incomplete", "failed"] and not checkouts
            calls.clear()

            a = bind(policy, session_schema, "A")
            b = bind(policy, session_schema, "B")
            diagnostic = await _resolve(a.partial())
            assert isinstance(diagnostic, Candidates) and diagnostic.widened_permits
            assert calls == ["A"] and not checkouts
            sessions["A"]["revoked"] = True  # partial is not a cached grant
            assert await _resolve(a.get("1")) is None
            assert calls == ["A", "A"] and not checkouts

            sessions["A"]["revoked"] = False
            page = await _resolve(a.page(limit=1))
            assert [r.id for r in page.items] == ["1"] and page.next_cursor == "1"
            assert len(calls) == 3 and len(checkouts) == 1
            assert await _resolve(a.page(limit=1, after=page.next_cursor)) == Page(
                (), None
            )
            assert len(checkouts) == 1
            assert isinstance(await _resolve(a.partial()), Denied)
            assert await _resolve(b.get("1")) is not None
            assert calls == ["A"] * 5 + ["B"] and len(checkouts) == 2
        finally:
            if adb:
                await adb.dispose()

    try:
        asyncio.run(contract())
    finally:
        db.dispose()


def test_page__should_cross_batches_and_throw_on_inconclusive_empty_window():
    db = _database(
        [
            (f"{i:03}", "draft", "alice" if i in {1, 40, 79} else "bob")
            for i in range(80)
        ]
    )
    try:
        docs = Store(db, Document, policies=WIDENED, schema=SCHEMA).for_user("alice")
        first = docs.page(limit=2)
        assert [d.id for d in first.items] == [
            "001",
            "040",
        ] and first.next_cursor == "040"
        second = docs.page(limit=2, after=first.next_cursor)
        assert [d.id for d in second.items] == ["079"] and second.next_cursor is None
        limited = Store(
            db, Document, policies=WIDENED, schema=SCHEMA, scan_limit=3
        ).for_user("alice")
        with pytest.raises(ScanLimitExceeded):
            limited.page(limit=1, after="001")
    finally:
        db.dispose()


def test_verify__should_isolate_each_row_graph_and_reject_allow_with_errors():
    # Both permits are valid. On any row except "ticket", the second permit
    # errors (the named entity is missing), so even the known-true permit must
    # not release that row. Adding neighbors to the entity graph changes this.
    policy = """permit(principal, action, resource);
    permit(principal, action, resource) when { Document::"ticket".state == "draft" };"""
    db = _database([("ticket", "draft", "bob"), ("neighbor", "published", "alice")])
    try:
        docs = Store(db, Document, policies=policy, schema=SCHEMA).for_user("alice")
        assert docs.get("neighbor") is None
        assert [r.id for r in docs.page(limit=2).items] == ["ticket"]
    finally:
        db.dispose()


def test_mapping__should_reject_unsafe_orm_shapes():
    class Nullable(AccessBase, CedarAuthorizationMixin):
        __tablename__ = "access_nullable"
        cedar_type = "Document"

        id: Mapped[str] = mapped_column(primary_key=True)
        state: Mapped[str | None] = mapped_column(info=attr("state"))

    class Deferred(AccessBase, CedarAuthorizationMixin):
        __tablename__ = "access_deferred"
        cedar_type = "Document"

        id: Mapped[str] = mapped_column(primary_key=True)
        unprojected: Mapped[str] = mapped_column(deferred=True)

    class Joined(AccessBase, CedarAuthorizationMixin):
        __tablename__ = "access_joined"
        cedar_type = "Document"

        id: Mapped[str] = mapped_column(primary_key=True)
        doc_id: Mapped[str] = mapped_column(ForeignKey(Document.id))
        doc: Mapped[Document] = relationship(Document, lazy="joined")

    class Custom(AccessBase, CedarAuthorizationMixin):
        __tablename__ = "access_custom"
        __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy mapper convention
        cedar_type = "Document"

        id: Mapped[str] = mapped_column(primary_key=True)

    class Parent(AccessBase, CedarAuthorizationMixin):
        __tablename__ = "access_parent"
        cedar_type = "Document"

        id: Mapped[str] = mapped_column(primary_key=True)

    class Child(Parent):
        pass

    db = create_engine("sqlite://")
    for model in [Nullable, Deferred, Joined, Custom, Parent, Child]:
        with pytest.raises(ValueError):
            Store(db, model, policies=POLICIES, schema=SCHEMA)
    db.dispose()


def test_projection__should_freeze_attribute_and_resource_declarations(monkeypatch):
    db = _database([("1", "draft", "alice")])
    try:
        store = Store(db, Document, policies=POLICIES, schema=SCHEMA)
        monkeypatch.setattr(Document, "cedar_type", "Other")
        monkeypatch.setitem(
            Document.__table__.c.owner_id.info,
            "cedarpy_sqlalchemy",
            attr("garbage")["cedarpy_sqlalchemy"],
        )
        row = store.for_user("alice").get("1")
        assert row is not None and row.owner_id == "alice"
        assert store.for_user("bob").get("1") is None
    finally:
        db.dispose()


@settings(max_examples=45, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["draft", "published", "sealed"]),
            st.sampled_from(["alice", "bob"]),
        ),
        max_size=18,
    ),
    st.integers(1, 5),
    st.sampled_from([POLICIES, WIDENED]),
)
def test_pages__should_match_independent_concrete_cedar(records, size, policies):
    data = [(f"{i:02}", state, owner) for i, (state, owner) in enumerate(records)]
    db = _database(data)
    try:
        docs = Store(db, Document, policies=policies, schema=SCHEMA).for_user("alice")
        actual = []
        after = None
        while True:
            page: Page[Document] = docs.page(limit=size, after=after)
            actual.extend(row.id for row in page.items)
            if page.next_cursor is None:
                break
            assert after is None or after < page.next_cursor
            after = page.next_cursor
        expected = []
        principal = {"type": "User", "id": "alice"}
        for id_, state, owner in data:
            uid = {"type": "Document", "id": id_}
            decision = cedarpy.is_authorized(
                {
                    "principal": principal,
                    "action": {"type": "Action", "id": "read"},
                    "resource": uid,
                    "context": {},
                },
                policies,
                [
                    {
                        "uid": uid,
                        "attrs": {
                            "state": state,
                            "owner": {"__entity": {"type": "User", "id": owner}},
                        },
                        "parents": [],
                    },
                    {"uid": principal, "attrs": {}, "parents": []},
                ],
                schema=SCHEMA,
            )
            if decision.allowed and not decision.diagnostics.errors:
                expected.append(id_)
        assert actual == expected
    finally:
        db.dispose()


def test_async_cedar__should_run_off_loop_and_not_hold_db_after_cancellation(
    tmp_path, monkeypatch
):
    path = tmp_path / "worker.sqlite"
    _database([("1", "draft", "alice")], path).dispose()

    async def run():
        db = create_async_engine(
            f"sqlite+aiosqlite:///{path}", pool_size=1, max_overflow=0
        )
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        entered = asyncio.Event()
        release = threading.Event()
        finished = asyncio.Event()
        planning = []
        tpe = cedarpy.tpe_authorize
        authorize = cedarpy.is_authorized

        def observed_tpe(*args, **kwargs):
            assert threading.get_ident() != loop_thread
            planning.append(1)
            return tpe(*args, **kwargs)

        def blocking_check(request, policies, entities, *, schema):
            assert threading.get_ident() != loop_thread
            loop.call_soon_threadsafe(entered.set)
            try:
                assert release.wait(5), "event loop could not run during concrete check"
                return authorize(request, policies, entities, schema=schema)
            finally:
                loop.call_soon_threadsafe(finished.set)

        try:
            store = AsyncStore(db, Document, policies=POLICIES, schema=SCHEMA)
            monkeypatch.setattr(cedarpy, "tpe_authorize", observed_tpe)
            monkeypatch.setattr(cedarpy, "is_authorized", blocking_check)
            reader = store.for_user("alice")
            assert not planning
            async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
                read = tasks.create_task(reader.get("1"))
                await entered.wait()
                assert (
                    planning
                    and isinstance(db.pool, QueuePool)
                    and db.pool.checkedout() == 1
                )
                read.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await read
                # The bounded detached Cedar invocation may finish after cancel;
                # it does not own the session, stream, or checked-out connection.
                assert db.pool.checkedout() == 0 and not finished.is_set()
                release.set()
                await finished.wait()
        finally:
            release.set()
            await db.dispose()

    asyncio.run(run())


def test_async_page__should_close_stream_and_private_session_on_cancellation(
    tmp_path, monkeypatch
):
    path = tmp_path / "cancel.sqlite"
    _database([(str(i), "published", "alice") for i in range(65)], path).dispose()

    async def cancel_during_fetch():
        db = create_async_engine(
            f"sqlite+aiosqlite:///{path}", pool_size=1, max_overflow=0
        )
        fetching = asyncio.Event()
        held = []
        closed = []
        fetchmany = aiosqlite.Cursor.fetchmany
        close = aiosqlite.Cursor.close

        async def pause(cursor, size=None):
            if size and size > 1 and not fetching.is_set():
                held.append(cursor)
                fetching.set()
                await asyncio.Future()
            return await fetchmany(cursor, size)

        async def spy_close(cursor):
            closed.append(cursor)
            return await close(cursor)

        monkeypatch.setattr(aiosqlite.Cursor, "fetchmany", pause)
        monkeypatch.setattr(aiosqlite.Cursor, "close", spy_close)
        try:
            reader = AsyncStore(
                db, Document, policies=POLICIES, schema=SCHEMA
            ).for_user("alice")
            async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
                task = tasks.create_task(reader.page(limit=100))
                await fetching.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert held and held[0] in closed
            assert isinstance(db.pool, QueuePool) and db.pool.checkedout() == 0
            row = await reader.get("1")
            assert row is not None and row.state == "published"
        finally:
            await db.dispose()

    asyncio.run(cancel_during_fetch())
