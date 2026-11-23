"""The adapters consume a shared static policy without importing its authoring API."""

from pathlib import Path

import cedarpy
import pytest
from cedarpy_sqlalchemy import CedarAuthorizationMixin, Store, attr, enum_type, ref
from cedarpy_web import Facts, Permission
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from examples.report_export_policy import export_policy
from examples.typed_policy import documents, reports
from examples.typed_policy.domain import DocumentState


class Base(DeclarativeBase):
    pass


class Document(Base, CedarAuthorizationMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
    state: Mapped[DocumentState] = mapped_column(enum_type(DocumentState), info=attr())


ROOT = Path(__file__).resolve().parents[1]
SQL_SCHEMA = ROOT / "packages/sqlalchemy/examples/documents.cedarschema"
WEB_SCHEMA = ROOT / "packages/web/examples/reports.cedarschema"


def test_shared_policy__should_check_rows_and_operation_independently():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            conn.execute(
                insert(Document),
                [
                    {
                        "id": "1",
                        "owner_id": "alice",
                        "state": DocumentState.SEALED,
                    },
                    {"id": "2", "owner_id": "bob", "state": DocumentState.PUBLIC},
                ],
            )
        reader = Store(
            engine, Document, policies=documents.read, schema=SQL_SCHEMA
        ).for_user("alice")
        operation = Permission(
            action="export",
            service="reports",
            policies=reports.start_export,
            schema=WEB_SCHEMA,
        )
        assert operation.allows(
            "alice",
            Facts(principal_attrs={"can_export": True}, context={"stepped_up": True}),
        )
        assert reader.get("1") is None
        (public,) = reader.page(limit=10).items
        assert public.id == "2" and public.state is DocumentState.PUBLIC
        assert not operation.allows(
            "alice",
            Facts(principal_attrs={"can_export": True}, context={"stepped_up": False}),
        )
    finally:
        engine.dispose()


def test_export__missing_step_up__should_not_grant_even_without_schema_validation():
    alice = {"type": "User", "id": "alice"}
    request = {
        "principal": alice,
        "action": {"type": "Action", "id": "export"},
        "resource": {"type": "Service", "id": "reports"},
        "context": {},
    }
    entities = [{"uid": alice, "attrs": {"can_export": True}, "parents": []}]
    native = cedarpy.PolicySet.from_str(WEB_SCHEMA.with_suffix(".cedar").read_text())
    for policies in (native, export_policy(), reports.start_export):
        result = cedarpy.is_authorized(request, policies, entities)
        assert result.diagnostics.errors
        assert not result.allowed


def test_shared_policy__should_not_drop_template_links_during_validation():
    source = (ROOT / "tests/fixtures/export-template.cedar").read_text(encoding="utf-8")
    unlinked = cedarpy.PolicySet.from_str(source)
    alice = {"type": "User", "id": "alice"}
    policies = unlinked.with_linked("block-user", "block-alice", {"?principal": alice})
    request = {
        "principal": alice,
        "action": {"type": "Action", "id": "export"},
        "resource": {"type": "Service", "id": "reports"},
        "context": {},
    }
    assert cedarpy.is_authorized(request, unlinked, []).allowed
    assert not cedarpy.is_authorized(request, policies, []).allowed
    with pytest.raises(ValueError, match="static policy set"):
        Permission(
            action="export", service="reports", schema=WEB_SCHEMA, policies=policies
        )
    engine = create_engine("sqlite://")
    try:
        for unsupported in (source, policies):
            with pytest.raises(ValueError, match="static policy set"):
                Store(engine, Document, policies=unsupported, schema=SQL_SCHEMA)
    finally:
        engine.dispose()
