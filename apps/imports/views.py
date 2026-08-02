from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.models import Membership

from .forms import InvoiceCSVUploadForm
from .models import ImportBatch
from .processing import process_import_batch
from .services import DuplicateImportError, create_import_batch


def get_active_membership(*, user, organization_id):
    return get_object_or_404(
        Membership.objects.select_related("organization"),
        organization_id=organization_id,
        organization__is_active=True,
        user=user,
        is_active=True,
    )


@login_required
def upload_invoice_csv(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    if membership.role == Membership.Role.VIEWER:
        raise PermissionDenied("Este utilizador nao pode carregar ficheiros.")

    if request.method == "POST":
        form = InvoiceCSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                import_batch = create_import_batch(
                    organization=membership.organization,
                    uploaded_by=request.user,
                    uploaded_file=form.cleaned_data["file"],
                )
            except DuplicateImportError as exc:
                form.add_error(
                    "file",
                    (
                        "Este ficheiro ja foi carregado nesta organizacao "
                        f"({exc.existing_batch.original_filename})."
                    ),
                )
            else:
                process_result = process_import_batch(import_batch)
                if process_result.is_valid:
                    messages.success(
                        request,
                        "Ficheiro validado e processado com sucesso.",
                    )
                else:
                    messages.warning(
                        request,
                        "O ficheiro contem erros e nao foi importado.",
                    )
                return redirect(
                    "imports:detail",
                    organization_id=membership.organization_id,
                    batch_id=import_batch.id,
                )
    else:
        form = InvoiceCSVUploadForm()

    return render(
        request,
        "imports/upload.html",
        {"form": form, "organization": membership.organization},
    )


@login_required
def import_detail(request, organization_id, batch_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    import_batch = get_object_or_404(
        ImportBatch.objects.for_organization(membership.organization),
        id=batch_id,
    )
    return render(
        request,
        "imports/detail.html",
        {"import_batch": import_batch, "organization": membership.organization},
    )
