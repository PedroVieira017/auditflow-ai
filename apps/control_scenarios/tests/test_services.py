from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.audit_log.models import AuditEvent
from apps.organizations.models import Membership, Organization

from ..models import ControlScenario, ControlScenarioVersion
from ..services import (
    ControlScenarioApprovalError,
    DuplicateControlScenarioKeyError,
    approve_control_scenario_version,
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
        self.owner = get_user_model().objects.create_user(
            email="proprietario-service@example.com",
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
        self.owner_membership = Membership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=Membership.Role.OWNER,
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

    def test_owner_approves_immutable_snapshot_without_activating_scenario(self):
        version = create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )

        approved = approve_control_scenario_version(
            membership=self.owner_membership,
            approved_by=self.owner,
            scenario_id=version.scenario_id,
            version_id=version.id,
            effective_from=timezone.localdate(),
            approval_note="Revisei e aceitei a configuração deste controlo.",
        )

        self.assertEqual(approved.state, ControlScenarioVersion.State.APPROVED)
        self.assertEqual(approved.approved_by, self.owner)
        self.assertEqual(approved.approved_by_email, self.owner.email)
        self.assertEqual(approved.approved_by_role, Membership.Role.OWNER)
        self.assertEqual(len(approved.config_hash), 64)
        self.assertEqual(
            approved.config_hash,
            approved.to_contract_payload()["integrity"]["payload_hash"],
        )
        approved.scenario.refresh_from_db()
        self.assertIsNone(approved.scenario.active_version_id)

        event = AuditEvent.objects.get(action="control_scenario.approved")
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.resource_id, approved.id)
        self.assertEqual(event.metadata["config_hash"], approved.config_hash)
        self.assertFalse(event.metadata["creator_is_approver"])

    def test_analyst_cannot_approve_scenario(self):
        version = create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )

        with self.assertRaises(PermissionDenied):
            approve_control_scenario_version(
                membership=self.analyst_membership,
                approved_by=self.analyst,
                scenario_id=version.scenario_id,
                version_id=version.id,
                effective_from=timezone.localdate(),
                approval_note="Tentativa de aprovação por um analista.",
            )

        version.refresh_from_db()
        self.assertEqual(version.state, ControlScenarioVersion.State.DRAFT)
        self.assertFalse(
            AuditEvent.objects.filter(action="control_scenario.approved").exists()
        )

    def test_owner_can_approve_a_draft_created_by_the_same_owner(self):
        version = create_control_scenario_draft(
            membership=self.owner_membership,
            created_by=self.owner,
            data=scenario_data(),
        )

        approved = approve_control_scenario_version(
            membership=self.owner_membership,
            approved_by=self.owner,
            scenario_id=version.scenario_id,
            version_id=version.id,
            effective_from=timezone.localdate(),
            approval_note="Revisei e aceitei a configuração que preparei.",
        )

        self.assertEqual(approved.state, ControlScenarioVersion.State.APPROVED)
        event = AuditEvent.objects.get(action="control_scenario.approved")
        self.assertTrue(event.metadata["creator_is_approver"])

    def test_approved_version_cannot_be_approved_again(self):
        version = create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )
        approval = {
            "membership": self.owner_membership,
            "approved_by": self.owner,
            "scenario_id": version.scenario_id,
            "version_id": version.id,
            "effective_from": timezone.localdate(),
            "approval_note": "Revisei e aceitei a configuração deste controlo.",
        }
        approve_control_scenario_version(**approval)

        with self.assertRaises(ControlScenarioApprovalError):
            approve_control_scenario_version(**approval)

        self.assertEqual(
            AuditEvent.objects.filter(action="control_scenario.approved").count(),
            1,
        )

    def test_version_cannot_be_approved_through_another_scenario(self):
        version = create_control_scenario_draft(
            membership=self.analyst_membership,
            created_by=self.analyst,
            data=scenario_data(),
        )
        other_scenario = ControlScenario.objects.create(
            organization=self.organization,
            key="OTHER_SCENARIO",
        )

        with self.assertRaises(PermissionDenied):
            approve_control_scenario_version(
                membership=self.owner_membership,
                approved_by=self.owner,
                scenario_id=other_scenario.id,
                version_id=version.id,
                effective_from=timezone.localdate(),
                approval_note="Tentativa de aprovação no cenário errado.",
            )

        version.refresh_from_db()
        self.assertEqual(version.state, ControlScenarioVersion.State.DRAFT)
