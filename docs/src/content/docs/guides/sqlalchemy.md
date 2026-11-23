---
title: Read authorized rows with SQLAlchemy
---

Alice can read her own documents and anyone's public documents. A sealed document stays hidden, even from its owner. You can express that policy in either of two ways:

- [Declare it in Python on the model](#declare-the-policy-in-python) when your `read` rules compare row facts, such as an owner or a state. You don't need to write Cedar or maintain a separate schema.
- [Write the policy and schema in Cedar files](#write-the-policy-and-schema-in-cedar-files) when you already have Cedar policies, share them across services, or need other actions or session context.

Choose one for a given model. In both cases Cedar makes the decision, and the code that reads a document or a page is the same.

This guide describes the [SQLAlchemy source in this repository](https://github.com/h0rv/cedarpy-integrations/tree/main/packages/sqlalchemy/src/cedarpy_sqlalchemy). The reader is not included in the `cedarpy-integrations` distribution or its extras.

## Declare the policy in Python

In `documents.py`, use your application's SQLAlchemy base. The [mixin](https://docs.sqlalchemy.org/en/20/orm/declarative_mixins.html) adds no table or columns.

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cedarpy_sqlalchemy import (
    CedarAuthorizationMixin, Store, attr, forbid_if, permit_if, principal, ref,
)


class Base(DeclarativeBase):
    pass


class Document(Base, CedarAuthorizationMixin):
    __tablename__ = "documents"
    cedar_rules = (
        permit_if(owner=principal),
        permit_if(state="public"),
        forbid_if(state="sealed"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    state: Mapped[str] = mapped_column(info=attr("state"))
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
```

The marked columns supply the schema. `attr("state")` exposes a string. `ref("owner", "User")` exposes `owner_id="alice"` as the entity `User::"alice"`, so you can compare it to `principal`. The class name supplies the Cedar type `Document`, and the string primary key `id` supplies its ID. `title` is an ordinary mapped field. It is available on an authorized document as a `str`, but it isn't a policy input.

The store checks rule keywords such as `owner` against your mapped facts at startup. Your Python type checker checks `doc.title`; it does not catch a misspelled keyword in `permit_if`. Either permit can allow the read, but the forbid wins if the document is sealed. To require two facts together, put them in one rule, such as `permit_if(owner=principal, state="draft")`.

At startup, pass your existing SQLAlchemy engine and model to `Store`. It derives the schema and compiles and validates the policy:

```python
store = Store(engine, Document)
```

## Write the policy and schema in Cedar files

For this version, `documents.py` exposes the same row facts but has **no `cedar_rules`**:

```python
from pathlib import Path

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cedarpy_sqlalchemy import CedarAuthorizationMixin, Store, attr, ref


class Base(DeclarativeBase):
    pass


class Document(Base, CedarAuthorizationMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    state: Mapped[str] = mapped_column(info=attr("state"))
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
```

Beside `documents.py`, put the permissions in **`documents.cedar`**:

```cedar
permit(principal is User, action == Action::"read", resource is Document)
when { resource.owner == principal || resource.state == "public" };

forbid(principal is User, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
```

Put the types of those facts and the scope of the `read` action in **`documents.cedarschema`**:

```cedarschema
entity User;
entity Document = { state: String, owner: User };
action "read" appliesTo { principal: [User], resource: [Document] };
```

Load both files at startup in `documents.py`:

```python
here = Path(__file__).parent
store = Store(
    engine, Document,
    policies=here / "documents.cedar",
    schema=here / "documents.cedarschema",
)
```

Pass `Path` objects for files or strings for inline Cedar source. The store reads files once at construction, parses the schema, checks the mapped facts, and validates the policy against the schema before any reads. It rejects external policy or schema text if the model also declares rules, so a file cannot silently replace a forbid.

## Read with either policy

### Open one document

Alice owns the contract, but it is sealed. Use Alice's verified user ID to look it up:

```python
alice = store.for_user("alice")

contract = alice.get("sealed-contract")
```

`contract` is `None`, just as it would be if the document didn't exist.

### List visible documents

```python
page = alice.page(limit=25)
```

`page.items` contains Alice's draft proposal and Bob's public handbook. The sealed contract is absent. If `page.next_cursor` isn't `None`, pass it as `after` to read the next page.

## Keep the full SQLAlchemy API

Keep your existing `Engine` or `AsyncEngine`. A store is a companion for one model and action, not an engine or session replacement. Construct it once. It reuses the engine's pool. On a read that needs the database, the reader opens and closes its own session and returns detached instances of your mapped class, not wrapper objects.

For example, here is the async setup for model rules. Use your existing engine if you already have one:

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cedarpy_sqlalchemy import AsyncStore

engine = create_async_engine("sqlite+aiosqlite:///documents.db")
documents = AsyncStore(engine, Document)
sessions = async_sessionmaker(documents.engine)  # The same AsyncEngine as `engine`.


async def read_title(user_id: str, document_id: str) -> str | None:
    doc = await documents.for_user(user_id).get(document_id)  # Document | None
    return doc.title if doc is not None else None
```

Use `sessions` or `engine` for ordinary SQLAlchemy operations, including transactions, joins, and writes. They don't apply the reader's policy. With a sync engine, `Store(engine, Document).engine` likewise returns the original `Engine`. Your application still owns engine disposal. The reader does not join a caller's open transaction.

A denied row looks like a missing row. A cursor marks a position, not a grant. SQL narrows the candidates; Cedar checks each returned row. Neither policy form protects writes, raw SQL, or unrelated sessions, and neither redacts columns.

## Supply session context from an identity service

The document database supplies `resource.owner` and `resource.state`. It need not know whether the caller recently completed step-up authentication. For example, a document service can ask its identity service whether step-up is still active for **this user and this session**. A database-backed session store can answer the same question. Neither source changes the Cedar policy.

For an export that requires step-up, use the file-based model above (no `cedar_rules`). Give the `export` action its own **`export.cedarschema`**:

```cedarschema
entity User;
entity Document = { state: String, owner: User };
action "export" appliesTo {
    principal: [User], resource: [Document], context: { stepped_up: Bool }
};
```

In **`export.cedar`**, keep the row rules and add the session requirement. Completing step-up alone doesn't grant any documents:

```cedar
permit(principal is User, action == Action::"export", resource is Document)
when { resource.owner == principal || resource.state == "public" };

forbid(principal, action == Action::"export", resource is Document)
when { resource.state == "sealed" };

forbid(principal, action == Action::"export", resource is Document)
unless { context.stepped_up };
```

At startup, bind a separate store for this action:

```python
exports = AsyncStore(
    engine, Document, action="export",
    policies=here / "export.cedar", schema=here / "export.cedarschema",
)
```

The application supplies the lookup. Here `step_up_active` is a typed, async function passed by the caller. It can be an authenticated identity-service client's method or a query against a session database. Pass the user and session IDs from authentication, not from the request body:

```python
from collections.abc import Awaitable, Callable

from cedarpy_sqlalchemy import Page


async def export_page(
    user_id: str,
    session_id: str,
    step_up_active: Callable[[str, str], Awaitable[bool]],
    after: str | None = None,
) -> Page[Document]:
    async def load_context() -> dict[str, bool]:
        active = await step_up_active(user_id, session_id)
        return {"stepped_up": active}

    reader = exports.for_user(user_id, load_context=load_context)
    return await reader.page(limit=25, after=after)
```

The source must check expiry and revocation and return a real boolean. Keep decoding database values or validating HTTP responses inside that source. If a call times out or returns malformed data, raise an error rather than assuming step-up. The reader loads fresh context once per `get()` or `page()` when needed, not once per row. A later page checks again. A sync `Store` accepts a regular function that returns the same mapping.

The Python `permit_if` and `forbid_if` model rules compare row facts for `read`. They don't express `context.stepped_up`; use the Cedar files for this case. A separate HTTP check may decide whether the caller can *start* an export. It doesn't authorize the rows in it.

If your column already uses SQLAlchemy's [info dictionary](https://docs.sqlalchemy.org/en/20/core/metadata.html#sqlalchemy.schema.SchemaItem.info), keep your keys alongside the Cedar entry: `info={"label": "State", **attr("state")}`.
