# /// script
# requires-python = ">=3.13"
# dependencies = ["cedarpy-integrations==0.1.0a0", "cedarpy==4.12.2"]
# ///
"""Can Alice read a document she owns after she seals it?"""

from enum import StrEnum

import cedarpy
from cedarpy_policy import Scope, entity_field, entity_principal, enum_field, policy


class DocumentState(StrEnum):
    DRAFT = "draft"
    PUBLIC = "public"
    SEALED = "sealed"


class ReadDocument:
    scope = Scope("read", "User", "Document")
    owner = entity_field(scope, "owner", "User")
    state = enum_field(scope, "state", DocumentState)
    principal = entity_principal(scope)


read_document = ReadDocument()
sealed = read_document.state == DocumentState.SEALED
owner_or_public = (read_document.owner == read_document.principal) | (
    read_document.state == DocumentState.PUBLIC
)
read = policy(read_document, permit_when=owner_or_public & ~sealed, forbid_when=sealed)


if __name__ == "__main__":
    print(cedarpy.format_policies(str(read)))
    alice = {"type": "User", "id": "alice"}
    notes = {"type": "Document", "id": "notes"}
    request = {
        "principal": alice,
        "action": {"type": "Action", "id": "read"},
        "resource": notes,
        "context": {},
    }
    for state in (DocumentState.DRAFT, DocumentState.SEALED):
        facts = {"state": state.value, "owner": {"__entity": alice}}
        entities = [{"uid": notes, "attrs": facts, "parents": []}]
        result = cedarpy.is_authorized(request, read, entities)
        if result.diagnostics.errors:
            raise RuntimeError(result.diagnostics.errors)
        decision = "allow" if result.allowed else "deny"
        print(f"Alice reads her own {state.value} document: {decision}")
