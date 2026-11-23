# Cedar reads for SQLAlchemy 2

The `cedarpy_sqlalchemy` reader is available only as [source in this checkout](src/cedarpy_sqlalchemy/). It is not part of the `cedarpy-integrations` distribution or its extras.

Use a reader when a handler or background job needs the rows an actor may read. Keep using your SQLAlchemy engine and sessions. `store.engine` returns the original `Engine`; `async_store.engine` returns the original `AsyncEngine`. Both expose the full native API, with no method forwarding. Only `store.for_user(...).get()` and `.page()` return Cedar-checked rows. These reads use a separate session and return detached instances of your model. Direct SQL, ORM queries on your own sessions, and writes are unchanged and unchecked.

Mark the columns Cedar may use. `ref` means that the value identifies a particular type of entity. It is not a parent relationship or a grant of access.

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
    state: Mapped[str] = mapped_column(info=attr("state"))
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
```

`Store(engine, Document)` derives the schema from the marked columns and compiles the three read rules into Cedar at startup. The mixin adds no registry or columns. To use a shared Cedar file instead, omit `cedar_rules`. The equivalent policy is:

```cedar
permit(principal, action == Action::"read", resource is Document)
when { resource.owner == principal || resource.state == "public" };
forbid(principal, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
```

For file-based policies, pass `Path` objects to read, parse and validate both files at startup. Plain strings mean Cedar source, not filenames. Create `cedarpy_sqlalchemy.Store(engine, Document, policies=source, schema=schema)` for a normal SQLAlchemy engine, or `cedarpy_sqlalchemy.AsyncStore(async_engine, Document, policies=source, schema=schema)` for an async engine. Both stores use `Action::"read"` by default. If exports have different rules, create a separate store with `action="export"`. Choose the action in trusted application code, not from request input. Cedar checks at startup that the action applies to `User` and the mapped resource type. Pass the authenticated ID explicitly; a job need not manufacture an HTTP request.

```python
reader = store.for_user(actor_id)
page = reader.page(limit=25, after=cursor)
doc = reader.get(document_id)  # None for either a missing or a denied row.

reader = async_store.for_user(actor_id)
page = await reader.page(limit=25, after=cursor)
doc = await reader.get(document_id)
```

`page.items` contains only verified rows. `next_cursor` is the last returned ID if another authorized row exists; otherwise it is `None`. A scan limit bounds candidate verification, not the database's internal work. For keyset reads, index the ordering used by the reader: `CREATE INDEX documents_cursor ON documents (id COLLATE "C")` on Postgres, or `CREATE INDEX documents_cursor ON documents (id COLLATE BINARY)` on SQLite if the primary key uses a different collation. Check the query plan with real data. A scan limit is not a page size. If the reader cannot determine a complete page within its budget it raises `ScanLimitExceeded`, not a short, misleading page.

### Session facts and typed partial reads

Row facts come from mapped columns. Session facts can come from another database or an authenticated identity-service call. [export.cedar](examples/export.cedar) and [export.cedarschema](examples/export.cedarschema) require active step-up in addition to the row policy. Bind those paths to an `AsyncStore` with `action="export"`. Here `verified` comes from authentication, and `step_ups.active` checks the user and session together, including expiry and revocation:

```python
async def load_context() -> dict[str, bool]:
    return {"stepped_up": await step_ups.active(verified.user_id, verified.session_id)}


docs = async_store.for_user(verified.user_id, load_context=load_context)
page = await docs.page(limit=25)
```

For sync code, pass a regular function instead. A definite denial needs no document query. If Cedar can deny before knowing the session facts, the reader skips their loader too. Otherwise it obtains one snapshot for the operation and reuses it for planning and concrete checks. Each subsequent operation loads fresh facts; this is not a cross-request MFA cache. A failed lookup must not be converted into an affirmative result.

Most handlers need only `get()` and `page()`. For inspection, `reader.partial()` (or `await async_reader.partial()`) returns `Denied | Candidates`. The latter carries typed `cedarpy.pst.Template` residuals, the IDs of permits widened for unsupported SQL, and a SQLAlchemy `ColumnElement[bool]` named `candidate_predicate`. That predicate is not a grant. Inspecting a partial does not authorize a future read or freeze its session facts.

### Why not just return a Select?

For a list, Cedar knows the user and action before it knows which document will be read. It returns conditions that still depend on the document. SQL narrows the candidates; Cedar decides on the actual rows. A condition outside the SQL subset can admit extra permit candidates, but never unchecked results. A relevant forbid the adapter cannot translate raises `UnsupportedForbid`. The reader does not offer authorized counts, aggregates, writes, arbitrary joins, or unrestricted relationship loading.

The reader supports flat resources with required string attributes, fixed-type UID references, the `User` principal, one action per store and scalar context fields (string, boolean, integer). It assumes that model declarations match the database DDL. Data changing between pages can change visibility. Use `scripts/test-postgres` from the project root to exercise both drivers against the same policies and records.

### CI checks

Call these functions from a test or a CI script. Both return `None` on success and raise on failure. Neither needs a database connection or a pytest plugin.

```python
import cedarpy_sqlalchemy.checks

# Import every module that declares tables before checking the inventory.
from myapp.models import Document, document_tags, metadata
from myapp.policy import schema_text

cedarpy_sqlalchemy.checks.check_resource_schema(Document, schema_text)
cedarpy_sqlalchemy.checks.check_table_coverage(
    metadata,
    protected=[Document],
    exemptions={document_tags: "Used only to link documents to tags."},
)
```

`check_resource_schema` uses the reader's projection rules. It checks a sample resource and an empty `User` against the Cedar schema text. It does not check stored values, policies or which actions apply.

`check_table_coverage` checks every table currently registered in the supplied `MetaData`, including association tables and tables with no ORM model. List each table once, either through a mapped `CedarAuthorizationMixin` subclass or as a `Table` object with a nonblank exemption reason. A table with the same name from another `MetaData` does not count. An empty inventory is an error.

If the app uses several `MetaData` objects, call the function once for each, with its own models and exemptions. The check cannot find tables from modules you forgot to import. It does not inspect the live database. To include tables discovered by reflection, call `metadata.reflect(bind=engine)` on the model's metadata first. Tables outside the schemas or filters you reflected are still out of scope unless declared separately.

Listing a model as protected does not prove that callers use a reader or enforce a policy on other queries.

For the planner's dependency provenance and release checks, see [release verification](../../RELEASE.md).
