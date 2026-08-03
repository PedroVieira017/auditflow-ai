from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit_log.models import AuditEvent
from apps.organizations.models import Membership, Organization

from ..models import ControlScenario, ControlScenarioVersion


def form_data(**overrides):
    data = {
        "key": "AP_DUPLICATE_INVOICE_REVIEW",
        "name": "Revisão de duplicação de faturas",
        "description": "Monitorização das exceções do processo de pagamentos.",
        "change_reason": "Configuração inicial do controlo.",
        "objective_category": "operations",
        "objective_statement": "Evitar pagamentos repetidos.",
        "risk_statement": "Uma obrigação pode ser paga mais do que uma vez.",
        "control_name": "Revisão de duplicados",
        "control_description": "Investigar as exceções antes do pagamento.",
        "control_type": "detective",
        "control_frequency": "per_import",
        "control_owner_role": "Responsável de contas a pagar",
        "reviewer_role": "Responsável financeiro",
        "review_due_days": "5",
        "indicator_target": "0.00",
        "rule_severity": "medium",
    }
    data.update(overrides)
    return data


class ControlScenarioViewsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Empresa de Cenários",
            slug="empresa-de-cenarios-views",
        )
        self.other_organization = Organization.objects.create(
            name="Empresa Confidencial",
            slug="empresa-confidencial-cenarios",
        )
        self.owner = get_user_model().objects.create_user(
            email="proprietario-views@example.com",
            password="password",
        )
        self.analyst = get_user_model().objects.create_user(
            email="analista-views@example.com",
            password="password",
        )
        self.viewer = get_user_model().objects.create_user(
            email="leitor-views@example.com",
            password="password",
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=Membership.Role.OWNER,
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.analyst,
            role=Membership.Role.ANALYST,
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.viewer,
            role=Membership.Role.VIEWER,
        )
        self.list_url = reverse(
            "control_scenarios:list",
            kwargs={"organization_id": self.organization.id},
        )
        self.create_url = reverse(
            "control_scenarios:create",
            kwargs={"organization_id": self.organization.id},
        )

    def create_draft_through_view(self):
        self.client.force_login(self.analyst)
        response = self.client.post(self.create_url, form_data())
        return response, ControlScenario.objects.get()

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(self.list_url)

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={self.list_url}",
        )

    def test_empty_list_guides_owner_to_create_first_scenario(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ainda não existem cenários")
        self.assertContains(response, self.create_url)

    def test_viewer_can_list_but_cannot_open_creation_flow(self):
        self.client.force_login(self.viewer)

        list_response = self.client.get(self.list_url)
        create_response = self.client.get(self.create_url)

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, "Criar primeiro cenário")
        self.assertEqual(create_response.status_code, 403)

    def test_analyst_creates_draft_and_is_redirected_to_detail(self):
        response, scenario = self.create_draft_through_view()

        detail_url = reverse(
            "control_scenarios:detail",
            kwargs={
                "organization_id": self.organization.id,
                "scenario_id": scenario.id,
            },
        )
        self.assertRedirects(response, detail_url)
        version = ControlScenarioVersion.objects.get()
        self.assertEqual(version.created_by, self.analyst)
        self.assertEqual(version.created_by_role, Membership.Role.ANALYST)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="control_scenario.draft_created",
                resource_id=version.id,
            ).exists()
        )

    def test_detail_presents_objective_risk_control_rule_and_governance(self):
        _, scenario = self.create_draft_through_view()
        detail_url = reverse(
            "control_scenarios:detail",
            kwargs={
                "organization_id": self.organization.id,
                "scenario_id": scenario.id,
            },
        )

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Evitar pagamentos repetidos.")
        self.assertContains(
            response,
            "Uma obrigação pode ser paga mais do que uma vez.",
        )
        self.assertContains(response, "Revisão de duplicados")
        self.assertContains(response, "DUPLICATE_INVOICE_EXACT")
        self.assertContains(response, "Rascunho não executável")
        self.assertContains(response, self.analyst.email)

    def test_duplicate_key_returns_form_error(self):
        self.client.force_login(self.analyst)
        self.client.post(self.create_url, form_data())

        response = self.client.post(self.create_url, form_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Já existe um cenário com esta chave na organização.",
        )
        self.assertEqual(ControlScenario.objects.count(), 1)

    def test_scenario_from_another_organization_is_not_visible(self):
        scenario = ControlScenario.objects.create(
            organization=self.other_organization,
            key="CONFIDENTIAL_SCENARIO",
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "control_scenarios:detail",
                kwargs={
                    "organization_id": self.organization.id,
                    "scenario_id": scenario.id,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_user_without_membership_cannot_access_organization(self):
        outsider = get_user_model().objects.create_user(
            email="fora-cenarios@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)
