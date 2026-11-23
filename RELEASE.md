# Local release check

Run `uv build` from the repository root. The `uv_build` backend uses the root `pyproject.toml` to build one source archive and one wheel for `cedarpy-integrations`. Both go in `dist/`. Building does not upload either file.

Before publishing, run `scripts/verify-release` as an unprivileged user from the repository root. You need `uv`, Git, Rust, and PostgreSQL server tools (`pg_config`, `initdb`, and `pg_ctl`). The script tests the same wheel in separate Python 3.13 environments: the base install should support policy, web, and WSGI without Starlette or FastAPI. The `[asgi]` extra should support ASGI without FastAPI. The `[fastapi]` extra should support FastAPI route dependencies. Run `scripts/test-typed-policy` for the typing and policy examples, and `scripts/test-frameworks` for the framework examples.

The distribution depends on released `cedarpy`. The SQLAlchemy reader under `packages/sqlalchemy/src/` needs a fork for typed partial authorization. The verification script tests that source separately with the pinned fork and a disposable PostgreSQL database. Neither the reader nor the fork belongs in the release artifacts. The script prints the directory containing the wheel, source archive, checksums, and tested dependency lists. It does not publish anything.

## Publish to PyPI

The first release is `0.1.0a0`. For each release, set the version in the root `pyproject.toml` and update the version pins in `examples/sealed_document.py` and `examples/pst_policy.py`. Restrict the GitHub environment `pypi` to the `main` branch. Configure a PyPI trusted publisher for `cedarpy-integrations` with the repository `h0rv/cedarpy-integrations`, workflow filename `publish.yml`, and environment `pypi`. To publish, run the **Publish to PyPI** workflow manually (`workflow_dispatch`) on `main`. It builds the root project, checks the quickstart against the wheel, and publishes the tested wheel and its source archive.

## First service rollout

1. Pick one read-only operation with a known answer from the current enforcement path. Verify that the registered action, resource type, cursor order, and returned columns match the service contract. The web guard targets ordinary (non-enumerated) `User` IDs. Its startup check binds a sample user ID; an enumerated user type that does not contain it is rejected. Neither the web guard nor the SQL reader protects unwrapped routes, unrelated sessions, or raw SQL. The reader does not redact fields on visible rows.
2. Supply identity from verified authentication. Load step-up from a source that checks the user **and** session, expiry, and revocation. Give the loader a deadline. On timeout or malformed facts, fail closed; do not retry the handler without its guard. Never pass a client-supplied action or step-up flag.
3. Shadow against the existing decision, keeping that decision authoritative. Compare authorized IDs, order, page continuation, denials, and errors. Check the query plan for a narrow and a widened permit on representative data. An indexed keyset query and a candidate budget serve different purposes. Measure latency, pool usage, timeouts, and budget overflows before declaring an endpoint ready.
4. Switch one operation. Keep the old enforcement path available for rollback. Treat `ScanLimitExceeded` as an incomplete operation, not an empty page or permission to return the partial result. Keep evaluation errors distinguishable from ordinary denials in internal telemetry. Do not log session IDs, step-up records, or raw sensitive attributes.

No production shadow traffic, load claims, independent external audit, or OSI license approval is implied by passing these local tests.
