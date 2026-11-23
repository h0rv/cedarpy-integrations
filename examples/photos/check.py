# /// script
# dependencies = ["cedarpy>=4.12.2"]
# ///
"""Run: uv run examples/photos/check.py"""

from pathlib import Path

import cedarpy

POLICIES = Path(__file__).with_name("view.cedar").read_text(encoding="utf-8")
SCHEMA = Path(__file__).with_name("photos.cedarschema").read_text(encoding="utf-8")


def can_view(user: str, photo_id: str, owner: str, visibility: str) -> bool:
    photo = {"type": "Photo", "id": photo_id}
    result = cedarpy.is_authorized(
        {
            "principal": {"type": "User", "id": user},
            "action": {"type": "Action", "id": "view"},
            "resource": photo,
            "context": {},
        },
        POLICIES,
        [
            {
                "uid": photo,
                "parents": [],
                "attrs": {
                    "owner": {"__entity": {"type": "User", "id": owner}},
                    "visibility": visibility,
                },
            }
        ],
        SCHEMA,
    )
    if result.diagnostics.errors:
        raise ValueError(result.diagnostics.errors)
    return result.allowed


if __name__ == "__main__":
    for user in ("alice", "bob"):
        print(user, "allowed" if can_view(user, "1", "alice", "private") else "denied")
