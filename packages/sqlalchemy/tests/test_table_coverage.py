import pytest
from cedarpy_sqlalchemy import CedarAuthorizationMixin
from cedarpy_sqlalchemy.checks import check_table_coverage
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    class_mapper,
    mapped_column,
    registry,
)

app_metadata = MetaData(naming_convention={"pk": "app_%(table_name)s_pk"})
app_registry = registry(metadata=app_metadata)


class AppBase(DeclarativeBase):
    registry = app_registry


class Tag(AppBase):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)


class Document(AppBase, CedarAuthorizationMixin):
    __tablename__ = "documents"
    cedar_type = "Document"

    id: Mapped[str] = mapped_column(primary_key=True)


links = Table(
    "document_tags",
    AppBase.metadata,
    Column("document_id", ForeignKey("documents.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)
jobs = Table("jobs", AppBase.metadata, Column("id", Integer, primary_key=True))
tags = AppBase.metadata.tables["tags"]


def test_protected_and_unprotected_models_share_app_mapping() -> None:
    assert class_mapper(Document).registry is class_mapper(Tag).registry is app_registry
    table = app_metadata.tables["documents"]
    assert table is Document.__table__
    assert table.primary_key.name == "app_documents_pk"


def test_checks_all_declared_tables_not_just_resource_mappers() -> None:
    exemptions = {tags: "Tag catalog", jobs: "Worker queue", links: "Tag membership"}
    check_table_coverage(AppBase.metadata, protected=[Document], exemptions=exemptions)
    with pytest.raises(
        ValueError, match="unclassified tables: document_tags, jobs, tags"
    ):
        check_table_coverage(AppBase.metadata, protected=[Document], exemptions={})


def test_protected_table_must_be_in_this_metadata_even_if_names_match() -> None:
    other = MetaData()
    documents = Table("documents", other)
    check_table_coverage(other, protected=[], exemptions={documents: "External data"})
    with pytest.raises(ValueError, match="documents is not in this MetaData"):
        check_table_coverage(other, protected=[Document], exemptions={})


def test_stale_exemption_cannot_cover_replacement_table() -> None:
    metadata = MetaData()
    old = Table("events", metadata)
    metadata.remove(old)
    Table("events", metadata)
    with pytest.raises(
        ValueError, match="events: exempt table is not in this MetaData"
    ):
        check_table_coverage(metadata, protected=[], exemptions={old: "Event log"})


def test_rejects_duplicate_or_conflicting_classification() -> None:
    with pytest.raises(
        ValueError, match="documents: declared protected more than once"
    ):
        check_table_coverage(
            AppBase.metadata, protected=[Document, Document], exemptions={}
        )
    with pytest.raises(ValueError, match="documents: both protected and exempt"):
        check_table_coverage(
            AppBase.metadata,
            protected=[Document],
            exemptions={AppBase.metadata.tables["documents"]: "Legacy data"},
        )


@pytest.mark.parametrize("reason", ["", " \t\n"])
def test_requires_nonblank_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="jobs: exemption needs a nonblank reason"):
        check_table_coverage(
            AppBase.metadata, protected=[Document], exemptions={jobs: reason}
        )


def test_rejects_empty_inventory() -> None:
    with pytest.raises(ValueError, match="no tables"):
        check_table_coverage(MetaData(), protected=[], exemptions={})


def test_protected_model_must_have_a_supported_projection() -> None:
    class Base(DeclarativeBase):
        pass

    class Unsupported(Base, CedarAuthorizationMixin):
        __tablename__ = "unsupported"
        cedar_type = "User"

        id: Mapped[str] = mapped_column(primary_key=True)

    with pytest.raises(ValueError, match="resource type cannot also be the principal"):
        check_table_coverage(Base.metadata, protected=[Unsupported], exemptions={})
