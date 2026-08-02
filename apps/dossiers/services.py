import uuid
from dataclasses import dataclass

from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.audit_log.models import AuditEvent

from .builder import build_work_dossier_payload


@dataclass(frozen=True)
class WorkDossierHTMLExport:
    content: str
    filename: str
    payload: dict


def generate_work_dossier_html(
    *,
    import_batch,
    generated_by,
    generation_id=None,
    generated_at=None,
):
    generation_id = generation_id or uuid.uuid4()
    generated_at = generated_at or timezone.now()

    with transaction.atomic():
        payload = build_work_dossier_payload(
            import_batch=import_batch,
            generated_by=generated_by,
            generation_id=generation_id,
            generated_at=generated_at,
        )
        content = render_to_string(
            "dossiers/work_dossier.html",
            {"dossier": payload},
        )
        generation_date = payload["document"]["generated_at"][0:10].replace(
            "-",
            "",
        )
        filename = (
            "auditflow-dossier-"
            f"{import_batch.organization.slug}-"
            f"{generation_date}-"
            f"{import_batch.id}.html"
        )
        AuditEvent.objects.create(
            organization=import_batch.organization,
            actor=generated_by,
            action="dossier.generated",
            resource_type="work_dossier",
            resource_id=payload["document"]["generation_id"],
            metadata={
                "contract": payload["contract"],
                "format": "html",
                "generation_id": payload["document"]["generation_id"],
                "import_batch_id": str(import_batch.id),
                "payload_hash": payload["integrity"]["payload_hash"],
            },
        )

    return WorkDossierHTMLExport(
        content=content,
        filename=filename,
        payload=payload,
    )
