"""Explicit Cedar read capabilities. SQL selects candidates; Cedar decides access."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import cedarpy
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, raiseload
from sqlalchemy.sql import ColumnElement, Select

from cedarpy_sqlalchemy._model import CedarAuthorizationMixin, Projection
from cedarpy_sqlalchemy._rules import compile_rules
from cedarpy_sqlalchemy.planner import (
    Candidates,
    Denied,
    ReadPlan,
    Reference,
    denied_without_context,
    plan,
)


class ScanLimitExceeded(Exception):
    """A page or its continuation could not be determined within the scan budget."""


@dataclass(frozen=True, slots=True)
class Page[T]:
    """Detached authorized rows, with the last returned id iff more are visible."""

    items: tuple[T, ...]
    next_cursor: str | None


type _Dialect = Literal["sqlite", "postgresql"]
type _Context = Mapping[str, str | bool | int]
type _Loader = Callable[[], _Context]
type _AsyncLoader = Callable[[], Awaitable[_Context]]
_EMPTY_CONTEXT: _Context = MappingProxyType({})


def _snapshot(context: _Context) -> _Context:
    if not isinstance(context, Mapping):
        raise TypeError("load_context must return a mapping")
    values = dict(context)
    for key, value in values.items():
        if type(key) is not str or type(value) not in (str, bool, int):
            raise TypeError(
                "expected string context keys and scalar str/bool/int values"
            )
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ValueError("Cedar Long must fit in a signed 64-bit integer")
    return MappingProxyType(values)


@dataclass(frozen=True, slots=True)
class _Binding[T: CedarAuthorizationMixin]:
    projection: Projection[T]
    policies: cedarpy.PolicySet
    schema: cedarpy.Schema
    action: str
    scan_limit: int
    dialect: _Dialect

    @classmethod
    def build(
        cls,
        model: type[T],
        policies: str | Path | cedarpy.PolicySet | None,
        schema: str | Path | cedarpy.Schema | None,
        action: str,
        scan_limit: int,
        dialect: str,
    ) -> "_Binding[T]":
        if dialect not in ("sqlite", "postgresql"):
            raise ValueError("expected SQLite or PostgreSQL")
        if type(scan_limit) is not int or scan_limit < 1:
            raise ValueError("scan_limit must be a positive integer")
        projection = Projection.from_model(model)
        if type(action) is not str:
            raise TypeError("expected a Cedar action ID string")
        if (rules := model.cedar_rules) is not None:
            if policies is not None or schema is not None:
                raise ValueError(
                    "choose model cedar_rules or external policies and schema, not both"
                )
            if action != "read":
                raise ValueError("model cedar_rules apply only to the read action")
            if not isinstance(rules, tuple):
                raise TypeError("cedar_rules must be a tuple of rules")
            policies = compile_rules(projection, action, rules)
            checked_schema = projection.read_schema()
        else:
            if policies is None or schema is None:
                raise ValueError(
                    "declare cedar_rules or supply both policies and schema"
                )
            if isinstance(policies, Path):
                policies = policies.read_text(encoding="utf-8")
            if isinstance(schema, Path):
                schema = schema.read_text(encoding="utf-8")
            checked_schema = (
                schema
                if isinstance(schema, cedarpy.Schema)
                else cedarpy.Schema.from_str(schema)
            )
        projection.validate_schema(checked_schema)
        # Building the typed partial request checks appliesTo even without any
        # policies. Leave context unknown; only real sessions can supply it.
        cedarpy.tpe_authorize(
            principal=cedarpy.pst.EntityType("User"),
            action={"type": "Action", "id": action},
            resource=cedarpy.pst.EntityType(projection.kind),
            policies="",
            entities=[],
            schema=checked_schema,
        )
        parsed_policies = (
            policies
            if isinstance(policies, cedarpy.PolicySet)
            else cedarpy.PolicySet.from_str(policies)
        )
        if parsed_policies.templates():
            raise ValueError("expected a static policy set without templates or links")
        source = policies if isinstance(policies, str) else str(parsed_policies)
        validation = cedarpy.validate_policies(source, checked_schema)
        if not validation.validation_passed:
            raise ValueError(
                f"policies do not validate against this schema: {validation.errors}"
            )
        return cls(
            projection,
            parsed_policies,
            checked_schema,
            action,
            scan_limit,
            dialect,
        )

    def for_user(self, authenticated_id: str) -> "_Queries[T]":
        if type(authenticated_id) is not str or not authenticated_id:
            raise ValueError("a nonempty authenticated user id is required")
        # Match lookup, resume and order irrespective of declared collation;
        # no dialect-specific DDL on the model.
        key = self.projection.primary.collate(
            "BINARY" if self.dialect == "sqlite" else "C"
        )
        base = (
            select(self.projection.model)
            .options(raiseload("*"))
            .execution_options(yield_per=32)
        )
        return _Queries(self, authenticated_id, key, base)


@dataclass(frozen=True, slots=True)
class _Queries[T: CedarAuthorizationMixin]:
    binding: _Binding[T]
    principal_id: str
    key: ColumnElement[str]
    base: Select[tuple[T]]

    def lookup(self, id_: str) -> Select[tuple[T]] | None:
        if type(id_) is not str:
            raise ValueError("expected a string resource id")
        if self.denied(resource_id=id_):
            return None
        return self.base.where(self.key == id_)

    def denied(self, *, resource_id: str | None = None) -> bool:
        b = self.binding
        return denied_without_context(
            b.policies,
            b.schema,
            self.principal_id,
            b.projection.kind,
            action=b.action,
            resource_id=resource_id,
        )

    def window(self, limit: int, after: str | None) -> Select[tuple[T]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("page size must be an integer from 1 to 100")
        stmt = self.base.order_by(self.key).limit(self.binding.scan_limit + 1)
        if after is None:
            return stmt
        if type(after) is not str:
            raise ValueError("expected a string keyset cursor")
        return stmt.where(self.key > after)

    def scope(self, facts: _Context) -> "_Scope[T] | Denied":
        binding = self.binding
        p = binding.projection
        result = plan(
            binding.policies,
            binding.schema,
            self.principal_id,
            p.kind,
            {f.fact.name: f.column for f in p.fields if f.fact.reference is None},
            references={
                f.fact.name: Reference(f.fact.reference, f.column)
                for f in p.fields
                if f.fact.reference is not None
            },
            dialect=binding.dialect,
            action=binding.action,
            context=facts,
        )
        if isinstance(result, Denied):
            return result
        return _Scope(binding, self.principal_id, facts, result)

    def fixed(self) -> "_Scope[T] | Denied":
        return Denied() if self.denied() else self.scope(_EMPTY_CONTEXT)


@dataclass(frozen=True, slots=True)
class _Scope[T: CedarAuthorizationMixin]:
    binding: _Binding[T]
    principal_id: str
    context: _Context
    candidates: Candidates

    def project(self, row: T) -> "_Check":
        principal = {"type": "User", "id": self.principal_id}
        entity = self.binding.projection.entity(row)
        # Only this row and its principal exist. Adding other candidates could
        # make rules depending on a literal UID change with batch/page size.
        return _Check(
            {
                "principal": principal,
                "action": {"type": "Action", "id": self.binding.action},
                "resource": entity["uid"],
                "context": dict(self.context),
            },
            self.binding.policies,
            [entity, {"uid": principal, "attrs": {}, "parents": []}],
            self.binding.schema,
        )


@dataclass(frozen=True, slots=True)
class _Check:
    """Plain request data and immutable Cedar handles; no live ORM references."""

    request: dict
    policies: cedarpy.PolicySet
    entities: list[dict]
    schema: cedarpy.Schema

    def allowed(self) -> bool:
        result = cedarpy.is_authorized(
            self.request, self.policies, self.entities, schema=self.schema
        )
        return result.allowed and not result.diagnostics.errors


@dataclass(slots=True)
class _Scan[T: CedarAuthorizationMixin]:
    scope: _Scope[T]
    want: int
    scanned: int = 0
    found: list[T] = field(default_factory=list)

    def check(self, row: T) -> _Check:
        # SQL may deliver one sentinel beyond the budget. Never authorize it,
        # and never mistake an inconclusive search for the final page.
        if self.scanned == self.scope.binding.scan_limit:
            raise ScanLimitExceeded("authorized page not known within scan_limit")
        self.scanned += 1
        return self.scope.project(row)

    def keep(self, row: T, *, allowed: bool) -> bool:
        if allowed:
            self.found.append(row)
        return len(self.found) == self.want


def _page[T: CedarAuthorizationMixin](rows: list[T], limit: int) -> Page[T]:
    items = tuple(rows[:limit])
    return Page(items, items[-1].id if len(rows) > limit else None)


class Store[T: CedarAuthorizationMixin]:
    """Bind a sync engine, a flat mapped model and validated Cedar policies at startup."""

    def __init__(
        self,
        engine: Engine,
        model: type[T],
        *,
        policies: str | Path | cedarpy.PolicySet | None = None,
        schema: str | Path | cedarpy.Schema | None = None,
        action: str = "read",
        scan_limit: int = 500,
    ) -> None:
        if not isinstance(engine, Engine) or engine.dialect.is_async:
            raise TypeError("Store requires a synchronous Engine")
        self._engine = engine
        self._binding = _Binding.build(
            model, policies, schema, action, scan_limit, engine.dialect.name
        )

    @property
    def engine(self) -> Engine:
        """The original SQLAlchemy engine. Operations on it do not run Cedar."""
        return self._engine

    def for_user(
        self, authenticated_id: str, *, load_context: _Loader | None = None
    ) -> "Reader[T]":
        """Scope reads to an authenticated User. The optional zero-argument loader
        captures that user's verified session, not ambient request state. It returns
        a scalar context mapping once per operation unless denial is already known.
        """
        return Reader(self, authenticated_id, load_context=load_context)


class AsyncStore[T: CedarAuthorizationMixin]:
    """Bind a native async engine. Await the reader's get, page, and partial methods."""

    def __init__(
        self,
        engine: AsyncEngine,
        model: type[T],
        *,
        policies: str | Path | cedarpy.PolicySet | None = None,
        schema: str | Path | cedarpy.Schema | None = None,
        action: str = "read",
        scan_limit: int = 500,
    ) -> None:
        if not isinstance(engine, AsyncEngine):
            raise TypeError("AsyncStore requires an AsyncEngine")
        self._engine = engine
        self._binding = _Binding.build(
            model, policies, schema, action, scan_limit, engine.dialect.name
        )

    @property
    def engine(self) -> AsyncEngine:
        """The original SQLAlchemy async engine. Operations on it do not run Cedar."""
        return self._engine

    def for_user(
        self, authenticated_id: str, *, load_context: _AsyncLoader | None = None
    ) -> "AsyncReader[T]":
        """Scope reads to a User. An async loader bound to the authenticated session
        is awaited once per operation unless denial is already known.
        """
        return AsyncReader(self, authenticated_id, load_context=load_context)


