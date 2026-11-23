---
title: Protect a Flask report export
---

The WSGI adapter checks permission before Flask chooses a route. Register the export blueprint on a dedicated Flask app so unrelated routes do not require export access.

```sh
uv add flask cedarpy-integrations
```

## Supply the two facts

Start with [the export policy, schema, and `Permission.from_files` call](../fastapi/#define-the-export-permission) in `report_access.py`. `can_export` looks up a grant for the verified user. `is_stepped_up` checks whether that user's current session still meets the extra authentication requirement. The code that builds `Facts` needs only the outcomes, not database rows.

```python title="report_access.py (continued)"
from collections.abc import Callable

from cedarpy_web import Facts, Session


def export_facts(
    can_export: Callable[[str], bool], is_stepped_up: Callable[[Session], bool]
) -> Callable[[Session], Facts]:
    def load_facts(session: Session) -> Facts:
        return Facts(
            principal_attrs={"can_export": can_export(session.user_id)},
            context={"stepped_up": is_stepped_up(session)},
        )

    return load_facts
```

## Read the stored values

These two lookups use SQLite. `users.id` and `sessions.id` are unique. Only the integer `1` grants export access. The authentication service stores both deadlines as integer Unix timestamps in seconds and deletes revoked sessions. Check both IDs before using either deadline. If a record is missing, malformed or unreadable, return `False`.

```python title="report_access.py (continued)"
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportEntitlements:
    database: Path

    def can_export(self, user_id: str) -> bool:
        try:
            with closing(sqlite3.connect(self.database)) as db:
                db.row_factory = sqlite3.Row
                user = db.execute(
                    "SELECT can_export FROM users WHERE id = ?", (user_id,)
                ).fetchone()
        except sqlite3.Error:
            return False
        if user is None:
            return False
        grant = user["can_export"]
        return type(grant) is int and grant == 1


@dataclass(frozen=True)
class SessionStore:
    database: Path

    def is_stepped_up(self, session: Session) -> bool:
        try:
            with closing(sqlite3.connect(self.database)) as db:
                db.row_factory = sqlite3.Row
                record = db.execute(
                    "SELECT expires_at, step_up_until FROM sessions WHERE user_id = ? AND id = ?",
                    (session.user_id, session.session_id),
                ).fetchone()
        except sqlite3.Error:
            return False
        if record is None:
            return False
        now = time.time()
        return all(
            type(deadline) is int and deadline > now
            for deadline in (record["expires_at"], record["step_up_until"])
        )
```

## Wrap the Flask app

Deploy the app behind a WSGI server that verifies the bearer token and sets `REMOTE_USER` and `cedar_web.session_id` in the WSGI environment for that session. Never copy these values from client headers. The adapter does not verify tokens itself.

```python title="reports_app.py"
import os
from pathlib import Path

from cedarpy_wsgi import require_authorization
from flask import Blueprint, Flask, Response

from .report_access import ExportEntitlements, SessionStore, export_facts, export_permission

reports = Blueprint("reports", __name__)


@reports.get("/export")
def export() -> Response:
    return Response("report,total\nsales,42\n", mimetype="text/csv")


database = Path(os.environ["REPORTS_DB"])
entitlements = ExportEntitlements(database)
sessions = SessionStore(database)
app = Flask(__name__, static_folder=None)
app.register_blueprint(reports)
app.wsgi_app = require_authorization(
    app.wsgi_app, export_permission,
    load_facts=export_facts(entitlements.can_export, sessions.is_stepped_up),
    challenge="Bearer",
)
```

Without a verified user and session, the guard returns `401`. With export access and a current extra check, `GET /export` returns the CSV. If access is revoked or the extra check expires, the next request gets `403` before Flask calls the view.
