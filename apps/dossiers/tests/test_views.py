import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.audit_log.models import AuditEvent
from apps.imports.models import ImportBatch
from apps.organizations.models import Membership, Organization

from ..services import generate_work_dossier_html


class WorkDossierDownloadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="analista-dossier@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa do Dossier",
            slug="empresa-do-dossier",
        )
        self.membership = Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        self.import_batch = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="faturas-agosto.csv",
            file_sha256="a" * 64,
            status=ImportBatch.Status.COMPLETED,
            row_count=4,
            valid_row_count=4,
            invalid_row_count=0,
            completed_at=datetime(2026, 8, 2, 9, 5, tzinfo=timezone.utc),
        )
        self.download_url = reverse(
            "dossiers:download",
            kwargs={
                "organization_id": self.organization.id,
                "batch_id": self.import_batch.id,
            },
        )
        self.import_detail_url = reverse(
            "imports:detail",
            kwargs={
                "organization_id": self.organization.id,
                "batch_id": self.import_batch.id,
            },
        )

    def create_dossier_event(
        self,
        *,
        actor=None,
        generation_id=None,
        import_batch=None,
        organization=None,
        payload_hash=None,
    ):
        generation_id = generation_id or uuid4()
        import_batch = import_batch or self.import_batch
        organization = organization or import_batch.organization
        payload_hash = payload_hash or generation_id.hex * 2
        return AuditEvent.objects.create(
            organization=organization,
            actor=actor or self.user,
            action="dossier.generated",
            resource_type="work_dossier",
            resource_id=generation_id,
            metadata={
                "contract": "auditflow-work-dossier-v1",
                "format": "html",
                "generation_id": str(generation_id),
                "import_batch_id": str(import_batch.id),
                "payload_hash": payload_hash,
            },
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.post(self.download_url)

        expected_url = f"{reverse('login')}?next={self.download_url}"
        self.assertRedirects(response, expected_url)
        self.assertFalse(AuditEvent.objects.exists())

    def test_download_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(self.download_url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(AuditEvent.objects.exists())

    def test_analyst_downloads_standalone_html_and_records_audit_event(self):
        generated_at = datetime(2026, 8, 2, 11, 30, tzinfo=timezone.utc)
        generation_id = UUID("99999999-9999-4999-8999-999999999999")
        self.client.force_login(self.user)

        with (
            patch(
                "apps.dossiers.services.timezone.now",
                return_value=generated_at,
            ),
            patch(
                "apps.dossiers.services.uuid.uuid4",
                return_value=generation_id,
            ),
        ):
            response = self.client.post(self.download_url)

        expected_filename = (
            "auditflow-dossier-empresa-do-dossier-20260802-"
            f"{self.import_batch.id}.html"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="{expected_filename}"',
        )
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertContains(response, "Dossier de análise de alertas")
        self.assertContains(response, "Não certificado", count=3)
        self.assertContains(response, "auditflow-work-dossier-v1")
        self.assertContains(response, self.organization.name)
        self.assertContains(response, self.import_batch.original_filename)
        self.assertNotContains(response, "<script")
        self.assertNotContains(response, "src=")

        event = AuditEvent.objects.get(action="dossier.generated")
        self.assertEqual(event.organization, self.organization)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.resource_type, "work_dossier")
        self.assertEqual(event.resource_id, generation_id)
        self.assertEqual(event.metadata["contract"], "auditflow-work-dossier-v1")
        self.assertEqual(event.metadata["format"], "html")
        self.assertEqual(event.metadata["generation_id"], str(generation_id))
        self.assertEqual(
            event.metadata["import_batch_id"],
            str(self.import_batch.id),
        )
        self.assertContains(response, event.metadata["payload_hash"], count=2)

    def test_owner_can_download_dossier(self):
        self.membership.role = Membership.Role.OWNER
        self.membership.save()
        self.client.force_login(self.user)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AuditEvent.objects.filter(action="dossier.generated").exists()
        )

    def test_viewer_cannot_download_or_create_audit_event(self):
        self.membership.role = Membership.Role.VIEWER
        self.membership.save()
        self.client.force_login(self.user)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditEvent.objects.exists())

    def test_user_without_membership_cannot_download(self):
        outsider = get_user_model().objects.create_user(
            email="fora-do-dossier@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AuditEvent.objects.exists())

    def test_inactive_membership_cannot_download(self):
        self.membership.is_active = False
        self.membership.save()
        self.client.force_login(self.user)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AuditEvent.objects.exists())

    def test_import_from_another_organization_is_not_accessible(self):
        other_organization = Organization.objects.create(
            name="Outra Empresa",
            slug="outra-empresa-dossier",
        )
        other_batch = ImportBatch.objects.create(
            organization=other_organization,
            uploaded_by=self.user,
            original_filename="dados-confidenciais.csv",
            file_sha256="b" * 64,
            status=ImportBatch.Status.COMPLETED,
            completed_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        )
        wrong_url = reverse(
            "dossiers:download",
            kwargs={
                "organization_id": self.organization.id,
                "batch_id": other_batch.id,
            },
        )
        self.client.force_login(self.user)

        response = self.client.post(wrong_url)

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(
            response,
            other_batch.original_filename,
            status_code=404,
        )
        self.assertFalse(AuditEvent.objects.exists())

    def test_incomplete_import_returns_conflict_without_audit_event(self):
        self.import_batch.status = ImportBatch.Status.PROCESSING
        self.import_batch.save()
        self.client.force_login(self.user)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            "os dados não são consistentes",
            status_code=409,
        )
        self.assertFalse(AuditEvent.objects.exists())

    def test_user_and_import_values_are_escaped_in_html(self):
        self.organization.name = "Empresa <script>alert('org')</script>"
        self.organization.save()
        self.import_batch.original_filename = "<script>alert('file')</script>.csv"
        self.import_batch.save()
        self.client.force_login(self.user)

        response = self.client.post(self.download_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<script>alert('org')</script>")
        self.assertNotContains(response, "<script>alert('file')</script>")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;org&#x27;)&lt;/script&gt;",
            html=False,
        )
        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;file&#x27;)&lt;/script&gt;.csv",
            html=False,
        )

    def test_failed_render_does_not_create_audit_event(self):
        with patch(
            "apps.dossiers.services.render_to_string",
            side_effect=RuntimeError("falha de apresentação"),
        ):
            with self.assertRaises(RuntimeError):
                generate_work_dossier_html(
                    import_batch=self.import_batch,
                    generated_by=self.user,
                )

        self.assertFalse(AuditEvent.objects.exists())

    def test_import_detail_shows_download_action_to_analyst(self):
        self.client.force_login(self.user)

        response = self.client.get(self.import_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descarregar dossier de trabalho")
        self.assertContains(response, self.download_url)
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_import_detail_shows_empty_dossier_history(self):
        self.client.force_login(self.user)

        response = self.client.get(self.import_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dossiers gerados")
        self.assertContains(
            response,
            "Ainda não foram gerados dossiers para esta importação.",
        )

    def test_generated_dossier_appears_in_import_history(self):
        generation_id = UUID("99999999-9999-4999-8999-999999999999")
        self.client.force_login(self.user)
        with patch(
            "apps.dossiers.services.uuid.uuid4",
            return_value=generation_id,
        ):
            download_response = self.client.post(self.download_url)

        event = AuditEvent.objects.get(action="dossier.generated")
        response = self.client.get(self.import_detail_url)

        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.email)
        self.assertContains(response, str(generation_id))
        self.assertContains(response, "auditflow-work-dossier-v1")
        self.assertContains(response, "html")
        self.assertContains(response, event.metadata["payload_hash"])

    def test_dossier_history_is_isolated_by_import_and_organization(self):
        other_batch = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="outra-importacao.csv",
            file_sha256="b" * 64,
            status=ImportBatch.Status.COMPLETED,
            completed_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        )
        other_organization = Organization.objects.create(
            name="Empresa Confidencial",
            slug="empresa-confidencial-dossier",
        )
        visible_event = self.create_dossier_event(payload_hash="a" * 64)
        hidden_import_event = self.create_dossier_event(
            import_batch=other_batch,
            payload_hash="b" * 64,
        )
        hidden_organization_event = self.create_dossier_event(
            organization=other_organization,
            payload_hash="c" * 64,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.import_detail_url)

        self.assertContains(response, visible_event.metadata["payload_hash"])
        self.assertNotContains(
            response,
            hidden_import_event.metadata["payload_hash"],
        )
        self.assertNotContains(
            response,
            hidden_organization_event.metadata["payload_hash"],
        )
        self.assertEqual(response.context["dossier_page"].paginator.count, 1)

    def test_dossier_history_is_paginated_at_twenty_events(self):
        for _ in range(21):
            self.create_dossier_event()
        self.client.force_login(self.user)

        first_page = self.client.get(self.import_detail_url)
        second_page = self.client.get(
            self.import_detail_url,
            {"dossier_page": 2},
        )

        self.assertEqual(first_page.context["dossier_page"].paginator.count, 21)
        self.assertEqual(
            len(first_page.context["dossier_page"].object_list),
            20,
        )
        self.assertEqual(
            len(second_page.context["dossier_page"].object_list),
            1,
        )
        self.assertContains(
            first_page,
            "?dossier_page=2#dossier-history",
        )

    def test_dossier_history_handles_a_removed_actor(self):
        removed_actor = get_user_model().objects.create_user(
            email="autor-removido@example.com",
            password="password",
        )
        self.create_dossier_event(actor=removed_actor)
        removed_actor.delete()
        self.client.force_login(self.user)

        response = self.client.get(self.import_detail_url)

        self.assertContains(response, "Utilizador removido")

    def test_import_detail_hides_download_action_from_viewer(self):
        event = self.create_dossier_event()
        self.membership.role = Membership.Role.VIEWER
        self.membership.save()
        self.client.force_login(self.user)

        response = self.client.get(self.import_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Descarregar dossier de trabalho")
        self.assertNotContains(response, self.download_url)
        self.assertContains(response, event.metadata["payload_hash"])


class WorkDossierTemplateTests(SimpleTestCase):
    def load_example_payload(self):
        example_path = (
            Path(settings.BASE_DIR)
            / "examples"
            / "dossier"
            / "dossier-trabalho-v1.example.json"
        )
        return json.loads(example_path.read_text(encoding="utf-8"))

    def test_complete_example_is_presented_in_html(self):
        payload = self.load_example_payload()

        content = render_to_string(
            "dossiers/work_dossier.html",
            {"dossier": payload},
        )

        alert = payload["alerts"][0]
        evidence = alert["evidence"][0]
        decision = alert["status_history"][0]
        self.assertIn(payload["organization"]["name"], content)
        self.assertIn(payload["rule_runs"][0]["rule"]["description"], content)
        self.assertIn(alert["title"], content)
        self.assertIn(alert["recommended_action"], content)
        self.assertIn(evidence["evidence_id"], content)
        self.assertIn(evidence["facts"]["invoice_number"], content)
        self.assertIn(decision["note"], content)
        self.assertIn(decision["event_id"], content)
        self.assertEqual(
            content.count(payload["integrity"]["payload_hash"]),
            2,
        )

    def test_alert_values_are_escaped_in_html(self):
        payload = self.load_example_payload()
        payload["alerts"][0]["title"] = "<script>alert('alerta')</script>"

        content = render_to_string(
            "dossiers/work_dossier.html",
            {"dossier": payload},
        )

        self.assertNotIn("<script>alert('alerta')</script>", content)
        self.assertIn(
            "&lt;script&gt;alert(&#x27;alerta&#x27;)&lt;/script&gt;",
            content,
        )
