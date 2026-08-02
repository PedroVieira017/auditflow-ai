from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.invoices.models import InvoiceRecord
from apps.organizations.models import Membership, Organization
from apps.rules.models import RuleDefinition, RuleRun

from ..models import Alert, AlertEvidence


class AlertViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="leitor-alertas@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa dos Alertas",
            slug="empresa-dos-alertas",
        )
        self.membership = Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.VIEWER,
        )
        self.rule_definition = RuleDefinition.objects.create(
            key="DUPLICATE_INVOICE_EXACT",
            version=1,
            name="Faturas potencialmente duplicadas",
            description="Compara os campos definidos pela regra.",
            default_severity=Severity.MEDIUM,
        )
        self.import_batch = self.create_import_batch(
            organization=self.organization,
            uploaded_by=self.user,
            filename="faturas-agosto.csv",
            file_hash="a" * 64,
        )
        self.rule_run = self.create_rule_run(
            organization=self.organization,
            import_batch=self.import_batch,
        )
        self.first_invoice = self.create_invoice(
            organization=self.organization,
            import_batch=self.import_batch,
            source_row_number=2,
            supplier_name="Fornecedor Principal",
        )
        self.second_invoice = self.create_invoice(
            organization=self.organization,
            import_batch=self.import_batch,
            source_row_number=5,
            supplier_name="Fornecedor Principal",
        )
        self.alert = Alert.objects.create(
            organization=self.organization,
            rule_run=self.rule_run,
            fingerprint="1" * 64,
            title="Possíveis faturas duplicadas",
            explanation="Foram encontradas duas faturas com os mesmos dados.",
            severity=Severity.MEDIUM,
            recommended_action="Comparar os documentos de origem.",
        )
        for invoice in (self.first_invoice, self.second_invoice):
            AlertEvidence.objects.create(
                organization=self.organization,
                alert=self.alert,
                invoice_record=invoice,
                facts={
                    "source_row_number": invoice.source_row_number,
                    "supplier_identifier": invoice.supplier_identifier,
                    "invoice_number": invoice.invoice_number,
                },
            )

        self.other_organization = Organization.objects.create(
            name="Outra Empresa",
            slug="outra-empresa-alertas",
        )
        other_user = get_user_model().objects.create_user(
            email="outra-empresa@example.com",
            password="password",
        )
        other_batch = self.create_import_batch(
            organization=self.other_organization,
            uploaded_by=other_user,
            filename="dados-confidenciais.csv",
            file_hash="b" * 64,
        )
        other_run = self.create_rule_run(
            organization=self.other_organization,
            import_batch=other_batch,
        )
        self.other_alert = Alert.objects.create(
            organization=self.other_organization,
            rule_run=other_run,
            fingerprint="2" * 64,
            title="Alerta de outra organização",
            explanation="Este conteúdo não pode ser mostrado.",
            severity=Severity.HIGH,
        )

        self.list_url = reverse(
            "alerts:list",
            kwargs={"organization_id": self.organization.id},
        )
        self.detail_url = reverse(
            "alerts:detail",
            kwargs={
                "organization_id": self.organization.id,
                "alert_id": self.alert.id,
            },
        )

    def create_import_batch(
        self,
        *,
        organization,
        uploaded_by,
        filename,
        file_hash,
    ):
        return ImportBatch.objects.create(
            organization=organization,
            uploaded_by=uploaded_by,
            original_filename=filename,
            file_sha256=file_hash,
            status=ImportBatch.Status.COMPLETED,
            row_count=2,
            valid_row_count=2,
        )

    def create_rule_run(self, *, organization, import_batch):
        return RuleRun.objects.create(
            organization=organization,
            import_batch=import_batch,
            rule_definition=self.rule_definition,
            status=RuleRun.Status.COMPLETED,
            alert_count=1,
        )

    def create_invoice(
        self,
        *,
        organization,
        import_batch,
        source_row_number,
        supplier_name,
    ):
        return InvoiceRecord.objects.create(
            organization=organization,
            import_batch=import_batch,
            source_row_number=source_row_number,
            supplier_identifier="PT500000001",
            supplier_name=supplier_name,
            invoice_number="FT 2026/100",
            normalized_invoice_number="FT 2026/100",
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal("1230.00"),
            currency="EUR",
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(self.list_url)

        expected_url = f"{reverse('login')}?next={self.list_url}"
        self.assertRedirects(response, expected_url)

    def test_viewer_can_list_only_alerts_from_own_organization(self):
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.alert.title)
        self.assertContains(response, self.detail_url)
        self.assertContains(response, self.import_batch.original_filename)
        self.assertNotContains(response, self.other_alert.title)
        self.assertNotContains(response, "dados-confidenciais.csv")

    def test_user_without_membership_cannot_list_alerts(self):
        outsider = get_user_model().objects.create_user(
            email="fora-dos-alertas@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_cannot_list_alerts(self):
        self.membership.is_active = False
        self.membership.save()
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_empty_organization_shows_empty_state(self):
        empty_organization = Organization.objects.create(
            name="Empresa sem Alertas",
            slug="empresa-sem-alertas",
        )
        Membership.objects.create(
            organization=empty_organization,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        empty_url = reverse(
            "alerts:list",
            kwargs={"organization_id": empty_organization.id},
        )
        self.client.force_login(self.user)

        response = self.client.get(empty_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ainda não existem alertas")

    def test_alert_list_is_paginated_at_25_rows(self):
        for index in range(25):
            Alert.objects.create(
                organization=self.organization,
                rule_run=self.rule_run,
                fingerprint=f"{index:064x}",
                title=f"Alerta adicional {index}",
                explanation="Resultado adicional para testar a paginação.",
                severity=Severity.LOW,
            )
        self.client.force_login(self.user)

        first_page = self.client.get(self.list_url)
        second_page = self.client.get(self.list_url, {"page": 2})

        self.assertEqual(first_page.context["page"].paginator.count, 26)
        self.assertEqual(len(first_page.context["page"].object_list), 25)
        self.assertEqual(len(second_page.context["page"].object_list), 1)

    def test_detail_shows_rule_explanation_action_and_all_evidence(self):
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.alert.title)
        self.assertContains(response, self.alert.explanation)
        self.assertContains(response, self.alert.recommended_action)
        self.assertContains(response, self.rule_definition.key)
        self.assertContains(response, self.import_batch.original_filename)
        self.assertContains(response, "Fornecedor Principal", count=2)
        self.assertContains(response, "FT 2026/100", count=4)
        self.assertContains(response, "1230,00", count=2)
        self.assertContains(response, "Não confirma, por si só, fraude")

    def test_detail_escapes_values_from_imported_data(self):
        self.first_invoice.supplier_name = "<script>alert('x')</script>"
        self.first_invoice.save()
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url)

        self.assertNotContains(response, "<script>alert('x')</script>")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;",
            html=False,
        )

    def test_alert_from_another_organization_is_not_accessible(self):
        other_detail_url = reverse(
            "alerts:detail",
            kwargs={
                "organization_id": self.organization.id,
                "alert_id": self.other_alert.id,
            },
        )
        self.client.force_login(self.user)

        response = self.client.get(other_detail_url)

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.other_alert.explanation, status_code=404)
