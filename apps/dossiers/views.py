from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.imports.models import ImportBatch
from apps.organizations.access import get_active_membership
from apps.organizations.models import Membership

from .builder import WorkDossierDataIntegrityError, WorkDossierPermissionError
from .services import generate_work_dossier_html


@login_required
@require_POST
def download_work_dossier(request, organization_id, batch_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    if membership.role == Membership.Role.VIEWER:
        raise PermissionDenied("Este utilizador não pode gerar dossiers.")

    import_batch = get_object_or_404(
        ImportBatch.objects.for_organization(membership.organization).select_related(
            "organization",
            "uploaded_by",
        ),
        id=batch_id,
    )
    try:
        dossier_export = generate_work_dossier_html(
            import_batch=import_batch,
            generated_by=request.user,
        )
    except WorkDossierPermissionError as exc:
        raise PermissionDenied(
            "Este utilizador não pode gerar dossiers."
        ) from exc
    except WorkDossierDataIntegrityError:
        return HttpResponse(
            "O dossier não pôde ser gerado porque os dados não são consistentes.",
            content_type="text/plain; charset=utf-8",
            status=409,
        )

    response = HttpResponse(
        dossier_export.content,
        content_type="text/html; charset=utf-8",
    )
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{dossier_export.filename}"'
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
        "script-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
