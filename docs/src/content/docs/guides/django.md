---
title: Protect a Django report export
---

The WSGI adapter checks permission before Django chooses a view or sets `request.user`. Use a dedicated Django application for the export so other views do not require export access.

```sh
uv add django cedarpy-integrations
```

## Define the permission and its sources

In the `reports` package, save [the export policy and schema](../fastapi/#define-the-export-permission) beside `report_access.py`. Use the `Permission.from_files` call there to load both files at startup.

Use [the synchronous lookups and fact loader](../flask/#supply-the-two-facts) in `report_access.py`. `ExportEntitlements.can_export` checks the user's current export grant. `SessionStore.is_stepped_up` checks both the verified user ID and the session ID before reading the expiry times. An extra check in one session does not count in another, even for the same user. Both lookups return booleans, so the view and the permission code do not have to interpret database values.

## Route the export and wrap the WSGI application

In `reports/settings.py`, set `ROOT_URLCONF` to `"reports.urls"`. Register the export view in that URL configuration.

```python title="reports/urls.py"
from django.http import HttpRequest, HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe


@require_safe
def export(request: HttpRequest) -> HttpResponse:
    return HttpResponse("report,total\nsales,42\n", content_type="text/csv")


urlpatterns = [path("export", export)]
```

Supply the two bound methods when you wrap the WSGI application. The stores can share a database file. They do not share a cached answer.

```python title="reports/wsgi.py"
import os
from pathlib import Path

from cedarpy_wsgi import require_authorization
from django.core.wsgi import get_wsgi_application

from .report_access import ExportEntitlements, SessionStore, export_facts, export_permission

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reports.settings")
database = Path(os.environ["REPORTS_DB"])
entitlements = ExportEntitlements(database)
sessions = SessionStore(database)
application = require_authorization(
    get_wsgi_application(), export_permission,
    load_facts=export_facts(entitlements.can_export, sessions.is_stepped_up),
    challenge="Bearer",
)
```

Serve `reports.wsgi.application` behind a WSGI server that verifies the bearer token and sets `REMOTE_USER` and `cedar_web.session_id` in the WSGI environment for that session. The adapter does not verify tokens itself. Never copy identity values from client headers.

Without a verified user and session, the guard returns `401`. If both checks pass, `GET /export` returns the CSV. If a lookup fails or the session is revoked, the next request gets `403` before Django calls the view.
