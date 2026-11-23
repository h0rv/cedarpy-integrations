"""Static contract tests, written as consumer code; keep in the ty check."""

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, assert_type

from cedarpy import pst
from cedarpy_sqlalchemy import (
    AsyncReader,
    AsyncStore,
    Candidates,
    CedarAuthorizationMixin,
    Denied,
    Page,
    Reader,
    ReadPlan,
    Store,
    attr,
    enum_type,
    permit_if,
)
from sqlalchemy import Engine, Select, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.sql import ColumnElement

if TYPE_CHECKING:

    class Base(DeclarativeBase):
        pass

    class State(StrEnum):
        PUBLIC = "public"

    class Document(Base, CedarAuthorizationMixin):
        __tablename__ = "documents"
        cedar_rules = (permit_if(state="public"),)

        id: Mapped[str] = mapped_column(primary_key=True)
        title: Mapped[str]
        state: Mapped[State] = mapped_column(enum_type(State), info=attr())

    async def native_and_checked(engine: Engine, async_engine: AsyncEngine) -> None:
        docs = Store(engine, Document)
        async_docs = AsyncStore(async_engine, Document)
        sessionmaker(assert_type(docs.engine, Engine))
        async_sessionmaker(assert_type(async_docs.engine, AsyncEngine))
        assert_type(select(Document.title), Select[tuple[str]])
        assert_type(docs.for_user("alice").get("1"), Document | None)
        doc = assert_type(await async_docs.for_user("alice").get("1"), Document | None)
        if doc is not None:
            assert_type(doc.title, str)
            assert_type(doc.state, State)
        page = await async_docs.for_user("alice").page(limit=5)
        assert_type(page.items, tuple[Document, ...])

    def sync[R: CedarAuthorizationMixin](reader: Reader[R], id_: str) -> None:
        plan = assert_type(reader.partial(), ReadPlan)
        match plan:
            case Candidates():
                assert_type(plan.candidate_predicate, ColumnElement[bool])
                assert_type(plan.residuals, Mapping[str, pst.Template])
            case Denied():
                pass
        assert_type(reader.get(id_), R | None)
        assert_type(reader.page(limit=4), Page[R])

    async def asynchronous[R: CedarAuthorizationMixin](
        reader: AsyncReader[R], id_: str
    ) -> None:
        assert_type(await reader.partial(), ReadPlan)
        assert_type(await reader.get(id_), R | None)
        assert_type(await reader.page(limit=4), Page[R])
