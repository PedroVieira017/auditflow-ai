from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Membership, Organization

from ..models import AuditEvent


class AuditEventListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="leitor-auditoria@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa Auditada",
            slug="empresa-auditada",
        )
        self.membership = Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.VIEWER,
        )
        self.other_organization = Organization.objects.create(
            name="Empresa Confidencial",
            slug="empresa-confidencial-auditoria",
        )
        self.list_url = reverse(
            "audit_log:list",
            kwargs={"organization_id": self.organization.id},
        )

    def create_event(
        self,
        *,
        action="import.created",
        actor=None,
        metadata=None,
        organization=None,
        resource_type="import_batch",
    ):
        return AuditEvent.objects.create(
            organization=organization or self.organization,
            actor=actor or self.user,
            action=action,
            resource_type=resource_type,
            resource_id=uuid4(),
            metadata=metadata or {},
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(self.list_url)

        expected_url = f"{reverse('login')}?next={self.list_url}"
        self.assertRedirects(response, expected_url)

    def test_viewer_sees_known_events_and_only_whitelisted_details(self):
        events = (
            (
                "import.created",
                "Importação criada",
                {
                    "original_filename": "faturas.csv",
                    "contract_version": "invoice-csv-v1",
                    "size_bytes": 1024,
                    "file_sha256": "a" * 64,
                    "internal_storage_key": "segredo-storage",
                },
                "import_batch",
            ),
            (
                "import.processed",
                "Importação processada",
                {"row_count": 10},
                "import_batch",
            ),
            (
                "import.validation_failed",
                "Validação da importação falhou",
                {
                    "row_count": 12,
                    "valid_row_count": 0,
                    "invalid_row_count": 12,
                    "error_count": 14,
                    "stored_error_count": 14,
                },
                "import_batch",
            ),
            (
                "rule_run.completed",
                "Execução de regra concluída",
                {
                    "rule_key": "DUPLICATE_INVOICE_EXACT",
                    "rule_version": 1,
                    "alert_count": 2,
                },
                "rule_run",
            ),
            (
                "rule_run.failed",
                "Execução de regra falhou",
                {
                    "rule_key": "DUPLICATE_INVOICE_EXACT",
                    "rule_version": 1,
                    "error_message": "password=segredo-tecnico",
                },
                "rule_run",
            ),
            (
                "alert.status_changed",
                "Estado do alerta alterado",
                {
                    "from_status": "new",
                    "to_status": "valid",
                    "status_event_id": str(uuid4()),
                },
                "alert",
            ),
            (
                "dossier.generated",
                "Dossier gerado",
                {
                    "contract": "auditflow-work-dossier-v1",
                    "format": "html",
                    "import_batch_id": str(uuid4()),
                    "payload_hash": "b" * 64,
                },
                "work_dossier",
            ),
        )
        for action, _, metadata, resource_type in events:
            self.create_event(
                action=action,
                metadata=metadata,
                resource_type=resource_type,
            )
        self.create_event(
            organization=self.other_organization,
            metadata={"original_filename": "confidencial.csv"},
        )
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, len(events))
        for action, label, _, _ in events:
            with self.subTest(action=action):
                self.assertContains(response, action)
                self.assertContains(response, label)
        self.assertContains(response, "faturas.csv")
        self.assertContains(response, "DUPLICATE_INVOICE_EXACT", count=2)
        self.assertContains(response, "auditflow-work-dossier-v1")
        self.assertNotContains(response, "segredo-storage")
        self.assertNotContains(response, "segredo-tecnico")
        self.assertNotContains(response, "confidencial.csv")

    def test_unknown_event_shows_action_but_hides_unknown_metadata(self):
        event = self.create_event(
            action="system.unknown_action",
            metadata={"secret": "valor-confidencial"},
            resource_type="unknown_resource",
        )
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertContains(response, event.action, count=2)
        self.assertContains(response, event.resource_type)
        self.assertContains(response, "Sem detalhes adicionais.")
        self.assertNotContains(response, "valor-confidencial")

    def test_events_can_be_filtered_by_action(self):
        import_event = self.create_event(
            metadata={"original_filename": "faturas.csv"},
        )
        dossier_event = self.create_event(
            action="dossier.generated",
            metadata={
                "contract": "auditflow-work-dossier-v1",
                "payload_hash": "d" * 64,
            },
            resource_type="work_dossier",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            self.list_url,
            {"action": "dossier.generated"},
        )

        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertContains(response, str(dossier_event.resource_id))
        self.assertNotContains(response, str(import_event.resource_id))
        self.assertTrue(response.context["filters_applied"])

    def test_invalid_filter_is_rejected_without_exposing_other_organization(self):
        own_event = self.create_event(metadata={"original_filename": "proprio.csv"})
        other_event = self.create_event(
            organization=self.other_organization,
            metadata={"original_filename": "confidencial.csv"},
        )
        self.client.force_login(self.user)

        response = self.client.get(self.list_url, {"action": "invalid.action"})

        self.assertTrue(response.context["filter_form"].errors)
        self.assertFalse(response.context["filters_applied"])
        self.assertContains(response, str(own_event.resource_id))
        self.assertNotContains(response, str(other_event.resource_id))
        self.assertNotContains(response, "confidencial.csv")

    def test_filtered_history_is_paginated_at_twenty_five_events(self):
        for index in range(26):
            self.create_event(
                action="dossier.generated",
                metadata={"payload_hash": f"{index:064x}"},
                resource_type="work_dossier",
            )
        self.client.force_login(self.user)

        first_page = self.client.get(
            self.list_url,
            {"action": "dossier.generated"},
        )
        second_page = self.client.get(
            self.list_url,
            {"action": "dossier.generated", "page": 2},
        )

        self.assertEqual(first_page.context["page"].paginator.count, 26)
        self.assertEqual(len(first_page.context["entries"]), 25)
        self.assertEqual(len(second_page.context["entries"]), 1)
        self.assertContains(
            first_page,
            "action=dossier.generated&amp;page=2",
            html=False,
        )

    def test_removed_actor_is_identified(self):
        removed_actor = get_user_model().objects.create_user(
            email="autor-removido-auditoria@example.com",
            password="password",
        )
        self.create_event(actor=removed_actor)
        removed_actor.delete()
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertContains(response, "Utilizador removido")

    def test_metadata_values_are_escaped(self):
        self.create_event(
            metadata={
                "original_filename": "<script>alert('audit')</script>.csv",
            }
        )
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertNotContains(response, "<script>alert('audit')</script>")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;audit&#x27;)&lt;/script&gt;.csv",
            html=False,
        )

    def test_empty_organization_shows_empty_state(self):
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertContains(
            response,
            "Ainda não existem eventos de auditoria nesta organização.",
        )

    def test_user_without_membership_cannot_access_audit_log(self):
        outsider = get_user_model().objects.create_user(
            email="fora-auditoria@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_inactive_organization_cannot_be_accessed(self):
        self.organization.is_active = False
        self.organization.save()
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_post_requests_are_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(self.list_url)

        self.assertEqual(response.status_code, 405)

    def test_navigation_contains_audit_log_link(self):
        self.client.force_login(self.user)

        response = self.client.get(self.list_url)

        self.assertContains(response, self.list_url)
        self.assertContains(response, "Registo de auditoria")
