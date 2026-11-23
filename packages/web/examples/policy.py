from pathlib import Path

import cedarpy_web

SCHEMA = Path(__file__).with_name("reports.cedarschema").read_text(encoding="utf-8")
POLICIES = Path(__file__).with_name("reports.cedar").read_text(encoding="utf-8")


def report_export() -> cedarpy_web.Permission:
    return cedarpy_web.Permission(
        action="export", service="reports", schema=SCHEMA, policies=POLICIES
    )
