# Shared Cedar policies in Python

On Python 3.13 or later, install the base distribution:

```sh
uv add cedarpy-integrations
```

Keep domain permissions in ordinary Python modules. Use your application's existing enum rather than copying state strings into rules:

```python
from cedarpy_policy import policy

from myapp.domain import DocumentState
from myapp.authz import read_document

resource = read_document.resource
sealed = resource.state == DocumentState.SEALED
owner_or_public = (resource.owner == read_document.principal) | (
    resource.state == DocumentState.PUBLIC
)

read = policy(
    read_document,
    permit_when=owner_or_public & ~sealed,
    forbid_when=sealed,
)
```

`read` is a `cedarpy.PolicySet`. Import it in a CLI, a worker, or a SQLAlchemy store. The package does not import an ORM, a web framework, or your models. The policy describes facts but never fetches them.

`read_document` is an application-defined typed reference for a particular action, principal, and resource. The [worked example](../../examples/typed_policy/) generates the references for two action shapes. It binds a Cedar `String` field to the app's `StrEnum` explicitly; a Cedar string schema cannot tell you which enum class to use. This is not a general schema compiler. The builder uses unqualified type names and one action ID. Combine symbolic conditions with `&`, `|`, and `~`, not Python's `and`, `or`, and `not`.

If you are building a syntax tree directly, use the lower-level `nodes` module to name Cedar operations without string tags:

```python
from cedarpy_policy import nodes

can_export = nodes.field(nodes.principal, "can_export")
stepped_up = nodes.field(nodes.context, "stepped_up")
condition = nodes.and_(can_export, stepped_up)
```

`condition` is a native `cedarpy.pst.BinaryOp`, not a Python boolean or a domain `Condition`. The constructor checks in a type checker that its operands are expressions. It cannot tell that the application fields are booleans: Cedar validates that against the schema. Use generated domain references when you want editor checks on field names and enum members.

Validate the policy against your Cedar schema and pass that schema when you authorize requests. Cedar skips policies that produce evaluation errors, including forbid rules. A generated reference does not check the facts in a request or turn a Cedar string field into an enum. Keep using `.cedar` and `.cedarschema` where sharing text is simpler.
