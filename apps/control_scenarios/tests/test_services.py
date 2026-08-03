from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.audit_log.models import AuditEvent
from apps.organizations.models import Membership, Organization

from ..models import ControlScenario, ControlScenarioVersion
from ..services import (
    DuplicateControlScenarioKeyError,
    create_control_scenario_draft,
)


def scenario_data():
    return {
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
        "review_due_days": 5,
        "indicator_target": Decimal("0.00"),
        "rule_severity": "medium",
    }


class ControlScenarioDraftServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Empresa de Cenários",
            slug="empresa-de-cenarios-service",
        )
        self.analyst = get_user_model().objects.create_user(
            email="analista-service@example.com",
            password="password",
        )
        self.viewer = get_user_model().objects.create_user(
            email="leitor-service@example.com",
            password="password",
        )
        self.analyst_membership = Membership.objects.create(
            organization=self.organization,
            user=self.analyst,
            role=Membership.Role.ANALYST,
        )
        self.viewer_membership = Membership.objects.create(
            organization=self.organization,
            user=self.viewer,
            role=Membership.Role.VIEWER,
        )

    def test_creates_complete_draft_and_audit_event(self):
        version = create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )

        self.assertEqual(ControlScenario.objects.count(), 1)
        self.assertEqual(ControlScenarioVersion.objects.count(), 1)
        self.assertEqual(version.state, ControlScenarioVersion.State.DRAFT)
        self.assertEqual(version.created_by_email, self.analyst.email)
        self.assertEqual(version.created_by_role, Membership.Role.ANALYST)
        self.assertEqual(version.objective["category"], "operations")
        self.assertEqual(version.rules[0]["key"], "DUPLICATE_INVOICE_EXACT")
        self.assertEqual(
            version.monitoring["indicators"][0]["target"]["value"],
            "0.00",
        )
        self.assertEqual(len(version.limitations), 4)

        event = AuditEvent.objects.get(
            action="control_scenario.draft_created"
        )
        self.assertEqual(event.organization, self.organization)
        self.assertEqual(event.actor, self.analyst)
        self.assertEqual(event.resource_id, version.id)
        self.assertEqual(
            event.metadata["scenario_key"],
            "AP_DUPLICATE_INVOICE_REVIEW",
        )

    def test_viewer_cannot_create_draft(self):
        with self.assertRaises(PermissionDenied):
            create_control_scenario_draft(
                membership=self.viewer_membership,
                created_by=self.viewer,
                data=scenario_data(),
            )

        self.assertFalse(ControlScenario.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_duplicate_key_is_rejected_without_partial_data(self):
        create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )

        with self.assertRaises(DuplicateControlScenarioKeyError):
            create_control_scenario_draft(
                membership=self.analyst_membership,
                created_by=self.analyst,
                data=scenario_data(),
            )

        self.assertEqual(ControlScenario.objects.count(), 1)
        self.assertEqual(ControlScenarioVersion.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)
