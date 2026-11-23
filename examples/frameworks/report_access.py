"""Application-owned lookups for the report export examples."""

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from cedarpy_web import Facts, Permission, Session

POLICY_DIR = Path(__file__).resolve().parents[2] / "packages/web/examples"
export_permission = Permission.from_files(
    action="export",
    service="reports",
    policies=POLICY_DIR / "reports.cedar",
    schema=POLICY_DIR / "reports.cedarschema",
)


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


def export_facts(
    can_export: Callable[[str], bool], is_stepped_up: Callable[[Session], bool]
) -> Callable[[Session], Facts]:
    def load_facts(session: Session) -> Facts:
        return Facts(
            principal_attrs={"can_export": can_export(session.user_id)},
            context={"stepped_up": is_stepped_up(session)},
        )

    return load_facts
