from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvidence
from apps.audit_log.models import AuditEvent
from apps.imports.models import ImportBatch
from apps.invoices.models import InvoiceRecord
from apps.organizations.models import Organization
from apps.rules.duplicate_invoices import DUPLICATE_INVOICE_EXACT_RULE
from apps.rules.models import RuleDefinition, RuleRun
from apps.rules.services import (
    RuleDefinitionConflictError,
    RuleExecutionError,
    execute_rule_for_import,
)


class RuleExecutionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="regras@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa Regras",
            slug="empresa-regras",
        )
        self.import_batch = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="faturas.csv",
            storage_key="organizations/test/faturas.csv",
            file_sha256="a" * 64,
            status=ImportBatch.Status.COMPLETED,
            row_count=2,
            valid_row_count=2,
            completed_at=timezone.now(),
        )

    def invoice(self, *, row, supplier="FORN-001", number="FT 2026/001"):
        return InvoiceRecord.objects.create(
            organization=self.organization,
            import_batch=self.import_batch,
            source_row_number=row,
            supplier_identifier=supplier,
            invoice_number=number,
            normalized_invoice_number=number.upper(),
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal("100.00"),
            currency="EUR",
            source_values={"numero_fatura": number},
        )

    def test_rule_run_alert_and_evidence_are_persisted(self):
        first = self.invoice(row=2)
        second = self.invoice(row=3, supplier="forn-001", number="ft 2026/001")

        rule_run = execute_rule_for_import(
            rule=DUPLICATE_INVOICE_EXACT_RULE,
            import_batch=self.import_batch,
        )

        self.assertEqual(rule_run.status, RuleRun.Status.COMPLETED)
        self.assertEqual(rule_run.alert_count, 1)
        self.assertIsNotNone(rule_run.started_at)
        self.assertIsNotNone(rule_run.completed_at)
        definition = RuleDefinition.objects.get()
        self.assertEqual(definition.key, "DUPLICATE_INVOICE_EXACT")
        self.assertEqual(definition.version, 1)

        alert = Alert.objects.get(rule_run=rule_run)
        self.assertEqual(alert.status, Alert.Status.NEW)
        self.assertEqual(len(alert.fingerprint), 64)
        evidence = list(
            AlertEvidence.objects.filter(alert=alert).order_by(
                "invoice_record__source_row_number"
            )
        )
        self.assertEqual(
            [item.invoice_record_id for item in evidence],
            [first.id, second.id],
        )
        self.assertEqual(evidence[0].facts["gross_amount"], "100.00")
        self.assertTrue(
            AuditEvent.objects.filter(action="rule_run.completed").exists()
        )

    def test_run_without_duplicates_completes_without_alerts(self):
        self.invoice(row=2)
        self.invoice(row=3, number="FT 2026/002")

        rule_run = execute_rule_for_import(
            rule=DUPLICATE_INVOICE_EXACT_RULE,
            import_batch=self.import_batch,
        )

        self.assertEqual(rule_run.status, RuleRun.Status.COMPLETED)
        self.assertEqual(rule_run.alert_count, 0)
        self.assertFalse(Alert.objects.exists())
        self.assertFalse(AlertEvidence.objects.exists())

    def test_incomplete_import_cannot_execute_rule(self):
        self.import_batch.status = ImportBatch.Status.FAILED
        self.import_batch.save()

        with self.assertRaisesMessage(RuleExecutionError, "concluidas"):
            execute_rule_for_import(
                rule=DUPLICATE_INVOICE_EXACT_RULE,
                import_batch=self.import_batch,
            )

        self.assertFalse(RuleRun.objects.exists())

    def test_persisted_definition_cannot_drift_from_code(self):
        RuleDefinition.objects.create(
            key="DUPLICATE_INVOICE_EXACT",
            version=1,
            name="Nome divergente",
            description=DUPLICATE_INVOICE_EXACT_RULE.metadata.description,
            default_severity=(
                DUPLICATE_INVOICE_EXACT_RULE.metadata.default_severity
            ),
        )

        with self.assertRaises(RuleDefinitionConflictError):
            execute_rule_for_import(
                rule=DUPLICATE_INVOICE_EXACT_RULE,
                import_batch=self.import_batch,
            )

        self.assertFalse(RuleRun.objects.exists())

    def test_persistence_failure_leaves_no_partial_alerts(self):
        self.invoice(row=2)
        self.invoice(row=3)

        with patch(
            "apps.rules.services.AlertEvidence.objects.create",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuleExecutionError):
                execute_rule_for_import(
                    rule=DUPLICATE_INVOICE_EXACT_RULE,
                    import_batch=self.import_batch,
                )

        rule_run = RuleRun.objects.get()
        self.assertEqual(rule_run.status, RuleRun.Status.FAILED)
        self.assertEqual(rule_run.alert_count, 0)
        self.assertFalse(Alert.objects.exists())
        self.assertFalse(AlertEvidence.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="rule_run.failed").exists())
