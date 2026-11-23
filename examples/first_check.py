# /// script
# requires-python = ">=3.10"
# dependencies = ["cedarpy==4.12.2"]
# ///
"""Run: uv run examples/first_check.py"""

from pathlib import Path

import cedarpy

policy_file = Path(__file__).with_name("first_check.cedar")
policies = cedarpy.PolicySet.from_str(policy_file.read_text(encoding="utf-8"))

for user in ("alice", "bob"):
    result = cedarpy.is_authorized(
        {
            "principal": {"type": "User", "id": user},
            "action": {"type": "Action", "id": "read"},
            "resource": {"type": "Document", "id": "notes"},
            "context": {},
        },
        policies,
        [],
    )
    print(
        user,
        "allowed" if result.allowed and not result.diagnostics.errors else "denied",
    )
