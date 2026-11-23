"""Session facts and a concrete Cedar permission for one mounted HTTP app."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from cedarpy import (
    Decision,
    PartialAuthzResult,
    PolicySet,
    Schema,
    is_authorized,
    is_authorized_partial,
    validate_policies,
)


@dataclass(frozen=True, slots=True)
class Session:
    user_id: str
    session_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(key, str) and key for key in (self.user_id, self.session_id)
        ):
            raise ValueError("Expected an authenticated user and session ID")


type Record = Mapping[str, str | int | bool]


class PermissionEvaluationError(RuntimeError):
    """The facts were invalid or a policy could not be evaluated."""


def _snapshot(record: Record) -> Record:
    if not isinstance(record, Mapping):
        raise PermissionEvaluationError("Expected a mapping of scalar facts")
    snapshot = dict(record)
    if not all(
        type(k) is str and type(v) in (str, int, bool) for k, v in snapshot.items()
    ):
        raise PermissionEvaluationError(
            "Expected string keys and str, int or bool values"
        )
    return MappingProxyType(snapshot)


@dataclass(frozen=True, slots=True, kw_only=True)
class Facts:
    principal_attrs: Record
    context: Record

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_attrs", _snapshot(self.principal_attrs))
        object.__setattr__(self, "context", _snapshot(self.context))


@dataclass(frozen=True, slots=True, init=False)
class Permission:
    policies: PolicySet
    schema: Schema
    action: str
    service: str

    def __init__(
        self,
        *,
        action: str,
        service: str,
        schema: str | Path | Schema,
        policies: str | PolicySet,
    ) -> None:
        """Bind policy text or a static policy set to one User/Action/Service mount."""
        for name, value in (("action", action), ("service", service)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonblank ID")

        if isinstance(schema, Path):
            schema = schema.read_text(encoding="utf-8")
        parsed_schema = (
            schema if isinstance(schema, Schema) else Schema.from_str(schema)
        )
        try:
            parsed_policies = (
                policies
                if isinstance(policies, PolicySet)
                else PolicySet.from_str(policies)
            )
        except ValueError as exc:
            raise ValueError(f"Invalid policies: {exc}") from exc
        # Formatting does not preserve templates or their links, so reject them
        # before converting a handle to text for native schema validation.
        if parsed_policies.templates():
            raise ValueError("expected a static policy set without templates or links")
        policy_text = str(parsed_policies)
        result = validate_policies(policy_text, parsed_schema)
        if not result.validation_passed:
            raise ValueError("Invalid policies: " + "; ".join(map(str, result.errors)))

        object.__setattr__(self, "policies", parsed_policies)
        object.__setattr__(self, "schema", parsed_schema)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "service", service)

        # Check appliesTo and the concrete Service entity. Only input diagnostics
        # matter here; the empty policy set always denies a well-formed request.
        if errors := self._partial("probe", policies="").diagnostics.errors:
            raise ValueError("Invalid mount: " + "; ".join(errors))

    @classmethod
    def from_files(
        cls, *, action: str, service: str, schema: str | Path, policies: str | Path
    ) -> "Permission":
        """Read both UTF-8 files once and validate the bound permission."""
        return cls(
            action=action,
            service=service,
            schema=Path(schema).read_text(encoding="utf-8"),
            policies=Path(policies).read_text(encoding="utf-8"),
        )

    def _partial(self, user_id: str, policies: str | PolicySet) -> PartialAuthzResult:
        # The classic partial API in 4.12.2 takes text UIDs. Leave context
        # absent and omit the principal entity so both sets of facts are unknown.
        return is_authorized_partial(
            {
                "principal": f"User::{json.dumps(user_id, ensure_ascii=False)}",
                "action": f"Action::{json.dumps(self.action, ensure_ascii=False)}",
                "resource": f"Service::{json.dumps(self.service, ensure_ascii=False)}",
            },
            policies,
            [
                {
                    "uid": {"type": "Service", "id": self.service},
                    "attrs": {},
                    "parents": [],
                }
            ],
            self.schema,
        )

    def definitely_denies(self, user_id: str) -> bool:
        preview = self._partial(user_id, self.policies)
        return preview.decision == Decision.Deny and not preview.diagnostics.errors

    def allows(self, user_id: str, facts: Facts) -> bool:
        principal = {"type": "User", "id": user_id}
        resource = {"type": "Service", "id": self.service}
        result = is_authorized(
            {
                "principal": principal,
                "action": {"type": "Action", "id": self.action},
                "resource": resource,
                "context": dict(facts.context),
            },
            self.policies,
            [
                {"uid": principal, "attrs": dict(facts.principal_attrs), "parents": []},
                {"uid": resource, "attrs": {}, "parents": []},
            ],
            self.schema,
        )
        if errors := result.diagnostics.errors:
            raise PermissionEvaluationError("; ".join(errors))
        return result.allowed
