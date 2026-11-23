from cedarpy_policy import policy

from examples.typed_policy.domain import DocumentState
from examples.typed_policy.generated import read_document

principal = read_document.principal
document = read_document.resource
sealed = document.state == DocumentState.SEALED
owner_or_public = (document.owner == principal) | (
    document.state == DocumentState.PUBLIC
)

read = policy(
    read_document,
    permit_when=owner_or_public & ~sealed,
    forbid_when=sealed,
)
