"""The suggested index must serve the actual keyset expression on SQLite."""

from cedarpy_sqlalchemy import CedarAuthorizationMixin, Store
from sqlalchemy import String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def test_matching_index_supports_binary_cursor_on_nocase_primary_key():
    class Base(DeclarativeBase):
        pass

    class Card(Base, CedarAuthorizationMixin):
        __tablename__ = "card_cursor_index"
        cedar_type = "Card"

        id: Mapped[str] = mapped_column(String(collation="NOCASE"), primary_key=True)

    db = create_engine("sqlite://")
    try:
        with db.begin() as conn:
            conn.exec_driver_sql(
                "create table card_cursor_index (id varchar collate nocase primary key not null)"
            )
            conn.exec_driver_sql(
                "create index card_by_cedar_id on card_cursor_index(id collate binary)"
            )
        captured = []
        event.listen(
            db,
            "before_cursor_execute",
            lambda conn, cursor, stmt, params, ctx, many: captured.append(
                (stmt, params)
            ),
        )
        reader = Store(
            db,
            Card,
            policies="permit(principal,action,resource);",
            schema="entity User; entity Card; action read appliesTo {principal:[User],resource:[Card]};",
        ).for_user("alice")
        reader.page(after="1", limit=1)
        assert len(captured) == 1
        stmt, params = captured[0]
        with db.connect() as conn:
            details = [
                row[-1]
                for row in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + stmt, params)
            ]
        assert any("SEARCH" in d and "card_by_cedar_id" in d for d in details)
    finally:
        db.dispose()