class Reader[T: CedarAuthorizationMixin]:
    """User-scoped sync reads. Each DB operation owns and closes a private Session."""

    def __init__(
        self,
        store: Store[T],
        authenticated_id: str,
        *,
        load_context: _Loader | None = None,
    ) -> None:
        self._engine = store._engine
        self._queries = store._binding.for_user(authenticated_id)
        self._source: _Scope[T] | Denied | _Loader
        if load_context is None:
            self._source = self._queries.fixed()
        elif self._queries.denied():
            self._source = Denied()
        else:
            self._source = load_context

    def _scope(self) -> _Scope[T] | Denied:
        if isinstance(self._source, (_Scope, Denied)):
            return self._source
        return self._queries.scope(_snapshot(self._source()))

    def partial(self) -> ReadPlan:
        """Inspect one operation's candidate plan without reading any rows.

        This is not a grant of access. A subsequent read loads fresh context.
        """
        # Don't expose the SQL expression used internally for context-free reads.
        scope = (
            self._queries.scope(_EMPTY_CONTEXT)
            if isinstance(self._source, _Scope)
            else self._scope()
        )
        return scope if isinstance(scope, Denied) else scope.candidates

    def _read(self, stmt: Select[tuple[T]], want: int) -> list[T]:
        scope = self._scope()
        if isinstance(scope, Denied):
            return []
        scan = _Scan(scope, want)
        with (
            Session(self._engine, autoflush=False) as session,
            closing(
                session.scalars(stmt.where(scope.candidates.candidate_predicate))
            ) as rows,
        ):
            for row in rows:
                if scan.keep(row, allowed=scan.check(row).allowed()):
                    break
        return scan.found

    def get(self, id_: str) -> T | None:
        """Return a detached authorized row, or None for missing or denied."""
        stmt = self._queries.lookup(id_)
        if stmt is None:
            return None
        rows = self._read(stmt, 1)
        return rows[0] if rows else None

    def page(self, *, limit: int, after: str | None = None) -> Page[T]:
        """Return up to limit visible rows after the exclusive string cursor."""
        return _page(self._read(self._queries.window(limit, after), limit + 1), limit)


