import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit_log.models import AuditEvent
from apps.invoices.models import InvoiceRecord
from apps.organizations.models import Membership, Organization

from ..models import ImportBatch
from ..processing import MAX_STORED_ERRORS, process_import_batch


class ImportProcessingTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory.name,
        )
        self.settings_override.enable()
        self.examples_dir = Path(settings.BASE_DIR) / "examples" / "csv"
        self.user = get_user_model().objects.create_user(
            email="processamento@example.com",
            password="password",
        )
        self.organization = Organization.objects.create(
            name="Empresa Processamento",
            slug="empresa-processamento",
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.ANALYST,
        )
        self.client.force_login(self.user)
        self.upload_url = reverse(
            "imports:upload",
            kwargs={"organization_id": self.organization.id},
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()

    def upload(self, content, filename="faturas.csv"):
        return self.client.post(
            self.upload_url,
            {
                "file": SimpleUploadedFile(
                    filename,
                    content,
                    content_type="text/csv",
                )
            },
        )

    def test_valid_file_is_parsed_and_persisted(self):
        content = (self.examples_dir / "faturas_validas.csv").read_bytes()

        response = self.upload(content)

        self.assertEqual(response.status_code, 302)
        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.status, ImportBatch.Status.COMPLETED)
        self.assertEqual(import_batch.row_count, 6)
        self.assertEqual(import_batch.valid_row_count, 6)
        self.assertEqual(import_batch.invalid_row_count, 0)
        self.assertEqual(import_batch.error_summary, [])
        self.assertIsNotNone(import_batch.started_at)
        self.assertIsNotNone(import_batch.completed_at)
        self.assertEqual(
            InvoiceRecord.objects.filter(import_batch=import_batch).count(),
            6,
        )

    def test_original_values_are_preserved_and_matching_value_is_normalized(self):
        content = (self.examples_dir / "faturas_validas.csv").read_bytes()
        self.upload(content)
        import_batch = ImportBatch.objects.get()

        first_invoice = InvoiceRecord.objects.get(
            import_batch=import_batch,
            source_row_number=2,
        )
        second_invoice = InvoiceRecord.objects.get(
            import_batch=import_batch,
            source_row_number=3,
        )

        self.assertEqual(first_invoice.invoice_number, "FT 2026/001")
        self.assertEqual(
            first_invoice.source_values["numero_fatura"],
            " FT 2026/001 ",
        )
        self.assertEqual(
            first_invoice.normalized_invoice_number,
            second_invoice.normalized_invoice_number,
        )

    def test_invalid_fixture_produces_expected_errors_without_persisting_rows(self):
        content = (self.examples_dir / "faturas_invalidas.csv").read_bytes()
        expected_manifest = json.loads(
            (self.examples_dir / "erros_esperados.json").read_text(encoding="utf-8")
        )

        response = self.upload(content)

        self.assertEqual(response.status_code, 302)
        import_batch = ImportBatch.objects.get()
        expected_errors = expected_manifest["files"]["faturas_invalidas.csv"]
        actual_errors = [
            {
                "source_row": error["source_row"],
                "field": error["field"],
                "code": error["code"],
            }
            for error in import_batch.error_summary
        ]
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(import_batch.row_count, 14)
        self.assertEqual(import_batch.valid_row_count, 0)
        self.assertEqual(import_batch.invalid_row_count, 14)
        self.assertEqual(actual_errors, expected_errors)
        self.assertFalse(InvoiceRecord.objects.exists())
        self.assertTrue(
            AuditEvent.objects.filter(action="import.validation_failed").exists()
        )

    def test_invalid_header_stops_processing(self):
        content = (self.examples_dir / "cabecalho_invalido.csv").read_bytes()

        self.upload(content)

        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(import_batch.row_count, 0)
        self.assertEqual(
            import_batch.error_summary[0]["code"],
            "unexpected_header",
        )
        self.assertFalse(InvoiceRecord.objects.exists())

    def test_one_invalid_row_prevents_all_rows_from_being_persisted(self):
        content = (
            "fornecedor_id;numero_fatura;data_fatura;valor_total;moeda\n"
            "FORN-001;FT 1;2026-08-01;100,00;EUR\n"
            "FORN-002;FT 2;01/08/2026;200,00;EUR\n"
        ).encode()

        self.upload(content)

        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(import_batch.valid_row_count, 1)
        self.assertEqual(import_batch.invalid_row_count, 1)
        self.assertFalse(InvoiceRecord.objects.exists())

    def test_invalid_utf8_after_initial_upload_sample_fails_processing(self):
        header = (
            b"fornecedor_id;numero_fatura;data_fatura;valor_total;moeda\n"
        )
        valid_row = b"FORN-001;FT 1;2026-08-01;100,00;EUR\n"
        prefix = header + (valid_row * 250)
        self.assertGreater(len(prefix), 8192)
        content = prefix + b"FORN-002;FT \xff;2026-08-01;100,00;EUR\n"

        response = self.upload(content)

        self.assertEqual(response.status_code, 302)
        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertIn(
            "invalid_encoding",
            [error["code"] for error in import_batch.error_summary],
        )
        self.assertFalse(InvoiceRecord.objects.exists())

    def test_malformed_csv_is_rejected(self):
        content = (
            b"fornecedor_id;numero_fatura;data_fatura;valor_total;moeda\n"
            b"FORN-001;\"FT 1;2026-08-01;100,00;EUR\n"
        )

        self.upload(content)

        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(import_batch.error_summary[0]["code"], "invalid_csv")
        self.assertFalse(InvoiceRecord.objects.exists())

    def test_only_first_hundred_errors_are_stored(self):
        header = "fornecedor_id;numero_fatura;data_fatura;valor_total;moeda\n"
        invalid_row = ";FT 1;2026-08-01;100,00;EUR\n"
        content = (header + (invalid_row * (MAX_STORED_ERRORS + 1))).encode()

        self.upload(content)

        import_batch = ImportBatch.objects.get()
        self.assertEqual(import_batch.invalid_row_count, MAX_STORED_ERRORS + 1)
        self.assertEqual(len(import_batch.error_summary), MAX_STORED_ERRORS)
        self.assertFalse(InvoiceRecord.objects.exists())

    def test_missing_stored_file_marks_import_as_failed(self):
        import_batch = ImportBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="inexistente.csv",
            storage_key="organizations/inexistente.csv",
            file_sha256="f" * 64,
        )

        result = process_import_batch(import_batch)

        import_batch.refresh_from_db()
        self.assertFalse(result.is_valid)
        self.assertEqual(import_batch.status, ImportBatch.Status.FAILED)
        self.assertEqual(
            import_batch.error_summary[0]["code"],
            "storage_read_error",
        )
        self.assertFalse(InvoiceRecord.objects.exists())
