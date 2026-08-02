from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit_log.models import AuditEvent
from apps.core.choices import Severity
from apps.imports.models import ImportBatch
from apps.organizations.models import Organization
from apps.rules.models import RuleDefinition, RuleRun

from ..models import Alert, AlertStatusEvent
from ..services import (
    AlertStatusChangeError,
    AlertStatusConflictError,
    change_alert_status,
)


class AlertStatusServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="analista-decisoes@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa das Decisões",
            slug="empresa-das-decisoes",
        )
        import_batch = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="faturas.csv",
            file_sha256="d" * 64,
            status=ImportBatch.Status.COMPLETED,
        )
        rule_definition = RuleDefinition.objects.create(
            key="TEST_RULE",
            version=1,
            name="Regra de teste",
            description="Regra usada para testar decisões.",
            default_severity=Severity.MEDIUM,
        )
        rule_run = RuleRun.objects.create(
            organization=self.organization,
            import_batch=import_batch,
            rule_definition=rule_definition,
            status=RuleRun.Status.COMPLETED,
            alert_count=1,
        )
        self.alert = Alert.objects.create(
            organization=self.organization,
            rule_run=rule_run,
            fingerprint="f" * 64,
            title="Alerta para análise",
            explanation="Existe uma exceção para analisar.",
            severity=Severity.MEDIUM,
        )

    def change_status(self, **overrides):
        parameters = {
            "alert": self.alert,
            "organization": self.organization,
            "changed_by": self.user,
            "to_status": Alert.Status.VALID,
            "note": "  Confirmei a exceção nos documentos.  ",
            "expected_status": Alert.Status.NEW,
        }
        parameters.update(overrides)
        return change_alert_status(**parameters)

    def test_change_status_persists_event_and_audit_log_atomically(self):
        updated_alert, status_event = self.change_status()

        self.alert.refresh_from_db()
        self.assertEqual(updated_alert.status, Alert.Status.VALID)
        self.assertEqual(self.alert.status, Alert.Status.VALID)
        self.assertEqual(status_event.organization, self.organization)
        self.assertEqual(status_event.alert, self.alert)
        self.assertEqual(status_event.changed_by, self.user)
        self.assertEqual(status_event.from_status, Alert.Status.NEW)
        self.assertEqual(status_event.to_status, Alert.Status.VALID)
        self.assertEqual(status_event.note, "Confirmei a exceção nos documentos.")

        audit_event = AuditEvent.objects.get(action="alert.status_changed")
        self.assertEqual(audit_event.organization, self.organization)
        self.assertEqual(audit_event.actor, self.user)
        self.assertEqual(audit_event.resource_id, self.alert.id)
        self.assertEqual(audit_event.metadata["from_status"], Alert.Status.NEW)
        self.assertEqual(audit_event.metadata["to_status"], Alert.Status.VALID)
        self.assertEqual(
            audit_event.metadata["status_event_id"],
            str(status_event.id),
        )

    def test_blank_note_is_rejected_without_changes(self):
        for note in (None, "", "   "):
            with self.subTest(note=note):
                with self.assertRaises(AlertStatusChangeError):
                    self.change_status(note=note)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.NEW)
        self.assertFalse(AlertStatusEvent.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_unknown_status_is_rejected_without_changes(self):
        with self.assertRaises(AlertStatusChangeError):
            self.change_status(to_status="unknown")

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.NEW)
        self.assertFalse(AlertStatusEvent.objects.exists())

    def test_same_status_is_rejected_without_changes(self):
        with self.assertRaises(AlertStatusChangeError):
            self.change_status(to_status=Alert.Status.NEW)

        self.assertFalse(AlertStatusEvent.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_stale_expected_status_is_rejected(self):
        with self.assertRaises(AlertStatusConflictError):
            self.change_status(expected_status=Alert.Status.VALID)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.NEW)
        self.assertFalse(AlertStatusEvent.objects.exists())

    def test_alert_from_another_organization_is_rejected(self):
        other_organization = Organization.objects.create(
            name="Organização Incorreta",
            slug="organizacao-incorreta",
        )

        with self.assertRaises(AlertStatusChangeError):
            self.change_status(organization=other_organization)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.NEW)
        self.assertFalse(AlertStatusEvent.objects.exists())

    def test_audit_log_failure_rolls_back_status_and_history(self):
        with patch(
            "apps.alerts.services.AuditEvent.objects.create",
            side_effect=RuntimeError("audit log unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.change_status()

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.NEW)
        self.assertFalse(AlertStatusEvent.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
