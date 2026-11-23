import json
import unittest
from itertools import product
from typing import assert_type

import cedarpy

from examples.typed_policy import documents, reports
from examples.typed_policy.domain import DocumentState
from examples.typed_policy.generate import DOCUMENTS, REPORTS, Binding, render_action


def uid(kind: str, key: str) -> dict[str, str]:
    return {"type": kind, "id": key}


def entity(key: dict[str, str], **attrs: object) -> dict[str, object]:
    return {"uid": key, "attrs": attrs, "parents": []}


class EquivalenceTests(unittest.TestCase):
    def policies(self, binding: Binding, compiled: cedarpy.PolicySet):
        schema = cedarpy.Schema.from_json_str(binding.schema.read_text())
        fixture = binding.schema.with_suffix("").with_suffix(".cedar").read_text()
        for source in (str(compiled), fixture):
            result = cedarpy.validate_policies(source, schema)
            self.assertTrue(result.validation_passed, result.errors)
        return (compiled, cedarpy.PolicySet.from_str(fixture)), schema

    def test_documents(self):
        policies, schema = self.policies(
            DOCUMENTS, assert_type(documents.read, cedarpy.PolicySet)
        )
        alice, doc = uid("User", "alice"), uid("Document", "notes")
        # The app's enum does not narrow Cedar's String schema.
        for owner, state in product(("alice", "bob"), (*DocumentState, "unlisted")):
            with self.subTest(owner=owner, state=state):
                request = {
                    "principal": alice,
                    "action": uid("Action", "read"),
                    "resource": doc,
                    "context": {},
                }
                entities = [
                    entity(alice),
                    entity(
                        doc, owner={"__entity": uid("User", owner)}, state=str(state)
                    ),
                ]
                expected = state != DocumentState.SEALED and (
                    owner == "alice" or state == DocumentState.PUBLIC
                )
                for policy in policies:
                    result = cedarpy.is_authorized(
                        request, policy, entities, schema=schema
                    )
                    self.assertFalse(
                        result.diagnostics.errors, result.diagnostics.errors
                    )
                    self.assertIs(result.allowed, expected)

    def test_reports(self):
        policies, schema = self.policies(
            REPORTS, assert_type(reports.start_export, cedarpy.PolicySet)
        )
        alice = uid("User", "alice")
        for entitlement, step_up, service in product(
            (False, True), (False, True), ("reports", "other")
        ):
            with self.subTest(
                entitlement=entitlement, step_up=step_up, service=service
            ):
                target = uid("Service", service)
                request = {
                    "principal": alice,
                    "action": uid("Action", "export"),
                    "resource": target,
                    "context": {"stepped_up": step_up},
                }
                entities = [entity(alice, can_export=entitlement), entity(target)]
                for policy in policies:
                    result = cedarpy.is_authorized(
                        request, policy, entities, schema=schema
                    )
                    self.assertFalse(
                        result.diagnostics.errors, result.diagnostics.errors
                    )
                    self.assertIs(
                        result.allowed, entitlement and step_up and service == "reports"
                    )
                    if service != "reports":
                        self.assertFalse(
                            result.diagnostics.reasons
                        )  # Neither scoped rule matched.

    def test_missing_or_invalid_guard_facts_do_not_grant_access(self):
        alice = uid("User", "alice")
        doc = uid("Document", "notes")
        service = uid("Service", "reports")
        for binding, compiled, target, facts, context in (
            (
                DOCUMENTS,
                documents.read,
                doc,
                [entity(alice), entity(doc, owner={"__entity": alice})],
                {},
            ),
            (
                REPORTS,
                reports.start_export,
                service,
                [entity(alice, can_export=True), entity(service)],
                {},
            ),
            (
                REPORTS,
                reports.start_export,
                service,
                [entity(alice, can_export=True), entity(service)],
                {"stepped_up": "yes"},
            ),
        ):
            policies, schema = self.policies(binding, compiled)
            request = {
                "principal": alice,
                "action": uid("Action", binding.action),
                "resource": target,
                "context": context,
            }
            for policy, request_schema in product(policies, (schema, None)):
                with self.subTest(
                    action=binding.action, schema=request_schema, context=context
                ):
                    result = cedarpy.is_authorized(
                        request, policy, facts, schema=request_schema
                    )
                    self.assertFalse(result.allowed)
                    self.assertTrue(result.diagnostics.errors)

    def test_forbids_override_another_matching_permit(self):
        alice = uid("User", "alice")
        doc = uid("Document", "notes")
        service = uid("Service", "reports")
        for binding, compiled, target, facts, context in (
            (
                DOCUMENTS,
                documents.read,
                doc,
                [entity(alice), entity(doc, owner={"__entity": alice}, state="sealed")],
                {},
            ),
            (
                REPORTS,
                reports.start_export,
                service,
                [entity(alice, can_export=True), entity(service)],
                {"stepped_up": False},
            ),
        ):
            policies, schema = self.policies(binding, compiled)
            request = {
                "principal": alice,
                "action": uid("Action", binding.action),
                "resource": target,
                "context": context,
            }
            for policy in policies:
                with self.subTest(action=binding.action):
                    combined = policy.with_added_str(
                        "permit(principal, action, resource);"
                    )
                    result = cedarpy.is_authorized(
                        request, combined, facts, schema=schema
                    )
                    self.assertFalse(result.allowed)
                    self.assertFalse(
                        result.diagnostics.errors, result.diagnostics.errors
                    )


