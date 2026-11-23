# Cedar web permissions

Both adapters provide `require_authorization()` to check a Cedar permission before calling the protected HTTP handler. On Python 3.13 or later, use `uv add cedarpy-integrations` for WSGI or `uv add 'cedarpy-integrations[asgi]'` for ASGI. For FastAPI route dependencies, use `uv add 'cedarpy-integrations[fastapi]'`.

Both adapters use `cedarpy_web` for permissions and session facts. WSGI does not require Starlette, AnyIO, or FastAPI.

The [report policy](examples/reports.cedar) permits export for `principal.can_export` and forbids it unless `context.stepped_up` is true. Its [Cedar schema](examples/reports.cedarschema) requires both fields to be Boolean. Make security facts required even if a policy uses `has`. Otherwise a missing field could turn off a forbid.

### Check the permission at startup

Build the permission once when you assemble the app. Pass Cedar source text rather than parsed handles:

```python
import cedarpy_web

permission = cedarpy_web.Permission(
    action="export", service="reports", schema=schema_text, policies=policy_text
)
```

Construction raises `ValueError` for invalid Cedar syntax, policies that do not type check against the schema, or an incompatible mount. The action must apply to a `User` and a `Service`. The configured service must satisfy the schema with no attributes or parents. Use an enumerated `Service` type if only specific service IDs are valid. With a regular entity type, Cedar cannot tell whether a service ID is a typo. A valid permission need not grant anyone access.

At startup the guard's request shape is checked with `User::"probe"`, the exact action and service IDs, no policies and unknown context. No session or facts are loaded. Use an ordinary `User` type, or include `"probe"` if `User` is enumerated. Action and service IDs must be nonblank and accepted by cedarpy's partial evaluator as JSON-quoted text UIDs. For example, quotes and backslashes work, but a configured ID containing NUL is rejected. IDs are not trimmed.

Both guards reuse the parsed policy set and schema. Request facts still have to pass the schema check on each full decision.

### Load facts for the authenticated session

Bind a loader to the operation at mount time. It takes a `Session(user_id, session_id)` and returns `Facts` or `None`. For example, read one active session from a trusted export table or cache:

```python
import cedarpy_web


async def load_export(session: cedarpy_web.Session) -> cedarpy_web.Facts | None:
    row = await exports.get_active(session.user_id, session.session_id)
    if row is None:
        return None
    return cedarpy_web.Facts(
        principal_attrs={"can_export": row.can_export},
        context={"stepped_up": row.stepped_up},
    )
```

`Facts` takes a read-only snapshot of both mappings at construction. Keys must be strings and values must be strings, integers or booleans. Later changes to the source mappings cannot affect the decision.

Use the same lookup synchronously in WSGI. Look up **both IDs**. Step-up belongs to the session, not the user. The source must check session revocation, session expiry and step-up expiry at lookup time. The guards do not cache decisions or facts between requests. If your source is a cache, its expiry and invalidation determine how soon revocation takes effect. A decision covers this invocation, not a later background job.

### Mount the middleware

```python
import cedarpy_wsgi

app = cedarpy_wsgi.require_authorization(
    export_app,
    permission,
    load_facts=load_export_sync,
    challenge='Basic realm="reports"',
)

```

For ASGI, wrap the mounted app:

```python
from starlette.routing import Mount

import cedarpy_asgi

route = Mount(
    "/exports",
    app=cedarpy_asgi.require_authorization(
        export_app,
        permission,
        identity=identity,
        load_facts=load_export,
        challenge="Bearer",
    ),
)
```

Both guards check the permission, app and callbacks when you mount them. `challenge` must be a nonempty `WWW-Authenticate` header value that fits in Latin-1, without leading or trailing whitespace, line breaks or other forbidden control bytes. Supply the authentication scheme your server actually uses. The guards do not parse scheme parameters or invoke callbacks at startup.

The [WSGI guard example](examples/wsgi_reports.py) expects outer authentication to set `REMOTE_USER` and `environ["cedar_web.session_id"]` for the same verified session. The [ASGI example](examples/asgi_reports.py) reads the authenticated user and session ID from server scope. Never copy raw headers or cookies into these fields. Neither guard takes an action or step-up flag from the client. ASGI awaits both callbacks, runs the Cedar checks in worker threads, passes lifespan through, and closes WebSockets with code 1008.

| Outcome | What runs |
| --- | --- |
| User or authenticated session ID missing | 401 with the configured challenge. No lookup or handler. |
| Partial Cedar check proves deny without errors | 403. No lookup or handler. Principal attributes and context are unknown, not empty. |
| Any other partial result, including allow | One facts lookup. A missing row gives 403. Otherwise Cedar checks the complete request against the schema. |
| Full deny | 403. The protected handler does not run. |
| Full allow without errors | The handler runs and its response passes through unchanged. |
| Source failure, invalid facts, or full evaluation error | The exception reaches the server error handler. The protected handler does not run. |

See the [FastAPI](../../docs/src/content/docs/guides/fastapi.md), [Flask](../../docs/src/content/docs/guides/flask.md), and [Django](../../docs/src/content/docs/guides/django.md) tutorials for complete request examples.
