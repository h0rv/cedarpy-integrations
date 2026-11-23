"""Compare SQLite candidate IDs with independent concrete Cedar batch decisions."""

import json
from collections.abc import Iterator, Mapping
from functools import partial

import cedarpy
import pytest
from cedarpy_sqlalchemy.planner import (
    Candidates,
    Denied,
    Reference,
    UnsupportedForbid,
    denied_without_context,
)
from cedarpy_sqlalchemy.planner import (
    plan as candidate_plan,
)
from sqlalchemy import Column, Connection, String, Table, create_engine, insert, select
from sqlalchemy.orm import DeclarativeBase

plan = partial(candidate_plan, dialect="sqlite")


class Base(DeclarativeBase):
    pass


STATE = Column("state", String(collation="BINARY"), nullable=False)
OWNER = Column("owner", String, nullable=False)
DOC_ID = Column("id", String, primary_key=True)
REVIEWER_ID = Column("reviewer_id", String(collation="BINARY"), nullable=False)
REFERENCES = {"reviewer": Reference("User", REVIEWER_ID)}


class Document(Base):
    __table__ = Table("document", Base.metadata, DOC_ID, STATE, OWNER, REVIEWER_ID)


COLUMNS = {"state": STATE, "owner": OWNER}
PRINCIPAL = 'a"\\\n雪'
PRINCIPAL_UID = {"type": "User", "id": PRINCIPAL}
SCHEMA = cedarpy.Schema.from_str("""
    entity User;
    entity Document = {state: String, owner: String, reviewer: User};
    action read, write appliesTo {principal: [User], resource: [Document]};
""")
ROWS = [
    {"id": "a", "state": "open", "owner": "me", "reviewer_id": PRINCIPAL},
    {"id": "b", "state": "OPEN", "owner": "me", "reviewer_id": "someone else"},
    {"id": "c", "state": "closed", "owner": "me", "reviewer_id": "someone else"},
    {"id": "d", "state": "open", "owner": "you", "reviewer_id": "someone else"},
    {"id": "e", "state": "draft", "owner": "you", "reviewer_id": "someone else"},
]
ALL_IDS = set("abcde")
ANY = "permit(principal, action, resource);"


def test_unknown_step_up_only_skips_loader_if_denied_for_all_sessions():
    schema = cedarpy.Schema.from_str(
        "entity User; entity Document; action read appliesTo {principal: [User], resource: [Document], context: {stepped_up: Bool}};"
    )
    policies = cedarpy.PolicySet.from_str(
        'permit(principal == User::"alice", action, resource) when {context.stepped_up};'
    )
    assert denied_without_context(policies, schema, "bob", "Document")
    assert not denied_without_context(policies, schema, "alice", "Document")
    assert isinstance(
        plan(policies, schema, "alice", "Document", {}, context={"stepped_up": False}),
        Denied,
    )
    assert isinstance(
        plan(policies, schema, "alice", "Document", {}, context={"stepped_up": True}),
        Candidates,
    )


@pytest.fixture
def db() -> Iterator[Connection]:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(insert(Document), ROWS)
        yield conn
    engine.dispose()


def _sets(
    db: Connection,
    source: str,
    *,
    action: str = "read",
    references: Mapping[str, Reference] | None = None,
) -> tuple[set[str], set[str]]:
    policies = cedarpy.PolicySet.from_str(source)
    predicate = plan(
        policies,
        SCHEMA,
        PRINCIPAL,
        "Document",
        COLUMNS,
        action=action,
        references=references,
    )
    candidates = (
        set()
        if isinstance(predicate, Denied)
        else set(db.scalars(select(DOC_ID).where(predicate.candidate_predicate)))
    )
    entities = [{"uid": PRINCIPAL_UID, "attrs": {}, "parents": []}]
    requests = []
    other = {"type": "User", "id": "someone else"}
    entities.append({"uid": other, "attrs": {}, "parents": []})
    for row in ROWS:
        uid = {"type": "Document", "id": row["id"]}
        attrs = {
            "state": row["state"],
            "owner": row["owner"],
            "reviewer": {"__entity": {"type": "User", "id": row["reviewer_id"]}},
        }
        entities.append({"uid": uid, "attrs": attrs, "parents": []})
        requests.append(
            {
                "principal": PRINCIPAL_UID,
                "resource": uid,
                "action": {"type": "Action", "id": action},
                "context": {},
            }
        )
    results = cedarpy.is_authorized_batch(
        requests=requests, policies=policies, schema=SCHEMA, entities=entities
    )
    allowed = {
        row["id"]
        for row, result in zip(ROWS, results, strict=True)
        if result.decision == cedarpy.Decision.Allow and not result.diagnostics.errors
    }
    assert allowed <= candidates
    return candidates, allowed


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", set()),
        (ANY, ALL_IDS),
        (ANY + "forbid(principal, action, resource);", set()),
        (
            (
                'permit(principal, action, resource) when {resource.state == "open" || "me" == resource.owner};'
                'forbid(principal, action, resource) when {resource.owner == "me" && !(resource.state == "open")};'
            ),
            {"a", "d"},
        ),
        (
            (
                'permit(principal, action, resource) when {if resource.state != "open" then true else resource.owner == "me"} '
                'unless {resource.state == "draft"};'
            ),
            {"a", "b", "c"},
        ),
        (
            (
                'permit(principal, action, resource) when {resource.state == "closed"};'
                'permit(principal, action, resource) when {resource.state == "open"};'
            ),
            {"a", "c", "d"},
        ),
    ],
)
def test_plan__exact_fragment__should_match_concrete_cedar(db, source, expected):
    assert _sets(db, source) == (expected, expected)


