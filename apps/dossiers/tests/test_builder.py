import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.alerts.models import Alert, AlertEvidence, AlertStatusEvent
from apps.audit_log.models import AuditEvent
from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.invoices.models import InvoiceRecord
from apps.organizations.models import Membership, Organization
from apps.rules.models import RuleDefinition, RuleRun

from ..builder import (
    WorkDossierDataIntegrityError,
    WorkDossierPermissionError,
    build_work_dossier_payload,
    calculate_payload_hash,
)


class WorkDossierBuilderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.generated_at = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
        cls.generation_id = UUID("99999999-9999-4999-8999-999999999999")
        cls.user = get_user_model().objects.create_user(
            id=UUID("22222222-2222-4222-8222-222222222222"),
            email="analista@example.com",
            password="password",
        )
        cls.organization = Organization.objects.create(
            id=UUID("11111111-1111-4111-8111-111111111111"),
            name="Empresa Exemplo, Lda.",
            slug="empresa-exemplo",
        )
        cls.membership = Membership.objects.create(
            organization=cls.organization,
            user=cls.user,
            role=Membership.Role.ANALYST,
        )
        cls.import_batch = ImportBatch.objects.create(
            id=UUID("33333333-3333-4333-8333-333333333333"),
            organization=cls.organization,
            uploaded_by=cls.user,
            original_filename="faturas-agosto.csv",
            file_sha256="a" * 64,
            status=ImportBatch.Status.COMPLETED,
            row_count=6,
            valid_row_count=6,
            invalid_row_count=0,
            completed_at=datetime(
                2026,
                8,
                2,
                9,
                4,
                58,
                tzinfo=timezone.utc,
            ),
        )
        cls.rule_definition = RuleDefinition.objects.create(
            key="DUPLICATE_INVOICE_EXACT",
            version=1,
            name="Faturas potencialmente duplicadas",
            description=(
                "Agrupa faturas com o mesmo fornecedor, número, data, valor e moeda."
            ),
            default_severity=Severity.MEDIUM,
        )
        cls.rule_run = RuleRun.objects.create(
            id=UUID("44444444-4444-4444-8444-444444444444"),
            organization=cls.organization,
            import_batch=cls.import_batch,
            rule_definition=cls.rule_definition,
            status=RuleRun.Status.COMPLETED,
            parameters={},
            alert_count=1,
            started_at=datetime(
                2026,
                8,
                2,
                9,
                4,
                59,
                tzinfo=timezone.utc,
            ),
            completed_at=datetime(
                2026,
                8,
                2,
                9,
                5,
                tzinfo=timezone.utc,
            ),
        )
        first_invoice = cls.create_invoice(
            invoice_id="77777777-7777-4777-8777-777777777771",
            source_row_number=2,
        )
        second_invoice = cls.create_invoice(
            invoice_id="77777777-7777-4777-8777-777777777772",
            source_row_number=5,
        )
        cls.alert = Alert.objects.create(
            id=UUID("55555555-5555-4555-8555-555555555555"),
            organization=cls.organization,
            rule_run=cls.rule_run,
            fingerprint="b" * 64,
            title="Possíveis faturas duplicadas",
            explanation=(
                "Foram encontradas 2 faturas com o mesmo fornecedor, número, "
                "data, valor e moeda."
            ),
            severity=Severity.MEDIUM,
            status=Alert.Status.VALID,
            recommended_action=(
                "Comparar os documentos de origem e confirmar se representam "
                "a mesma obrigação."
            ),
        )
        Alert.objects.filter(id=cls.alert.id).update(
            created_at=datetime(2026, 8, 2, 9, 5, tzinfo=timezone.utc)
        )
        cls.alert.refresh_from_db()
        cls.first_evidence = cls.create_evidence(
            evidence_id="66666666-6666-4666-8666-666666666661",
            invoice=first_invoice,
        )
        cls.create_evidence(
            evidence_id="66666666-6666-4666-8666-666666666662",
            invoice=second_invoice,
        )
        cls.status_event = AlertStatusEvent.objects.create(
            id=UUID("88888888-8888-4888-8888-888888888888"),
            organization=cls.organization,
            alert=cls.alert,
            changed_by=cls.user,
            from_status=Alert.Status.NEW,
            to_status=Alert.Status.VALID,
            note="A exceção foi confirmada através dos documentos de origem.",
        )
        AlertStatusEvent.objects.filter(id=cls.status_event.id).update(
            created_at=datetime(2026, 8, 2, 10, 15, tzinfo=timezone.utc)
        )
        cls.status_event.refresh_from_db()

    @classmethod
    def create_invoice(cls, *, invoice_id, source_row_number):
        return InvoiceRecord.objects.create(
            id=UUID(invoice_id),
            organization=cls.organization,
            import_batch=cls.import_batch,
            source_row_number=source_row_number,
            supplier_identifier="PT500000001",
            invoice_number="FT 2026/100",
            normalized_invoice_number="FT 2026/100",
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal("1230.00"),
            currency="EUR",
        )

    @classmethod
    def create_evidence(cls, *, evidence_id, invoice):
        return AlertEvidence.objects.create(
            id=UUID(evidence_id),
            organization=cls.organization,
            alert=cls.alert,
            invoice_record=invoice,
            facts={
                "currency": "EUR",
                "gross_amount": "1230.00",
                "invoice_date": "2026-08-01",
                "invoice_number": "FT 2026/100",
                "source_row_number": invoice.source_row_number,
                "supplier_identifier": "PT500000001",
            },
        )

    def build_payload(self, **overrides):
        parameters = {
            "import_batch": self.import_batch,
            "generated_by": self.user,
            "generation_id": self.generation_id,
            "generated_at": self.generated_at,
        }
        parameters.update(overrides)
        return build_work_dossier_payload(**parameters)

    def test_builder_matches_the_versioned_example(self):
        expected_path = (
            Path(settings.BASE_DIR)
            / "examples"
            / "dossier"
            / "dossier-trabalho-v1.example.json"
        )
        expected_payload = json.loads(expected_path.read_text(encoding="utf-8"))

        payload = self.build_payload()

        self.assertEqual(payload, expected_payload)

    def test_same_snapshot_produces_the_same_payload_and_hash(self):
        first_payload = self.build_payload()
        second_payload = self.build_payload()

        self.assertEqual(first_payload, second_payload)
        self.assertEqual(
            first_payload["integrity"]["payload_hash"],
            calculate_payload_hash(first_payload),
        )

    def test_builder_does_not_write_a_generation_audit_event(self):
        self.assertFalse(AuditEvent.objects.exists())

        self.build_payload()

        self.assertFalse(AuditEvent.objects.exists())

    def test_viewer_cannot_build_a_dossier(self):
        self.membership.role = Membership.Role.VIEWER
        self.membership.save()

        with self.assertRaises(WorkDossierPermissionError):
            self.build_payload()

    def test_missing_user_cannot_build_a_dossier(self):
        with self.assertRaises(WorkDossierPermissionError):
            self.build_payload(generated_by=None)

    def test_invalid_generation_id_is_rejected(self):
        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload(generation_id="identificador-invalido")

    def test_incomplete_import_is_rejected(self):
        ImportBatch.objects.filter(id=self.import_batch.id).update(
            status=ImportBatch.Status.PROCESSING
        )

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_alert_without_evidence_is_rejected(self):
        AlertEvidence.objects.filter(alert=self.alert).delete()

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_inconsistent_rule_run_alert_count_is_rejected(self):
        RuleRun.objects.filter(id=self.rule_run.id).update(alert_count=2)

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_invalid_rule_run_status_is_rejected(self):
        RuleRun.objects.filter(id=self.rule_run.id).update(status="invalid")

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_broken_status_history_is_rejected(self):
        AlertStatusEvent.objects.filter(id=self.status_event.id).update(
            from_status=Alert.Status.RESOLVED
        )

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_status_history_without_note_is_rejected(self):
        AlertStatusEvent.objects.filter(id=self.status_event.id).update(note="")

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_evidence_from_another_import_is_rejected(self):
        other_import = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="outra-importacao.csv",
            file_sha256="c" * 64,
            status=ImportBatch.Status.COMPLETED,
            completed_at=self.generated_at,
        )
        other_invoice = InvoiceRecord.objects.create(
            organization=self.organization,
            import_batch=other_import,
            source_row_number=2,
            supplier_identifier="PT599999999",
            invoice_number="FT 2",
            normalized_invoice_number="FT 2",
            invoice_date=date(2026, 8, 2),
            gross_amount=Decimal("10.00"),
            currency="EUR",
        )
        AlertEvidence.objects.filter(id=self.first_evidence.id).update(
            invoice_record=other_invoice
        )

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload()

    def test_completed_import_without_runs_or_alerts_is_valid(self):
        empty_import = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="sem-alertas.csv",
            file_sha256="d" * 64,
            status=ImportBatch.Status.COMPLETED,
            completed_at=self.generated_at,
        )

        payload = self.build_payload(
            import_batch=empty_import,
            generation_id=uuid4(),
        )

        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["rule_runs"], [])
        self.assertEqual(payload["summary"]["alert_count"], 0)
        self.assertEqual(payload["summary"]["rule_run_count"], 0)
        self.assertEqual(
            payload["integrity"]["payload_hash"],
            calculate_payload_hash(payload),
        )

    def test_failed_rule_run_does_not_expose_internal_error_message(self):
        failed_import = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="regra-falhou.csv",
            file_sha256="e" * 64,
            status=ImportBatch.Status.COMPLETED,
            completed_at=self.generated_at,
        )
        RuleRun.objects.create(
            organization=self.organization,
            import_batch=failed_import,
            rule_definition=self.rule_definition,
            status=RuleRun.Status.FAILED,
            alert_count=0,
            error_message="database password: segredo-interno",
        )

        payload = self.build_payload(
            import_batch=failed_import,
            generation_id=uuid4(),
        )

        self.assertNotIn("segredo-interno", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("error_message", payload["rule_runs"][0])

    def test_naive_generation_datetime_is_rejected(self):
        naive_datetime = datetime(2026, 8, 2, 11, 0)

        with self.assertRaises(WorkDossierDataIntegrityError):
            self.build_payload(generated_at=naive_datetime)
