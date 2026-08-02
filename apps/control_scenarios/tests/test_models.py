import copy
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.organizations.models import Membership, Organization

from ..contracts import calculate_payload_hash
from ..models import ControlScenario, ControlScenarioVersion


class ControlScenarioModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        example_path = (
            Path(settings.BASE_DIR)
            / "examples"
            / "control_scenarios"
            / "cenario-controlo-v1.example.json"
        )
        cls.example = json.loads(example_path.read_text(encoding="utf-8"))

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="proprietario-cenarios@example.com",
            password="password",
        )
        self.analyst = get_user_model().objects.create_user(
            email="analista-cenarios@example.com",
            password="password",
        )
        self.viewer = get_user_model().objects.create_user(
            email="leitor-cenarios@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa dos Cenários",
            slug="empresa-dos-cenarios",
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
        self.scenario = ControlScenario.objects.create(
            organization=self.organization,
            key="AP_DUPLICATE_INVOICE_REVIEW",
        )

    def configuration(self):
        return {
            section: copy.deepcopy(self.example[section])
            for section in (
                "control",
                "limitations",
                "monitoring",
                "objective",
                "risk",
                "rules",
            )
        }

    def create_draft(
        self,
        *,
        scenario=None,
        organization=None,
        version=1,
        supersedes=None,
        created_by=None,
        created_by_role=Membership.Role.ANALYST,
        include_configuration=True,
    ):
        scenario = scenario or self.scenario
        organization = organization or self.organization
        created_by = created_by or self.analyst
        configuration = self.configuration() if include_configuration else {}
        return ControlScenarioVersion.objects.create(
            organization=organization,
            scenario=scenario,
            version=version,
            organization_name=organization.name,
            name="Revisão de duplicação de faturas",
            description=(
                "Monitorização das exceções ao procedimento de pagamentos."
            ),
            objective=configuration.get("objective", {}),
            risk=configuration.get("risk", {}),
            control=configuration.get("control", {}),
            monitoring=configuration.get("monitoring", {}),
            rules=configuration.get("rules", []),
            limitations=configuration.get("limitations", []),
            created_by=created_by,
            created_by_email=created_by.email,
            created_by_user_id=created_by.id,
            created_by_role=created_by_role,
            change_reason="Configuração inicial do cenário.",
            supersedes=supersedes,
        )

    def approve(
        self,
        version,
        *,
        approved_by=None,
        approved_by_role=Membership.Role.OWNER,
        approved_at=None,
        effective_from=None,
    ):
        approved_by = approved_by or self.owner
        approved_at = approved_at or timezone.now()
        version.state = ControlScenarioVersion.State.APPROVED
        version.approved_by = approved_by
        version.approved_by_email = approved_by.email
        version.approved_by_user_id = approved_by.id
        version.approved_by_role = approved_by_role
        version.approved_at = approved_at
        version.effective_from = effective_from or approved_at.date()
        version.approval_note = "Configuração revista e aprovada."
        version.save()
        version.refresh_from_db()
        return version

    def test_valid_draft_can_be_incomplete_edited_and_deleted(self):
        draft = self.create_draft(include_configuration=False)

        draft.name = "Novo nome do rascunho"
        draft.save()
        draft_id = draft.id
        draft.delete()

        self.assertFalse(
            ControlScenarioVersion.objects.filter(id=draft_id).exists()
        )

    def test_creator_must_be_active_owner_or_analyst(self):
        with self.assertRaises(ValidationError):
            self.create_draft(
                created_by=self.viewer,
                created_by_role=Membership.Role.VIEWER,
            )

    def test_scenario_key_is_unique_per_organization_and_immutable(self):
        with self.assertRaises(ValidationError):
            ControlScenario.objects.create(
                organization=self.organization,
                key=self.scenario.key,
            )

        other_organization = Organization.objects.create(
            name="Outra Empresa",
            slug="outra-empresa-cenarios",
        )
        other_scenario = ControlScenario.objects.create(
            organization=other_organization,
            key=self.scenario.key,
        )
        self.assertEqual(other_scenario.key, self.scenario.key)

        self.scenario.key = "NEW_KEY"
        with self.assertRaises(ValidationError):
            self.scenario.save()

    def test_database_enforces_scenario_key_uniqueness(self):
        duplicate = ControlScenario(
            organization=self.organization,
            key=self.scenario.key,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ControlScenario.objects.bulk_create([duplicate])

    def test_version_must_belong_to_scenario_organization(self):
        other_organization = Organization.objects.create(
            name="Organização Incorreta",
            slug="organizacao-incorreta-cenarios",
        )
        Membership.objects.create(
            organization=other_organization,
            user=self.analyst,
            role=Membership.Role.ANALYST,
        )

        with self.assertRaises(ValidationError):
            self.create_draft(organization=other_organization)

    def test_version_lineage_is_consecutive_and_cannot_branch(self):
        first = self.approve(self.create_draft())
        second = self.create_draft(
            version=2,
            supersedes=first,
        )
        self.approve(second)

        with self.assertRaises(ValidationError):
            self.create_draft(version=3, supersedes=first)
        with self.assertRaises(ValidationError):
            self.create_draft(version=2, supersedes=first)

    def test_approved_version_builds_contract_payload_and_hash(self):
        version = self.approve(self.create_draft())

        payload = version.to_contract_payload()

        self.assertEqual(payload["contract"], "auditflow-control-scenario-v1")
        self.assertEqual(payload["scenario"]["id"], str(self.scenario.id))
        self.assertEqual(payload["scenario"]["version_id"], str(version.id))
        self.assertEqual(payload["scenario"]["version"], 1)
        self.assertEqual(payload["organization"]["id"], str(self.organization.id))
        self.assertEqual(
            payload["governance"]["approved_by"],
            {
                "email": self.owner.email,
                "role": Membership.Role.OWNER,
                "user_id": str(self.owner.id),
            },
        )
        self.assertEqual(
            payload["integrity"]["payload_hash"],
            calculate_payload_hash(payload),
        )
        self.assertEqual(version.config_hash, payload["integrity"]["payload_hash"])

    def test_version_cannot_be_created_directly_as_approved(self):
        configuration = self.configuration()
        version = ControlScenarioVersion(
            organization=self.organization,
            scenario=self.scenario,
            version=1,
            state=ControlScenarioVersion.State.APPROVED,
            organization_name=self.organization.name,
            name="Cenário",
            description="Descrição do cenário.",
            objective=configuration["objective"],
            risk=configuration["risk"],
            control=configuration["control"],
            monitoring=configuration["monitoring"],
            rules=configuration["rules"],
            limitations=configuration["limitations"],
            created_by=self.analyst,
            created_by_email=self.analyst.email,
            created_by_user_id=self.analyst.id,
            created_by_role=Membership.Role.ANALYST,
            approved_by=self.owner,
            approved_by_email=self.owner.email,
            approved_by_user_id=self.owner.id,
            approved_by_role=Membership.Role.OWNER,
            approved_at=timezone.now(),
            effective_from=timezone.localdate(),
            approval_note="Aprovado.",
            change_reason="Configuração inicial.",
        )

        with self.assertRaises(ValidationError):
            version.save()

    def test_only_active_owner_can_approve(self):
        draft = self.create_draft()

        with self.assertRaises(ValidationError):
            self.approve(
                draft,
                approved_by=self.analyst,
                approved_by_role=Membership.Role.OWNER,
            )

        draft.refresh_from_db()
        self.assertEqual(draft.state, ControlScenarioVersion.State.DRAFT)
        self.assertEqual(draft.config_hash, "")

    def test_invalid_contract_configuration_cannot_be_approved(self):
        draft = self.create_draft()
        draft.rules[0]["key"] = "UNREGISTERED_RULE"

        with self.assertRaises(ValidationError):
            self.approve(draft)

        draft.refresh_from_db()
        self.assertEqual(draft.state, ControlScenarioVersion.State.DRAFT)

    def test_unregistered_metric_cannot_be_approved(self):
        draft = self.create_draft()
        draft.monitoring["indicators"][0]["measurement"]["metric_key"] = (
            "UNREGISTERED_METRIC"
        )

        with self.assertRaises(ValidationError):
            self.approve(draft)

        draft.refresh_from_db()
        self.assertEqual(draft.state, ControlScenarioVersion.State.DRAFT)

    def test_approved_version_is_immutable_and_cannot_be_deleted(self):
        version = self.approve(self.create_draft())
        version.objective = {
            "category": "operations",
            "statement": "Objetivo alterado depois da aprovação.",
        }

        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            ControlScenarioVersion.objects.filter(id=version.id).update(
                objective=version.objective
            )
        with self.assertRaises(ValidationError):
            version.delete()
        with self.assertRaises(ValidationError):
            ControlScenarioVersion.objects.filter(id=version.id).delete()

    def test_version_identity_is_immutable_while_draft(self):
        draft = self.create_draft()
        draft.version = 2

        with self.assertRaises(ValidationError):
            draft.save()
        with self.assertRaises(ValidationError):
            ControlScenarioVersion.objects.filter(id=draft.id).update(version=2)

    def test_queryset_cannot_bypass_approval_validation(self):
        draft = self.create_draft()

        with self.assertRaises(ValidationError):
            ControlScenarioVersion.objects.filter(id=draft.id).update(
                state=ControlScenarioVersion.State.APPROVED
            )

    def test_only_effective_approved_version_can_be_activated(self):
        approved = self.approve(self.create_draft())
        self.scenario.active_version = approved
        self.scenario.save()
        self.scenario.refresh_from_db()
        self.assertEqual(self.scenario.active_version, approved)

        future = self.create_draft(version=2, supersedes=approved)
        future = self.approve(
            future,
            effective_from=timezone.localdate() + timedelta(days=1),
        )
        self.scenario.active_version = future
        with self.assertRaises(ValidationError):
            self.scenario.save()

    def test_version_from_another_scenario_cannot_be_activated(self):
        other_scenario = ControlScenario.objects.create(
            organization=self.organization,
            key="OTHER_CONTROL_SCENARIO",
        )
        other_version = self.approve(
            self.create_draft(scenario=other_scenario)
        )
        self.scenario.active_version = other_version

        with self.assertRaises(ValidationError):
            self.scenario.save()

    def test_user_deletion_preserves_approval_snapshot_and_hash(self):
        version = self.approve(self.create_draft())
        original_hash = version.config_hash
        owner_id = self.owner.id
        analyst_id = self.analyst.id

        self.owner.delete()
        self.analyst.delete()
        version.refresh_from_db()
        payload = version.to_contract_payload()

        self.assertIsNone(version.created_by)
        self.assertIsNone(version.approved_by)
        self.assertEqual(
            payload["governance"]["created_by"]["user_id"],
            str(analyst_id),
        )
        self.assertEqual(
            payload["governance"]["approved_by"]["user_id"],
            str(owner_id),
        )
        self.assertEqual(payload["integrity"]["payload_hash"], original_hash)
