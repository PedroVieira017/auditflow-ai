import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.test import SimpleTestCase

from apps.rules.catalog import rule_registry


STABLE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ControlScenarioContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        example_path = (
            Path(settings.BASE_DIR)
            / "examples"
            / "control_scenarios"
            / "cenario-controlo-v1.example.json"
        )
        cls.payload = json.loads(example_path.read_text(encoding="utf-8"))

    def assert_canonical_uuid(self, value):
        self.assertEqual(str(UUID(value)), value)

    def parse_utc_datetime(self, value):
        self.assertTrue(value.endswith("Z"))
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
        return parsed

    def test_example_has_stable_contract_sections_and_identity(self):
        self.assertEqual(
            self.payload["contract"],
            "auditflow-control-scenario-v1",
        )
        self.assertEqual(
            set(self.payload),
            {
                "contract",
                "control",
                "governance",
                "integrity",
                "limitations",
                "monitoring",
                "objective",
                "organization",
                "risk",
                "rules",
                "scenario",
            },
        )
        scenario = self.payload["scenario"]
        self.assertEqual(
            set(scenario),
            {
                "description",
                "id",
                "key",
                "name",
                "version",
                "version_id",
            },
        )
        self.assert_canonical_uuid(self.payload["organization"]["id"])
        self.assert_canonical_uuid(scenario["id"])
        self.assert_canonical_uuid(scenario["version_id"])
        self.assertNotEqual(scenario["id"], scenario["version_id"])
        self.assertRegex(scenario["key"], STABLE_KEY_PATTERN)
        self.assertGreaterEqual(scenario["version"], 1)

    def test_governance_records_human_approval_before_effective_date(self):
        governance = self.payload["governance"]
        self.assertEqual(
            set(governance),
            {
                "approval_note",
                "approved_at",
                "approved_by",
                "change_reason",
                "created_at",
                "created_by",
                "effective_from",
                "state",
                "supersedes_version_id",
            },
        )
        self.assertEqual(governance["state"], "approved")
        self.assertTrue(governance["approval_note"].strip())
        self.assertTrue(governance["change_reason"].strip())
        created_at = self.parse_utc_datetime(governance["created_at"])
        approved_at = self.parse_utc_datetime(governance["approved_at"])
        effective_from = date.fromisoformat(governance["effective_from"])
        self.assertLess(created_at, approved_at)
        self.assertGreaterEqual(effective_from, approved_at.date())
        self.assertIsNone(governance["supersedes_version_id"])
        for user_field in ("created_by", "approved_by"):
            user = governance[user_field]
            self.assertEqual(set(user), {"email", "role", "user_id"})
            self.assert_canonical_uuid(user["user_id"])
            self.assertIn("@", user["email"])
            self.assertIn(user["role"], {"owner", "analyst"})
        self.assertEqual(governance["approved_by"]["role"], "owner")

    def test_objective_risk_and_control_use_explicit_vocabulary(self):
        objective = self.payload["objective"]
        risk = self.payload["risk"]
        control = self.payload["control"]
        self.assertEqual(set(objective), {"category", "statement"})
        self.assertIn(
            objective["category"],
            {"operations", "reporting", "compliance"},
        )
        self.assertTrue(objective["statement"].strip())
        self.assertEqual(set(risk), {"statement"})
        self.assertTrue(risk["statement"].strip())
        self.assertEqual(
            set(control),
            {
                "description",
                "evidence_expectations",
                "frequency",
                "name",
                "owner_role",
                "type",
            },
        )
        self.assertIn(
            control["type"],
            {"preventive", "detective", "corrective"},
        )
        self.assertIn(
            control["frequency"],
            {
                "per_transaction",
                "per_import",
                "daily",
                "weekly",
                "monthly",
                "quarterly",
                "annual",
                "ad_hoc",
            },
        )
        self.assertTrue(control["owner_role"].strip())
        self.assertTrue(control["evidence_expectations"])
        self.assertTrue(
            all(item.strip() for item in control["evidence_expectations"])
        )

    def test_indicators_are_declarative_versioned_measurements(self):
        monitoring = self.payload["monitoring"]
        self.assertEqual(
            set(monitoring),
            {"indicators", "review_due_days", "reviewer_role"},
        )
        self.assertGreaterEqual(monitoring["review_due_days"], 1)
        self.assertTrue(monitoring["reviewer_role"].strip())
        self.assertTrue(monitoring["indicators"])
        indicator_keys = []
        rule_keys = {rule["key"] for rule in self.payload["rules"]}
        for indicator in monitoring["indicators"]:
            self.assertEqual(
                set(indicator),
                {
                    "description",
                    "direction",
                    "key",
                    "measurement",
                    "name",
                    "target",
                    "type",
                    "unit",
                },
            )
            self.assertRegex(indicator["key"], STABLE_KEY_PATTERN)
            indicator_keys.append(indicator["key"])
            self.assertIn(
                indicator["type"],
                {"kpi", "kri", "control_indicator"},
            )
            self.assertIn(
                indicator["unit"],
                {"count", "percentage", "currency", "days", "ratio"},
            )
            self.assertIn(
                indicator["direction"],
                {
                    "lower_is_better",
                    "higher_is_better",
                    "informational",
                },
            )
            measurement = indicator["measurement"]
            self.assertEqual(
                set(measurement),
                {
                    "metric_key",
                    "metric_version",
                    "parameters",
                    "window",
                },
            )
            self.assertRegex(measurement["metric_key"], STABLE_KEY_PATTERN)
            self.assertGreaterEqual(measurement["metric_version"], 1)
            self.assertIsInstance(measurement["parameters"], dict)
            self.assertIn(
                measurement["window"],
                {
                    "per_import",
                    "daily",
                    "weekly",
                    "monthly",
                    "quarterly",
                    "annual",
                },
            )
            referenced_rule = measurement["parameters"].get("rule_key")
            if referenced_rule:
                self.assertIn(referenced_rule, rule_keys)
            target = indicator["target"]
            self.assertEqual(set(target), {"operator", "value"})
            self.assertIn(target["operator"], {"eq", "gt", "gte", "lt", "lte"})
            self.assertIsInstance(target["value"], str)
            Decimal(target["value"])
        self.assertEqual(len(indicator_keys), len(set(indicator_keys)))

    def test_rule_bindings_are_explicit_versioned_and_traceable(self):
        rules = self.payload["rules"]
        self.assertTrue(rules)
        rule_keys = []
        for rule in rules:
            self.assertEqual(
                set(rule),
                {
                    "key",
                    "origin",
                    "parameters",
                    "purpose",
                    "severity",
                    "version",
                },
            )
            self.assertRegex(rule["key"], STABLE_KEY_PATTERN)
            self.assertGreaterEqual(rule["version"], 1)
            rule_keys.append(rule["key"])
            registered_rule = rule_registry.get(rule["key"], rule["version"])
            self.assertEqual(registered_rule.metadata.key, rule["key"])
            self.assertEqual(registered_rule.metadata.version, rule["version"])
            self.assertIsInstance(rule["parameters"], dict)
            self.assertTrue(rule["purpose"].strip())
            self.assertIn(
                rule["severity"],
                {"low", "medium", "high", "critical"},
            )
            origin = rule["origin"]
            self.assertEqual(set(origin), {"references", "type"})
            self.assertIn(
                origin["type"],
                {"internal", "contractual", "regulatory", "suggested_template"},
            )
            self.assertIsInstance(origin["references"], list)
            for reference in origin["references"]:
                self.assertEqual(set(reference), {"reference", "title"})
                self.assertTrue(reference["reference"].strip())
                self.assertTrue(reference["title"].strip())
        self.assertEqual(len(rule_keys), len(set(rule_keys)))

    def test_example_contains_only_required_limitation_codes(self):
        self.assertEqual(len(self.payload["limitations"]), 4)
        for limitation in self.payload["limitations"]:
            self.assertEqual(set(limitation), {"code", "message"})
            self.assertTrue(limitation["message"].strip())
        self.assertEqual(
            {item["code"] for item in self.payload["limitations"]},
            {
                "configured_criteria_only",
                "human_review_required",
                "indicators_are_not_controls",
                "not_a_professional_conclusion",
            },
        )

    def test_integrity_hash_matches_canonical_payload_without_integrity(self):
        payload_without_integrity = {
            key: value
            for key, value in self.payload.items()
            if key != "integrity"
        }
        canonical_payload = json.dumps(
            payload_without_integrity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        calculated_hash = hashlib.sha256(canonical_payload).hexdigest()

        self.assertEqual(self.payload["integrity"]["algorithm"], "sha256")
        self.assertEqual(
            self.payload["integrity"]["payload_hash"],
            calculated_hash,
        )
