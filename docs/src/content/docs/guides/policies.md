---
title: Share a typed policy in Python
---

Define a Cedar policy expression in Python and import it wherever you need the same rule. The `cedarpy_policy` module does not load data or make access decisions. Your application still supplies concrete facts to Cedar.

```sh
uv add cedarpy-integrations
```

## Use your domain enum

The application owns this enum. There is no second `DocumentState` for authorization:

```python
from enum import StrEnum


class DocumentState(StrEnum):
    DRAFT = "draft"
    PUBLIC = "public"
    SEALED = "sealed"
```

In `documents.py`, compare the resource field to an enum member. Cedar receives the member's value, `"sealed"`, not its Python name, `"SEALED"`.

```python
from cedarpy_policy import policy

from examples.typed_policy.domain import DocumentState
from examples.typed_policy.generated import read_document

document = read_document.resource
principal = read_document.principal
sealed = document.state == DocumentState.SEALED
visible = (document.owner == principal) | (document.state == DocumentState.PUBLIC)

read = policy(
    read_document,
    permit_when=visible & ~sealed,
    forbid_when=sealed,
)
```

Alice may read her own draft or Bob's public document. She cannot read a sealed document, even her own. `read` is a `cedarpy.PolicySet`. It describes rules but does not return an access decision. Use `|`, `&`, and `~` to compose Cedar expressions. Python's `or`, `and`, and `not` cannot combine these expressions.

## Generate typed references

`examples/typed_policy/generate.py` reads the example Cedar schemas and writes Python members for the action shapes used by that example. It binds `Document.state` to the application's enum explicitly because a Cedar `String` field does not name a Python enum. A type checker can catch misspelled attributes and enum members. This generator supports the example schemas. It is not a general Cedar schema compiler.

## Reuse the policy for row reads

Declare the column with the same enum you used in the policy:

```python
from cedarpy_sqlalchemy import attr, enum_type

# On the mapped class:
state: Mapped[DocumentState] = mapped_column(enum_type(DocumentState), info=attr())
```

`enum_type(DocumentState)` stores `"sealed"` as text and returns a `DocumentState` member on the row. `attr()` exposes the mapped field name `state` to Cedar. Use `attr("visibility")` to expose it under a different name. SQLAlchemy still owns `mapped_column()`, so options such as `index=True` work as usual.

If your base already configures the same enum storage, `mapped_column(info=attr())` is enough. Storage alone doesn't expose a field to Cedar or migrate an existing column.

Pass the imported policy to a [SQLAlchemy store](../sqlalchemy/) instead of a `.cedar` path. Keep the mapped columns and omit model-local `cedar_rules`. Use the schema that describes those facts:

```python
from pathlib import Path

from cedarpy_sqlalchemy import Store
from examples.typed_policy import documents

store = Store(
    engine, Document,
    policies=documents.read,
    schema=Path("documents.cedarschema"),
)
```

`store.for_user(user_id).get(...)` and `.page(...)` both use that policy. A CLI can pass the same policy to `cedarpy.is_authorized` directly.

## Keep operation permissions separate

In `reports.py`, the request to start an export uses a different action. It needs two booleans, not a document row:

```python
from cedarpy_policy import policy
from examples.typed_policy.generated import start_export as export

stepped_up = export.context.stepped_up

start_export = policy(
    export,
    permit_when=export.principal.can_export & stepped_up,
    forbid_when=~stepped_up,
)
```

The permit requires a known, active step-up. If the fact is missing, the permit cannot grant the export. The separate forbid overrides any other permit when step-up is known to be false. This distinction matters because [native Cedar skips a policy that errors](https://docs.cedarpolicy.com/auth/authorization.html); it does not treat an error as a matching forbid.

Bind it once and reuse the permission on the routes that start a reports export:

```python
from pathlib import Path

from cedarpy_web import Permission
from examples.typed_policy import reports

require_export = Permission(
    action="export", service="reports",
    policies=reports.start_export,
    schema=Path("reports.cedarschema"),
)
```

The [web integration](../fastapi/) still supplies the authenticated session and current facts. Starting the export does not grant access to its rows. Both adapters validate policies against the schema at startup. If you prefer to author the rules in `.cedar` files, the file APIs are unchanged.