def test_permanent_policy_error__should_return_no_rows_without_querying(db):
    source = (
        ANY + "forbid(principal,action,resource) when {9223372036854775807 + 1 == 0};"
    )
    assert _sets(db, source) == (set(), set())
    assert denied_without_context(
        cedarpy.PolicySet.from_str(source), SCHEMA, PRINCIPAL, "Document"
    )


def test_plan__unusual_principal_id_and_action_scope__should_match_concrete_cedar(db):
    uid_literal = json.dumps(PRINCIPAL, ensure_ascii=False)
    policy = f'permit(principal == User::{uid_literal}, action == Action::"write", resource) when {{resource.state == "open"}};'
    assert _sets(db, policy) == (set(), set())
    assert _sets(db, policy, action="write") == ({"a", "d"}, {"a", "d"})


@pytest.mark.parametrize(
    ("condition", "allowed"),
    [
        ('!(resource.state like "o*")', {"b", "e"}),
        ("resource.reviewer == principal", {"a"}),
    ],
)
def test_plan__unsupported_permit__should_widen_whole_policy_but_keep_forbid(
    db, condition, allowed
):
    source = (
        f"permit(principal, action, resource) when {{{condition}}};"
        + 'forbid(principal, action, resource) when {resource.state == "closed"};'
    )
    assert _sets(db, source) == (ALL_IDS - {"c"}, allowed)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "permit(principal, action, resource) when {principal == resource.reviewer};",
            {"a"},
        ),
        (
            "permit(principal, action, resource) when {resource.reviewer != principal};",
            ALL_IDS - {"a"},
        ),
        (
            ANY
            + "forbid(principal, action, resource) when {resource.reviewer == principal};",
            ALL_IDS - {"a"},
        ),
        (
            f"permit(principal, action, resource) when {{resource.reviewer == Document::{json.dumps(PRINCIPAL, ensure_ascii=False)}}};",
            set(),
        ),
        (
            f"permit(principal, action, resource) when {{Document::{json.dumps(PRINCIPAL, ensure_ascii=False)} != resource.reviewer}};",
            ALL_IDS,
        ),
    ],
)
def test_plan__declared_uid_reference__should_compare_type_and_id(db, source, expected):
    assert _sets(db, source, references=REFERENCES) == (expected, expected)


@pytest.mark.parametrize(
    "column",
    [
        Column("id", String, nullable=True),
        Column("id", String(collation="NOCASE"), nullable=False),
    ],
)
def test_plan__unsafe_reference_id_column__should_reject_residual_forbid(column):
    policies = cedarpy.PolicySet.from_str(
        ANY
        + "forbid(principal, action, resource) when {principal == resource.reviewer};"
    )
    with pytest.raises(UnsupportedForbid, match="policy1"):
        plan(
            policies,
            SCHEMA,
            PRINCIPAL,
            "Document",
            COLUMNS,
            references={"reviewer": Reference("User", column)},
        )


def test_plan__uid_scoped_permit__should_not_mistake_id_for_string_attr(db):
    source = 'permit(principal, action, resource == Document::"a");'
    assert _sets(db, source) == (ALL_IDS, {"a"})


@pytest.mark.parametrize(
    "forbid",
    [
        "forbid(principal, action, resource) when {resource.reviewer == principal};",
        'forbid(principal, action, resource == Document::"a") when {resource.state == "open"};',
        'forbid(principal, action, resource) unless {resource.state like "c*"};',
    ],
)
@pytest.mark.parametrize(
    "permit",
    [ANY, 'permit(principal, action, resource) when {resource.state like "*n"};'],
)
def test_plan__unsupported_residual_forbid__should_raise_even_with_broad_permit(
    permit, forbid
):
    policies = cedarpy.PolicySet.from_str(permit + forbid)
    with pytest.raises(UnsupportedForbid, match="policy1"):
        plan(policies, SCHEMA, PRINCIPAL, "Document", COLUMNS)


@pytest.mark.parametrize(
    "col",
    [
        Column("state", String, nullable=True),
        Column("state", String(collation="NOCASE"), nullable=False),
        Column(
            "state",
            String().with_variant(String(collation="RTRIM"), "sqlite"),
            nullable=False,
        ),
    ],
)
def test_plan__nonexact_sql_column__should_widen_permit_and_reject_forbid(db, col):
    expr = '(principal, action, resource) when {resource.state == "open"};'
    columns = {"state": col}
    pred = plan(
        cedarpy.PolicySet.from_str("permit" + expr),
        SCHEMA,
        PRINCIPAL,
        "Document",
        columns,
    )
    assert isinstance(pred, Candidates)
    assert pred.widened_permits == ("policy0",)
    assert isinstance(pred.residuals["policy0"], cedarpy.pst.Template)
    assert set(db.scalars(select(DOC_ID).where(pred.candidate_predicate))) == ALL_IDS
    with pytest.raises(UnsupportedForbid):
        plan(
            cedarpy.PolicySet.from_str(ANY + "forbid" + expr),
            SCHEMA,
            PRINCIPAL,
            "Document",
            columns,
        )
