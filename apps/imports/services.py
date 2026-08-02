import hashlib
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction

from apps.audit_log.models import AuditEvent

from .contracts import INVOICE_CSV_CONTRACT_VERSION
from .models import ImportBatch


class DuplicateImportError(Exception):
    def __init__(self, existing_batch):
        self.existing_batch = existing_batch
        super().__init__("Este ficheiro ja foi importado nesta organizacao.")


def calculate_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def sanitize_original_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return PurePosixPath(normalized).name[:255]


def create_import_batch(*, organization, uploaded_by, uploaded_file):
    file_hash = calculate_sha256(uploaded_file)
    existing_batch = ImportBatch.objects.for_organization(organization).filter(
        file_sha256=file_hash
    ).first()
    if existing_batch:
        raise DuplicateImportError(existing_batch)

    original_filename = sanitize_original_filename(uploaded_file.name)
    requested_storage_key = (
        f"organizations/{organization.id}/imports/{uuid.uuid4().hex}.csv"
    )
    saved_storage_key = None

    try:
        uploaded_file.seek(0)
        saved_storage_key = default_storage.save(requested_storage_key, uploaded_file)

        try:
            with transaction.atomic():
                import_batch = ImportBatch.objects.create(
                    organization=organization,
                    uploaded_by=uploaded_by,
                    original_filename=original_filename,
                    storage_key=saved_storage_key,
                    file_sha256=file_hash,
                    status=ImportBatch.Status.PENDING,
                )
                AuditEvent.objects.create(
                    organization=organization,
                    actor=uploaded_by,
                    action="import.created",
                    resource_type="import_batch",
                    resource_id=import_batch.id,
                    metadata={
                        "contract_version": INVOICE_CSV_CONTRACT_VERSION,
                        "file_sha256": file_hash,
                        "original_filename": original_filename,
                        "size_bytes": uploaded_file.size,
                    },
                )
        except (IntegrityError, ValidationError) as exc:
            duplicate = ImportBatch.objects.for_organization(organization).filter(
                file_sha256=file_hash
            ).first()
            if duplicate:
                raise DuplicateImportError(duplicate) from exc
            raise

        return import_batch
    except Exception:
        if saved_storage_key and default_storage.exists(saved_storage_key):
            default_storage.delete(saved_storage_key)
        raise
