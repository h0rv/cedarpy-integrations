import pytest
from cedarpy_sqlalchemy import CedarAuthorizationMixin, attr, ref
from cedarpy_sqlalchemy.checks import check_resource_schema
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base, CedarAuthorizationMixin):
    __tablename__ = "projection_schema_documents"
    cedar_type = "Document"

    id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(info={**attr("state"), "label": "Status"})
    team_id: Mapped[str] = mapped_column(info={**ref("team", "Team"), "cedar": "app"})
    notes: Mapped[str] = mapped_column(info={"cedar": "app-only"})


# A reference is a typed UID. Reads do not supply the referenced Team's facts.
SCHEMA = """
entity User;
entity Team = { name: String };
entity Document = { state: String, team: Team };
"""


def test_validate_schema__should_project_only_namespaced_column_info() -> None:
    check_resource_schema(Document, SCHEMA)
    columns = Base.metadata.tables[Document.__tablename__].c
    assert "cedarpy_sqlalchemy" in columns.status.info
    assert columns.status.info["label"] == "Status"
    assert "cedarpy_sqlalchemy" in columns.team_id.info
    assert columns.team_id.info["cedar"] == "app"
    assert columns.notes.info == {"cedar": "app-only"}


def test_mixin__should_not_supply_a_primary_key() -> None:
    class LegacyDocument(Base, CedarAuthorizationMixin):
        __tablename__ = "projection_schema_legacy_documents"
        cedar_type = "Document"

        slug: Mapped[str] = mapped_column(primary_key=True)

    assert "id" not in Base.metadata.tables[LegacyDocument.__tablename__].c
    with pytest.raises(ValueError, match="primary key"):
        check_resource_schema(LegacyDocument, SCHEMA)


@pytest.mark.parametrize(
    ("source", "replacement"),
    [
        pytest.param("state: String", "status: String", id="misspelled-attribute"),
        pytest.param("state: String", "state: Bool", id="wrong-scalar-type"),
        pytest.param("team: Team", "team: User", id="wrong-reference-target"),
        pytest.param("entity Document", "entity Report", id="unknown-resource-type"),
        pytest.param(
            "entity User;", "entity User = { role: String };", id="nonempty-principal"
        ),
    ],
)
def test_validate_schema__should_reject_incompatible_projection(
    source: str, replacement: str
) -> None:
    with pytest.raises(ValueError, match="projection for Document"):
        check_resource_schema(Document, SCHEMA.replace(source, replacement))
