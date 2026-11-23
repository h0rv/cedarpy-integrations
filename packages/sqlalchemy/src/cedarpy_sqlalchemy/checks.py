"""Offline CI checks for resource projections and declared tables."""

from collections.abc import Iterable, Mapping

import cedarpy
from sqlalchemy import MetaData, Table

from cedarpy_sqlalchemy._model import CedarAuthorizationMixin, Projection

__all__ = ["check_resource_schema", "check_table_coverage"]


def check_resource_schema(model: type[CedarAuthorizationMixin], schema: str) -> None:
    """Raise if the reader's projected resource and empty User do not fit schema."""
    projection = Projection.from_model(model)
    projection.validate_schema(cedarpy.Schema.from_str(schema))


def check_table_coverage(
    metadata: MetaData,
    *,
    protected: Iterable[type[CedarAuthorizationMixin]],
    exemptions: Mapping[Table, str],
) -> None:
    """Require one explicit classification per table in this loaded MetaData."""
    tables = set(metadata.tables.values())
    if not tables:
        raise ValueError("MetaData contains no tables; import table declarations first")

    protected_tables: set[Table] = set()
    for model in protected:
        table = Projection.from_model(model).primary.table
        if table not in tables:
            raise ValueError(f"{model.__name__}: table {table} is not in this MetaData")
        if table in protected_tables:
            raise ValueError(f"{table}: declared protected more than once")
        protected_tables.add(table)

    for table, reason in exemptions.items():
        if table not in tables:
            raise ValueError(f"{table}: exempt table is not in this MetaData")
        if table in protected_tables:
            raise ValueError(f"{table}: both protected and exempt")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{table}: exemption needs a nonblank reason")

    missing = tables.difference(protected_tables, exemptions)
    if missing:
        raise ValueError(
            "unclassified tables: " + ", ".join(sorted(t.key for t in missing))
        )
