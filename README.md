# cedarpy-integrations

Write a policy with your Python types and enums. Cedar still makes the decision.

Alice owns a document. She may read it while it's a draft. What happens when she seals it?

```python
sealed = read_document.state == DocumentState.SEALED
owner_or_public = (read_document.owner == read_document.principal) | (
    read_document.state == DocumentState.PUBLIC
)

read = policy(
    read_document,
    permit_when=owner_or_public & ~sealed,
    forbid_when=sealed,
)
```

```text
Alice reads her own draft document: allow
Alice reads her own sealed document: deny
```

<details>
<summary>See the Cedar this Python generates</summary>

```cedar
permit (principal is User, action == Action::"read", resource is Document)
when {
  (((resource.owner) == principal) || ((resource.state) == "public")) &&
  (!((resource.state) == "sealed"))
};

forbid (principal is User, action == Action::"read", resource is Document)
when { (resource.state) == "sealed" };
```

</details>

Save [sealed_document.py](https://raw.githubusercontent.com/h0rv/cedarpy-integrations/main/examples/sealed_document.py) and run it. The script declares its dependencies, prints the generated Cedar, and checks both decisions. No checkout, web framework, or database is needed.

```sh
uv run sealed_document.py
```

## Install an integration

Use Python 3.13 or later. The base `cedarpy-integrations` install includes typed policies, shared web permissions, and WSGI. Choose an extra if your application uses ASGI or FastAPI:

| Use case | Install | Guide |
| --- | --- | --- |
| Share typed policy expressions in Python | `uv add cedarpy-integrations` | [Share policies in Python](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/policies.md) |
| Require permission on a FastAPI route | `uv add 'cedarpy-integrations[fastapi]'` | [FastAPI](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/fastapi.md) |
| Protect a mounted ASGI app | `uv add 'cedarpy-integrations[asgi]'` | [ASGI example](https://github.com/h0rv/cedarpy-integrations/blob/main/packages/web/examples/asgi_reports.py) |
| Protect Flask or Django views | `uv add cedarpy-integrations` | [Flask](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/flask.md) or [Django](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/django.md) |

The [SQLAlchemy reader](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/sqlalchemy.md) is available only as source in this repository. See [when to use Python or Cedar](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/choosing-policy.md) before choosing a policy format.

## Using the integrations

`cedarpy_policy` builds Cedar policy expressions from typed Python references. It does not fetch application data, replace Cedar schemas, or evaluate a request by itself. Use it when you want to define and share rules in Python. The [policy guide](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/src/content/docs/guides/policies.md) shows how it fits with the schema and SQLAlchemy reader.

For an HTTP operation, authenticate the caller first and supply verified user and session facts to Cedar. See [binding session facts](https://github.com/h0rv/cedarpy-integrations/blob/main/packages/web/README.md).

For row access, map model columns to Cedar facts. The SQL reader narrows candidate rows and checks each candidate with the policy. It does not protect raw SQL, writes, or other sessions. See [the SQLAlchemy API](https://github.com/h0rv/cedarpy-integrations/blob/main/packages/sqlalchemy/README.md).

Without a framework, call `cedarpy.is_authorized()` directly. The [example](https://github.com/h0rv/cedarpy-integrations/blob/main/examples/first_check.py) checks whether Alice and Bob may read the same document.

This project is licensed under [Apache License 2.0](https://github.com/h0rv/cedarpy-integrations/blob/main/LICENSE). Vendored documentation and grammars retain their upstream notices.

The four import namespaces (`cedarpy_policy`, `cedarpy_web`, `cedarpy_wsgi`, and `cedarpy_asgi`) live under `src/`. The SQLAlchemy source stays in `packages/sqlalchemy/src/`. See [the docs site](https://github.com/h0rv/cedarpy-integrations/blob/main/docs/README.md) for preview instructions and [release verification](https://github.com/h0rv/cedarpy-integrations/blob/main/RELEASE.md) for contributor checks.
