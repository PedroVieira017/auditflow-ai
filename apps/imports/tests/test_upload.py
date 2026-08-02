import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.audit_log.models import AuditEvent
from apps.core.middleware import RequestBodySizeLimitMiddleware
from apps.invoices.models import InvoiceRecord
from apps.organizations.models import Membership, Organization

from ..contracts import INVOICE_CSV_MAX_FILE_SIZE_BYTES
from ..models import ImportBatch


class InvoiceCSVUploadTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory.name,
        )
        self.settings_override.enable()

        self.user = get_user_model().objects.create_user(
            email="analista-upload@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa Upload",
            slug="empresa-upload",
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        self.upload_url = reverse(
            "imports:upload",
            kwargs={"organization_id": self.organization.id},
        )
        self.valid_csv = (
            Path(settings.BASE_DIR) / "examples" / "csv" / "faturas_validas.csv"
        ).read_bytes()

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()

    def uploaded_file(self, name="faturas.csv", content=None):
        return SimpleUploadedFile(
            name,
            self.valid_csv if content is None else content,
            content_type="text/csv",
        )

    def test_authenticated_analyst_can_upload_csv(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file()},
        )

        import_batch = ImportBatch.objects.get()
        expected_url = reverse(
            "imports:detail",
            kwargs={
                "organization_id": self.organization.id,
                "batch_id": import_batch.id,
            },
        )
        self.assertRedirects(response, expected_url)
        self.assertEqual(import_batch.organization, self.organization)
        self.assertEqual(import_batch.uploaded_by, self.user)
        self.assertEqual(import_batch.original_filename, "faturas.csv")
        self.assertEqual(import_batch.status, ImportBatch.Status.PENDING)
        self.assertRegex(
            import_batch.storage_key,
            rf"^organizations/{self.organization.id}/imports/[0-9a-f]{{32}}\.csv$",
        )
        self.assertNotIn(import_batch.original_filename, import_batch.storage_key)
        self.assertTrue(
            (Path(self.media_directory.name) / import_batch.storage_key).is_file()
        )
        self.assertEqual(InvoiceRecord.objects.count(), 0)

        audit_event = AuditEvent.objects.get(action="import.created")
        self.assertEqual(audit_event.organization, self.organization)
        self.assertEqual(audit_event.actor, self.user)
        self.assertEqual(audit_event.resource_id, import_batch.id)
        self.assertEqual(
            audit_event.metadata["size_bytes"],
            len(self.valid_csv),
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(self.upload_url)

        expected_login_url = f"{reverse('login')}?next={self.upload_url}"
        self.assertRedirects(response, expected_login_url)

    def test_viewer_cannot_upload_files(self):
        membership = Membership.objects.get(
            organization=self.organization,
            user=self.user,
        )
        membership.role = Membership.Role.VIEWER
        membership.save()
        self.client.force_login(self.user)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file()},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ImportBatch.objects.exists())

    def test_user_without_membership_cannot_access_organization(self):
        outsider = get_user_model().objects.create_user(
            email="fora@example.com",
            password="password",
        )
        self.client.force_login(outsider)

        response = self.client.get(self.upload_url)

        self.assertEqual(response.status_code, 404)

    def test_non_csv_extension_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(name="faturas.exe")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "extensao .csv")
        self.assertFalse(ImportBatch.objects.exists())

    def test_file_larger_than_contract_limit_is_rejected(self):
        self.client.force_login(self.user)
        oversized_content = b"x" * (INVOICE_CSV_MAX_FILE_SIZE_BYTES + 1)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(content=oversized_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "excede o limite de 10 MiB")
        self.assertFalse(ImportBatch.objects.exists())

    def test_binary_file_with_csv_extension_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(content=b"coluna\x00valor")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dados binarios")
        self.assertFalse(ImportBatch.objects.exists())

    def test_invalid_utf8_file_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(content=b"coluna;valor\n\xff;100")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "codificacao UTF-8")
        self.assertFalse(ImportBatch.objects.exists())

    def test_post_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            self.upload_url,
            {"file": self.uploaded_file()},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ImportBatch.objects.exists())

    def test_duplicate_file_is_not_stored_twice(self):
        self.client.force_login(self.user)
        first_response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(name="primeiro.csv")},
        )

        self.assertEqual(first_response.status_code, 302)

        second_response = self.client.post(
            self.upload_url,
            {"file": self.uploaded_file(name="segundo.csv")},
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, "ja foi carregado")
        self.assertEqual(ImportBatch.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="import.created").count(), 1)
        stored_files = [
            path
            for path in Path(self.media_directory.name).rglob("*")
            if path.is_file()
        ]
        self.assertEqual(len(stored_files), 1)

    def test_import_detail_cannot_cross_organization_boundary(self):
        self.client.force_login(self.user)
        self.client.post(
            self.upload_url,
            {"file": self.uploaded_file()},
        )
        import_batch = ImportBatch.objects.get()
        other_organization = Organization.objects.create(
            name="Outra Empresa",
            slug="outra-empresa-upload",
        )
        Membership.objects.create(
            organization=other_organization,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        wrong_organization_url = reverse(
            "imports:detail",
            kwargs={
                "organization_id": other_organization.id,
                "batch_id": import_batch.id,
            },
        )

        response = self.client.get(wrong_organization_url)

        self.assertEqual(response.status_code, 404)


class RequestBodySizeLimitMiddlewareTests(TestCase):
    def test_oversized_request_is_rejected_before_view(self):
        middleware = RequestBodySizeLimitMiddleware(
            lambda request: self.fail("A view nao deveria ser executada.")
        )
        request = RequestFactory().post("/imports/new/")
        request.META["CONTENT_LENGTH"] = str(
            settings.MAX_REQUEST_BODY_SIZE_BYTES + 1
        )

        response = middleware(request)

        self.assertEqual(response.status_code, 413)
