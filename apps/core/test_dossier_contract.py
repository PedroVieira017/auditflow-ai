import hashlib
import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.test import SimpleTestCase


class WorkDossierContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        example_path = (
            Path(settings.BASE_DIR)
            / "examples"
            / "dossier"
            / "dossier-trabalho-v1.example.json"
        )
        cls.payload = json.loads(example_path.read_text(encoding="utf-8"))

    def test_example_has_stable_contract_and_required_sections(self):
        self.assertEqual(
            self.payload["contract"],
            "auditflow-work-dossier-v1",
        )
        self.assertEqual(
            set(self.payload),
            {
                "alerts",
                "contract",
                "document",
                "integrity",
                "limitations",
                "organization",
                "rule_runs",
                "scope",
                "summary",
            },
        )
        self.assertEqual(
            self.payload["document"]["certification"],
            "not_certified",
        )
        UUID(self.payload["document"]["generation_id"])
        UUID(self.payload["organization"]["id"])
        UUID(self.payload["scope"]["import"]["id"])

    def test_summary_reconciles_with_alerts_and_rule_runs(self):
        alerts = self.payload["alerts"]
        rule_runs = self.payload["rule_runs"]
        summary = self.payload["summary"]

        self.assertEqual(summary["alert_count"], len(alerts))
        self.assertEqual(summary["rule_run_count"], len(rule_runs))
        self.assertEqual(
            summary["alerts_by_status"],
            {
                status: Counter(alert["status"] for alert in alerts)[status]
                for status in ("false_positive", "new", "resolved", "valid")
            },
        )
        self.assertEqual(
            summary["alerts_by_severity"],
            {
                severity: Counter(alert["severity"] for alert in alerts)[severity]
                for severity in ("critical", "high", "low", "medium")
            },
        )

        alerts_by_run = Counter(alert["rule_run_id"] for alert in alerts)
        for rule_run in rule_runs:
            self.assertEqual(
                rule_run["alert_count"],
                alerts_by_run[rule_run["id"]],
            )

    def test_example_contains_only_the_required_limitation_codes(self):
        self.assertEqual(
            {limitation["code"] for limitation in self.payload["limitations"]},
            {
                "human_review_required",
                "not_an_audit_opinion",
                "rule_matches_only",
                "scope_limited_to_import",
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
