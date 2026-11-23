# /// script
# requires-python = ">=3.13"
# dependencies = ["cedarpy==4.12.2", "cedarpy-integrations==0.1.0a0"]
# ///
"""A single owner-read policy, authored in Python and evaluated by Cedar."""

import cedarpy
from cedarpy import pst
from cedarpy_policy import nodes

owner = nodes.field(nodes.resource, "owner")
owner_read = nodes.permit(
    id="owner-read",
    principal=nodes.entity_is("User"),
    action=nodes.action_is("read"),
    resource=nodes.entity_is("Document"),
    clauses=(pst.When(nodes.eq(owner, nodes.principal)),),
    annotations={},
)
policies = cedarpy.PolicySet.from_pst(
    pst.PolicySet(
        templates={}, static_policies={owner_read.id: owner_read}, template_links=()
    )
)

if __name__ == "__main__":
    doc = {"type": "Document", "id": "notes"}
    alice = {"type": "User", "id": "alice"}
    entities = [{"uid": doc, "attrs": {"owner": {"__entity": alice}}, "parents": []}]
    for user in ("alice", "bob"):
        result = cedarpy.is_authorized(
            {
                "principal": {"type": "User", "id": user},
                "action": {"type": "Action", "id": "read"},
                "resource": doc,
                "context": {},
            },
            policies,
            entities,
        )
        if result.diagnostics.errors:
            raise RuntimeError(result.diagnostics.errors)
        print(user, "allowed" if result.allowed else "denied")
