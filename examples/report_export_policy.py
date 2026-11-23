"""Build the reports export policy with typed Python nodes."""

from cedarpy import PolicySet, pst
from cedarpy_policy import nodes


def export_policy() -> PolicySet:
    action = nodes.action_is("export")
    reports = nodes.entity_is_id("Service", "reports")

    can_export = nodes.field(nodes.principal, "can_export")
    stepped_up = nodes.field(nodes.context, "stepped_up")

    permit = nodes.permit(
        id="export-reports",
        principal=pst.ScopeAny(),
        action=action,
        resource=reports,
        clauses=(pst.When(nodes.and_(can_export, stepped_up)),),
        annotations={},
    )
    forbid = nodes.forbid(
        id="require-step-up",
        principal=pst.ScopeAny(),
        action=action,
        resource=pst.ScopeAny(),
        clauses=(pst.Unless(stepped_up),),
        annotations={},
    )
    return PolicySet.from_pst(
        pst.PolicySet(
            templates={},
            static_policies={p.id: p for p in (permit, forbid)},
            template_links=(),
        )
    )


if __name__ == "__main__":
    print(export_policy())