class GeneratorTests(unittest.TestCase):
    def test_fields_follow_schema(self):
        schema = json.loads(DOCUMENTS.schema.read_text())
        attrs = schema[""]["entityTypes"]["Document"]["shape"]["attributes"]
        attrs["reviewer"] = attrs.pop("owner")
        generated = render_action(DOCUMENTS, json.dumps(schema))
        self.assertIn("reviewer = _api.entity_field(", generated)
        self.assertNotIn("owner", generated)

    def test_explicitly_closed_records_generate_the_same_references(self):
        source = REPORTS.schema.read_text()
        schema = json.loads(source)
        context = schema[""]["actions"]["export"]["appliesTo"]["context"]
        context["additionalAttributes"] = False
        self.assertEqual(
            render_action(REPORTS, json.dumps(schema)), render_action(REPORTS, source)
        )

    def test_unsupported_fields_are_not_silently_ignored(self):
        for name, descriptor in [
            ("owner", {"type": "Entity", "name": "Missing"}),
            ("owner", {"type": "Entity", "name": "User", "required": False}),
            ("state", {"type": "Boolean"}),
            ("label", {"type": "String"}),
            ("class", {"type": "Boolean"}),
        ]:
            with self.subTest(name=name, descriptor=descriptor):
                schema = json.loads(DOCUMENTS.schema.read_text())
                schema[""]["entityTypes"]["Document"]["shape"]["attributes"][name] = (
                    descriptor
                )
                with self.assertRaises(ValueError):
                    render_action(DOCUMENTS, json.dumps(schema))

    def test_cedar_entity_features_outside_the_subset_are_rejected(self):
        for feature in (
            {"enum": ["reports"]},
            {"memberOfTypes": ["User"]},
            {"tags": {"type": "Boolean"}},
        ):
            with self.subTest(feature=feature):
                schema = json.loads(REPORTS.schema.read_text())
                schema[""]["entityTypes"]["Service"] = feature
                source = json.dumps(schema)
                cedarpy.Schema.from_json_str(source)
                with self.assertRaisesRegex(ValueError, "optional inline entity shape"):
                    render_action(REPORTS, source)

    def test_unsupported_action_shape(self):
        schema = json.loads(REPORTS.schema.read_text())
        schema[""]["actions"]["export"]["appliesTo"]["resourceTypes"].append("User")
        source = json.dumps(schema)
        cedarpy.Schema.from_json_str(source)
        with self.assertRaisesRegex(
            ValueError, "one principal type, one resource type"
        ):
            render_action(REPORTS, source)
