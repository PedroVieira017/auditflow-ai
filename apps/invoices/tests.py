from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.alerts.models import Alert, AlertEvidence, AlertStatusEvent
from apps.audit_log.models import AuditEvent
from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.organizations.models import Membership, Organization
from apps.rules.models import RuleDefinition, RuleRun

from .models import InvoiceRecord


class OrganizationIsolationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="analista@example.com",
            password="password",
        )
        self.organization_a = Organization.objects.create(
            name="Empresa A",
            slug="empresa-a",
        )
        self.organization_b = Organization.objects.create(
            name="Empresa B",
            slug="empresa-b",
        )
        Membership.objects.create(
            organization=self.organization_a,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        self.import_a = self._create_import(self.organization_a, "a" * 64)
        self.import_b = self._create_import(self.organization_b, "b" * 64)
        self.invoice_a = self._create_invoice(
            organization=self.organization_a,
            import_batch=self.import_a,
            row_number=2,
        )
        self.invoice_b = self._create_invoice(
            organization=self.organization_b,
            import_batch=self.import_b,
            row_number=2,
        )
        self.rule = RuleDefinition.objects.create(
            key="DUPLICATE_INVOICE_EXACT",
            version=1,
            name="Faturas potencialmente duplicadas",
            description="Deteta faturas com os mesmos campos determinantes.",
            default_severity=Severity.MEDIUM,
        )
        self.rule_run_a = RuleRun.objects.create(
            organization=self.organization_a,
            import_batch=self.import_a,
            rule_definition=self.rule,
        )

    def _create_import(self, organization, file_hash):
        return ImportBatch.objects.create(
            organization=organization,
            uploaded_by=self.user,
            original_filename=f"faturas-{organization.slug}.csv",
            file_sha256=file_hash,
        )

    def _create_invoice(self, organization, import_batch, row_number):
        return InvoiceRecord.objects.create(
            organization=organization,
            import_batch=import_batch,
            source_row_number=row_number,
            supplier_identifier="FORN-001",
            supplier_name="Fornecedor Exemplo",
            invoice_number="FT 2026/1",
            normalized_invoice_number="FT 2026/1",
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal("123.45"),
            currency="EUR",
            source_values={"numero_fatura": "FT 2026/1"},
        )

    def test_scoped_queryset_only_returns_requested_organization(self):
        invoices_a = InvoiceRecord.objects.for_organization(self.organization_a)
        invoices_b = InvoiceRecord.objects.for_organization(self.organization_b.id)

        self.assertQuerySetEqual(invoices_a, [self.invoice_a])
        self.assertQuerySetEqual(invoices_b, [self.invoice_b])

    def test_invoice_rejects_import_from_another_organization(self):
        invoice_data = dict(
            organization=self.organization_a,
            import_batch=self.import_b,
            source_row_number=3,
            supplier_identifier="FORN-002",
            invoice_number="FT 2026/2",
            normalized_invoice_number="FT 2026/2",
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal("50.00"),
            currency="EUR",
        )

        with self.assertRaisesMessage(ValidationError, "outra organizacao"):
            InvoiceRecord.objects.create(**invoice_data)

    def test_rule_run_rejects_import_from_another_organization(self):
        with self.assertRaisesMessage(ValidationError, "outra organizacao"):
            RuleRun.objects.create(
                organization=self.organization_b,
                import_batch=self.import_a,
                rule_definition=self.rule,
            )

    def test_alert_and_evidence_reject_cross_organization_relations(self):
        alert = Alert.objects.create(
            organization=self.organization_a,
            rule_run=self.rule_run_a,
            fingerprint="c" * 64,
            title="Possivel fatura duplicada",
            explanation="Duas linhas possuem os mesmos campos.",
            severity=Severity.MEDIUM,
        )
        with self.assertRaisesMessage(ValidationError, "outra organizacao"):
            AlertEvidence.objects.create(
                organization=self.organization_a,
                alert=alert,
                invoice_record=self.invoice_b,
            )

    def test_complete_audit_graph_can_be_persisted(self):
        alert = Alert.objects.create(
            organization=self.organization_a,
            rule_run=self.rule_run_a,
            fingerprint="d" * 64,
            title="Possivel fatura duplicada",
            explanation="Duas linhas possuem os mesmos campos.",
            severity=Severity.MEDIUM,
            recommended_action="Confirmar os documentos de origem.",
        )
        evidence = AlertEvidence.objects.create(
            organization=self.organization_a,
            alert=alert,
            invoice_record=self.invoice_a,
            facts={"campos_iguais": ["fornecedor", "numero", "valor"]},
        )
        status_event = AlertStatusEvent.objects.create(
            organization=self.organization_a,
            alert=alert,
            changed_by=self.user,
            from_status=Alert.Status.NEW,
            to_status=Alert.Status.VALID,
            note="Confirmado pelo responsavel financeiro.",
        )
        audit_event = AuditEvent.objects.create(
            organization=self.organization_a,
            actor=self.user,
            action="alert.status_changed",
            resource_type="alert",
            resource_id=alert.id,
            metadata={"to_status": Alert.Status.VALID},
        )

        self.assertEqual(evidence.alert, alert)
        self.assertEqual(status_event.to_status, Alert.Status.VALID)
        self.assertEqual(audit_event.resource_id, alert.id)
