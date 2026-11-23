import sqlite3
from contextlib import closing

import pytest

from examples.frameworks.report_access import ExportEntitlements, SessionStore


@pytest.fixture
def reports_db(tmp_path):
    path = tmp_path / "reports.sqlite3"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY, can_export INTEGER);
            INSERT INTO users VALUES ('alice', 1), ('bob', 1);
            CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, expires_at INTEGER, step_up_until INTEGER);
            INSERT INTO sessions VALUES ('verified', 'alice', unixepoch()+600, unixepoch()+300);
            INSERT INTO sessions VALUES ('other', 'alice', unixepoch()+600, 0);
        """)
        yield path, db


@pytest.fixture
def lookups(reports_db):
    path, _ = reports_db
    return {
        "can_export": ExportEntitlements(path).can_export,
        "is_stepped_up": SessionStore(path).is_stepped_up,
    }
