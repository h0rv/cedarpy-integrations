from cedarpy_policy import policy

from examples.typed_policy.generated import start_export as export

stepped_up = export.context.stepped_up

start_export = policy(
    export,
    permit_when=export.principal.can_export & stepped_up,
    forbid_when=~stepped_up,
)
