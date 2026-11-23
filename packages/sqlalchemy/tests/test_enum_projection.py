import os
from enum import StrEnum

import pytest
from cedarpy_sqlalchemy import (
    CedarAuthorizationMixin,
    Store,
    attr,
    enum_type,
    forbid_if,
    permit_if,
    principal,
    ref,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import String, TypeDecorator, create_engine, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class Status(StrEnum):
    PUBLIC = "public"
    SEALED = "sealed"
    DRAFT = "draft"


def _values(enum):
    return [member.value for member in enum]


def _storage(**options):
    return SqlEnum(Status, native_enum=False, values_callable=_values, **options)


def _document(storage, *, info=None, nullable=False):
    class Base(DeclarativeBase):
        pass

    table_options = {"prefixes": ["TEMPORARY"]}

    class Document(Base, CedarAuthorizationMixin):
        __tablename__ = "enum_projection_documents"
        __table_args__ = table_options
        cedar_rules = (
            permit_if(state="public"),
            permit_if(owner=principal),
            forbid_if(state="sealed"),
            forbid_if(state="PUBLIC"),  # A name, not a stored value.
        )
        id: Mapped[str] = mapped_column(primary_key=True)
        owner: Mapped[str] = mapped_column(info=ref("owner", "User"))
        status: Mapped[Status] = mapped_column(
            "Document Status",
            storage,
            nullable=nullable,
            info=attr("state") if info is None else info,
        )

    return Document


@pytest.mark.parametrize("postgres", [False, True], ids=["sqlite", "postgresql"])
@pytest.mark.parametrize("validate_strings", [False, True])
def test_store__should_compare_and_project_enum_values(
    validate_strings: bool, postgres: bool
) -> None:
    url = os.environ.get("CEDAR_TEST_PG") if postgres else "sqlite://"
    if url is None:
        pytest.skip("set CEDAR_TEST_PG to test PostgreSQL")
    model = _document(_storage(validate_strings=validate_strings))
    engine = create_engine(url, poolclass=StaticPool)
    try:
        with engine.begin() as conn:
            model.metadata.create_all(conn, checkfirst=False)
            conn.execute(
                insert(model),
                [
                    {"id": "1", "owner": "bob", "Document Status": Status.PUBLIC},
                    {"id": "2", "owner": "alice", "Document Status": Status.SEALED},
                    {"id": "3", "owner": "alice", "Document Status": Status.DRAFT},
                ],
            )
        reader = Store(engine, model, scan_limit=2).for_user("alice")
        row = reader.get("1")
        assert row is not None and row.status is Status.PUBLIC
        assert reader.get("2") is None
        first = reader.page(limit=1)
        assert [r.id for r in first.items] == ["1"] and first.next_cursor == "1"
        second = reader.page(limit=1, after=first.next_cursor)
        assert [r.id for r in second.items] == ["3"] and second.next_cursor is None
    finally:
        engine.dispose()


def test_mapped_column__should_respect_cedar_alias_and_infer_other_mapped_names():
    class Base(DeclarativeBase):
        pass

    class Document(Base, CedarAuthorizationMixin):
        __tablename__ = "documents"
        cedar_rules = (permit_if(state="public", label="open"),)

        id: Mapped[str] = mapped_column(primary_key=True)
        status: Mapped[Status] = mapped_column(
            enum_type(Status), index=True, info=attr("state")
        )
        label: Mapped[str] = mapped_column("db_label", info={"app": "tag", **attr()})

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            conn.execute(
                insert(Document),
                [{"id": "1", "status": Status.PUBLIC, "db_label": "open"}],
            )
            assert (
                conn.exec_driver_sql("SELECT status FROM documents").scalar_one()
                == "public"
            )
        doc = Store(engine, Document).for_user("alice").get("1")
        assert doc is not None and doc.status is Status.PUBLIC
        assert Document.__table__.c.db_label.info["app"] == "tag"
    finally:
        engine.dispose()


def test_store__should_reject_an_enum_primary_key() -> None:
    class Base(DeclarativeBase):
        pass

    class Document(Base, CedarAuthorizationMixin):
        __tablename__ = "documents"
        cedar_rules = ()
        id: Mapped[str] = mapped_column(_storage(), primary_key=True)

    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError, match="id: expected a non-null plain string"):
            Store(engine, Document)
    finally:
        engine.dispose()


class Decorated(TypeDecorator):
    impl = String
    cache_ok = True


@pytest.mark.parametrize(
    ("storage", "options"),
    [
        (SqlEnum(Status, native_enum=False), {}),
        (SqlEnum(Status, values_callable=_values), {}),
        (
            SqlEnum(
                Status, native_enum=False, values_callable=lambda e: _values(e)[::-1]
            ),
            {},
        ),
        (SqlEnum("public", "sealed", native_enum=False), {}),
        (_storage().with_variant(String(), "postgresql"), {}),
        (Decorated(), {}),
        (_storage(), {"nullable": True}),
        (_storage(), {"info": ref("state", "User")}),
    ],
)
def test_store__should_reject_unsupported_storage_before_reads(
    storage, options
) -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError, match="Document Status: expected"):
            Store(engine, _document(storage, **options))
    finally:
        engine.dispose()
