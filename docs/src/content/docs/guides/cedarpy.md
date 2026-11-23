---
title: Python bindings reference
---

The [quickstart](../../#first-check) shows the policy and Cedar's decision when the owner seals a document.

```sh
uv add cedarpy-integrations
```

For typed references to application fields and enum members, see [Shared Python policies](../policies/). For lower-level control, build the policy syntax tree directly as below.

## Express the export conditions in typed Python

The [FastAPI example](../fastapi/) loads `reports.cedar`. You can author the same two conditions with `cedarpy_policy.nodes` instead:

```python
from cedarpy import pst
from cedarpy_policy import nodes

can_export = nodes.field(nodes.principal, "can_export")
stepped_up = nodes.field(nodes.context, "stepped_up")

permit_when = pst.When(nodes.and_(can_export, stepped_up))
forbid_unless = pst.Unless(stepped_up)
```

`When` belongs to the permit for exporting reports. `Unless` belongs to the forbid for exports without an active step-up. These nodes describe facts; they don't fetch their values. The application can supply `can_export` from its entitlement database and `stepped_up` from its identity service.

`examples/report_export_policy.py` builds the two scoped policies with `PolicySet.from_pst`. If you choose Python as your policy source, generate the file before starting the app:

```sh
uv run python examples/report_export_policy.py > reports.cedar
```

Load that file with the same `Permission.from_files` call as the handwritten policy. The Python types check the structure of a clause; Cedar checks names like `stepped_up` against `reports.cedarschema` at startup.

## Binding guides

Use the guides below when you need more than a concrete allow or deny decision. All three are reproduced from [cedar-py v4.12.2](https://github.com/k9securityio/cedar-py/tree/v4.12.2); each includes its source link.

| If you need to… | Read |
| --- | --- |
| Inspect a policy in Python without parsing its source text | [Policy syntax trees](../cedarpy-pst/) |
| Ask what still depends on an unknown resource or missing facts | [Partial authorization](../cedarpy-partial/) |
| Call the synchronous evaluator from an async handler without blocking its event loop | [Threads and asyncio](../cedarpy-asyncio/) |

For Cedar's policy syntax and evaluation rules, see the external [Cedar language reference](https://docs.cedarpolicy.com/). For database reads, use the [SQLAlchemy guide](../sqlalchemy/). The adapter uses typed partial authorization to narrow the query and checks each candidate row with Cedar before returning it.
