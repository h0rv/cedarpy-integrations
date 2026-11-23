# Shared app policies

Import `documents.read` or `reports.start_export` from `examples.typed_policy`. Each value is a `cedarpy.PolicySet`. You can pass it directly to `cedarpy.is_authorized`.

| Policy | Action | Principal | Resource | Schema |
| --- | --- | --- | --- | --- |
| `documents.read` | `read` | `User` | Any `Document` | `documents.schema.json` |
| `reports.start_export` | `export` | `User` | Only the `Service` with ID `reports` | `reports.schema.json` |

A document owner can read their draft. Anyone can read a public document. Nobody can read a sealed document. The read policy needs no attributes on the requesting user. An export requires both `principal.can_export` and `context.stepped_up`.

Pass the matching schema to `cedarpy.is_authorized` to check that required facts are present and have the right types. The permit rules check state and step up directly because Cedar skips a forbid rule if evaluating it produces an error. The forbid rules still override other matching permits.

Read `documents.py` and `reports.py` for the rules. `generated.py` contains references to the fields those rules use. Cedar declares `Document.state` as a string. The generator binds that specific field to `domain.DocumentState`. The enum values belong to the app, not the schema.

Run these commands from the checkout root with Python 3.13 or later:

```sh
# Create the project environment before the first run.
uv sync

# Regenerate references after editing a schema or binding.
.venv/bin/python -m examples.typed_policy.generate > examples/typed_policy/generated.py

# Check the committed references without a build or network access.
scripts/test-typed-policy --check-generated

# Build the local package, check types and compare decisions with the .cedar fixtures.
scripts/test-typed-policy
```
