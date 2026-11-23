"""Model-declared read rules must agree with independently written Cedar."""

import asyncio
from inspect import isawaitable

import cedarpy
import pytest
from cedarpy_sqlalchemy import (
    AsyncStore,
    CedarAuthorizationMixin,
    Store,
    attr,
    forbid_if,
    permit_if,
    principal,
    ref,
)
from sqlalchemy import create_engine, insert, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RULES = (
    permit_if(owner=principal),
    permit_if(state="public"),
    forbid_if(state="sealed"),
)
SCHEMA = """
entity User;
entity Document = { owner: User, state: String };
action "read" appliesTo { principal: [User], resource: [Document] };
"""
POLICIES = """
permit(principal, action == Action::"read", resource is Document)
when { resource.owner == principal || resource.state == "public" };
forbid(principal, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
"""
ROWS = (("1", "alice", "draft"), ("2", "alice", "sealed"), ("3", "bob", "public"))


def _document(rules=None):
    class Base(DeclarativeBase):
        pass

    class Document(Base, CedarAuthorizationMixin):
        __tablename__ = "documents"
        if rules is not None:  # Omitted metadata is distinct from an empty tuple.
            cedar_rules = rules

        id: Mapped[str] = mapped_column(primary_key=True)
        title: Mapped[str]
        owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
        status: Mapped[str] = mapped_column(info=attr("state"))

    return Document


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rules.sqlite'}")
    model = _document()
    try:
        with engine.begin() as conn:
            model.metadata.create_all(conn)
            conn.execute(
                insert(model),
                [
                    {"id": i, "title": f"Doc {i}", "owner_id": o, "status": s}
                    for i, o, s in ROWS
                ],
            )
        yield engine
    finally:
        engine.dispose()


def _cedar_allows(user, key, owner, state):
    who = {"type": "User", "id": user}
    uid = {"type": "Document", "id": key}
    result = cedarpy.is_authorized(
        {
            "principal": who,
            "action": {"type": "Action", "id": "read"},
            "resource": uid,
            "context": {},
        },
        POLICIES,
        [
            {"uid": who, "parents": [], "attrs": {}},
            {
                "uid": uid,
                "parents": [],
                "attrs": {
                    "owner": {"__entity": {"type": "User", "id": owner}},
                    "state": state,
                },
            },
        ],
        schema=SCHEMA,
    )
    assert not result.diagnostics.errors
    return result.allowed


async def _resolve(value):
    return await value if isawaitable(value) else value


@pytest.mark.parametrize("native_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("rules", [RULES, None, ()], ids=["model", "text", "empty"])
def test_reads__should_match_concrete_cedar(db, native_async, rules):
    model = _document(rules)
    policies, schema = (POLICIES, SCHEMA) if rules is None else (None, None)

    async def check():
        adb = (
            create_async_engine(db.url.set(drivername="sqlite+aiosqlite"))
            if native_async
            else None
        )
        try:
            store = (
                AsyncStore(adb, model, policies=policies, schema=schema)
                if adb
                else Store(db, model, policies=policies, schema=schema)
            )
            # The native engine is unchanged; only reads through for_user run Cedar.
            query = select(model.id).order_by(model.id)
            if adb is not None:
                assert store.engine is adb
                async with adb.connect() as conn:
                    assert list(await conn.scalars(query)) == ["1", "2", "3"]
            else:
                assert store.engine is db
                with db.connect() as conn:
                    assert list(conn.scalars(query)) == ["1", "2", "3"]
            for user in ("alice", "bob"):
                reader = store.for_user(user)
                expected = []
                for key, owner, state in ROWS:
                    allowed = rules != () and _cedar_allows(user, key, owner, state)
                    row = await _resolve(reader.get(key))
                    if allowed:
                        assert row is not None and row.id == key
                        assert isinstance(row, model) and row.title == f"Doc {key}"
                        expected.append(key)
                    else:
                        assert row is None

                # Walk one item at a time so a forbidden row between permits
                # cannot displace a permitted row or leak through a later page.
                after = None
                for i, key in enumerate(expected):
                    page = await _resolve(reader.page(limit=1, after=after))
                    assert [row.id for row in page.items] == [key]
                    after = page.next_cursor
                    assert after == (key if i + 1 < len(expected) else None)
                if not expected:
                    page = await _resolve(reader.page(limit=1))
                    assert not page.items and page.next_cursor is None
        finally:
            if adb:
                await adb.dispose()

    asyncio.run(check())


@pytest.mark.parametrize("rules", [RULES, ()], ids=["nonempty", "empty"])
@pytest.mark.parametrize(
    "inputs",
    [
        {"policies": POLICIES},
        {"schema": SCHEMA},
        {"policies": POLICIES, "schema": SCHEMA},
    ],
    ids=["policies", "schema", "both"],
)
def test_store__should_reject_mixed_inputs(db, rules, inputs):
    with pytest.raises((ValueError, TypeError)):
        Store(db, _document(rules), **inputs)


@pytest.mark.parametrize(
    "inputs",
    [{}, {"policies": POLICIES}, {"schema": SCHEMA}],
    ids=["neither", "only-policies", "only-schema"],
)
def test_store__should_require_both_text_inputs_without_model_rules(db, inputs):
    with pytest.raises((ValueError, TypeError)):
        Store(db, _document(), **inputs)


@pytest.mark.parametrize(
    "condition",
    [
        {"staet": "public"},
        {"state": principal},
        {"owner": "alice"},
    ],
    ids=["unknown-field", "principal-for-string", "string-for-ref"],
)
def test_store__should_refuse_invalid_rules(db, condition):
    with pytest.raises((ValueError, TypeError)):
        Store(db, _document((permit_if(**condition),)))


def test_store__should_parse_and_validate_files_at_startup(db, tmp_path):
    policy_file = tmp_path / "documents.cedar"
    schema_file = tmp_path / "documents.cedarschema"
    policy_file.write_text(POLICIES, encoding="utf-8")
    schema_file.write_text(SCHEMA, encoding="utf-8")
    model = _document()
    store = Store(db, model, policies=policy_file, schema=schema_file)

    policy_file.write_text(
        POLICIES.replace("resource.owner", "resource.owenr"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="do not validate"):
        Store(db, model, policies=policy_file, schema=schema_file)
    schema_file.unlink()
    with pytest.raises(FileNotFoundError):
        Store(db, model, policies=policy_file, schema=schema_file)
    assert [d.id for d in store.for_user("alice").page(limit=10).items] == ["1", "3"]


def test_rule__should_require_all_conditions(db):
    model = _document((permit_if(owner=principal, state="public"),))
    store = Store(db, model)
    assert not store.for_user("alice").page(limit=10).items
    assert [row.id for row in store.for_user("bob").page(limit=10).items] == ["3"]


def test_store__should_not_rebind_model_rules_to_another_action(db):
    with pytest.raises(ValueError):
        Store(db, _document(RULES), action="write")
