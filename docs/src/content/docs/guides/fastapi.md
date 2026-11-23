---
title: Require a Cedar permission on a FastAPI route
---

Keep your existing FastAPI app and authentication dependency. Add one permission check to the route that starts an export.

```sh
uv add 'cedarpy-integrations[fastapi]'
```

## Protect the route

Here `current_session` is your app's FastAPI dependency. It rejects unauthenticated requests and returns a `cedarpy_web.Session` with the verified user and session IDs. `export_facts` reads the facts for that session. The route itself needs neither of them.

```python title="routes.py"
from cedarpy_asgi.fastapi import require_authorization
from fastapi import APIRouter, Depends, Response

from .authentication import current_session
from .report_access import export_permission
from .report_facts import export_facts

router = APIRouter()
require_export = require_authorization(
    export_permission, identity=current_session, load_facts=export_facts
)

@router.post("/exports", dependencies=[Depends(require_export)])
def export_reports() -> Response:
    return Response("report,total\nsales,42\n", media_type="text/csv")
```

Register the router with `app.include_router(router)` as usual. If you have a token verifier instead of a FastAPI dependency, use `identity=bearer_session(verify_token)` from `cedarpy_asgi.fastapi`. The verifier must return `None` if it cannot confirm the token. The bearer helper then returns `401`.

## Supply the two facts

The app owns these lookups. In this example both use async clients, so the loader awaits them. The first checks a user grant. The second checks whether this particular session still meets the extra authentication requirement. A check on a laptop must not grant access on a phone.

```python title="report_facts.py"
from cedarpy_web import Facts, Session

from .authentication import has_current_step_up
from .entitlements import can_export

async def export_facts(session: Session) -> Facts:
    return Facts(
        principal_attrs={"can_export": await can_export(session.user_id)},
        context={"stepped_up": await has_current_step_up(session.user_id, session.session_id)},
    )
```

Read both facts on each request. Use trusted lookups that return `False` if they cannot confirm a grant, including on timeout, expiry, or revocation. Do not take either value from request data. The [example identity adapter](https://github.com/h0rv/cedarpy-integrations/blob/main/examples/frameworks/report_identity.py) shows how to check both IDs in a service reply and use a synchronous database without blocking the event loop.

## Define the export permission

Load the policy and schema once. Cedar returns a denial if either fact is false. The dependency turns that denial into `403` before the route runs. Permission to start the export does not grant access to its rows.

```python title="report_access.py"
from pathlib import Path

from cedarpy_web import Permission

here = Path(__file__).parent
export_permission = Permission.from_files(
    action="export",
    service="reports",
    policies=here / "reports.cedar",
    schema=here / "reports.cedarschema",
)
```

```cedar title="reports.cedar"
permit(principal, action == Action::"export", resource == Service::"reports")
when { principal.can_export && context.stepped_up };

forbid(principal, action == Action::"export", resource)
unless { context.stepped_up };
```

```cedarschema title="reports.cedarschema"
entity User { can_export: Bool };
entity Service;
action "export" appliesTo {
    principal: [User],
    resource: [Service],
    context: { stepped_up: Bool }
};
```