class AsyncReader[T: CedarAuthorizationMixin]:
    """User-scoped reads on a new native AsyncSession per DB operation."""

    def __init__(
        self,
        store: AsyncStore[T],
        authenticated_id: str,
        *,
        load_context: _AsyncLoader | None = None,
    ) -> None:
        self._engine = store._engine
        self._queries = store._binding.for_user(authenticated_id)
        self._loader = load_context
        self._fixed: _Scope[T] | Denied | None = None

    async def _scope(self, *, diagnostic: bool = False) -> _Scope[T] | Denied:
        if self._loader is None:
            # Only context-free plans can be reused. Never expose our internal
            # SQL expression via partial(), or cache the one handed to a caller.
            if self._fixed is not None and not diagnostic:
                return self._fixed
            scope = await asyncio.to_thread(self._queries.fixed)
            if not diagnostic:
                self._fixed = scope
            return scope
        if await asyncio.to_thread(self._queries.denied):
            return Denied()
        facts = _snapshot(await self._loader())
        return await asyncio.to_thread(self._queries.scope, facts)

    async def partial(self) -> ReadPlan:
        """Inspect one fresh operation's plan, without issuing row SQL."""
        scope = await self._scope(diagnostic=True)
        return scope if isinstance(scope, Denied) else scope.candidates

    async def _read(self, stmt: Select[tuple[T]], want: int) -> list[T]:
        scope = await self._scope()
        if isinstance(scope, Denied):
            return []
        scan = _Scan(scope, want)
        async with AsyncSession(self._engine, autoflush=False) as session:
            rows = await session.stream_scalars(
                stmt.where(scope.candidates.candidate_predicate)
            )
            try:
                async for row in rows:
                    check = scan.check(row)
                    if scan.keep(row, allowed=await asyncio.to_thread(check.allowed)):
                        break
            finally:
                await rows.close()
        return scan.found

    async def get(self, id_: str) -> T | None:
        """Await a detached authorized row, or None for missing or denied."""
        stmt = await asyncio.to_thread(self._queries.lookup, id_)
        if stmt is None:
            return None
        rows = await self._read(stmt, 1)
        return rows[0] if rows else None

    async def page(self, *, limit: int, after: str | None = None) -> Page[T]:
        """Await up to limit visible rows after the exclusive string cursor."""
        return _page(
            await self._read(self._queries.window(limit, after), limit + 1), limit
        )
