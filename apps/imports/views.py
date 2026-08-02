from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.access import get_active_membership
from apps.organizations.models import Membership
from apps.rules.duplicate_invoices import DUPLICATE_INVOICE_EXACT_RULE
from apps.rules.services import RuleExecutionError, execute_rule_for_import

from .forms import InvoiceCSVUploadForm
from .models import ImportBatch
from .processing import process_import_batch
from .services import DuplicateImportError, create_import_batch

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
                    try:
                        rule_run = execute_rule_for_import(
                            rule=DUPLICATE_INVOICE_EXACT_RULE,
                            import_batch=import_batch,
                        )
                    except RuleExecutionError:
                        messages.warning(
                            request,
                            (
                                "O ficheiro foi importado, mas a regra de auditoria "
                                "nao pode ser executada."
                            ),
                        )
                    else:
                        messages.success(
                            request,
                            (
                                "Ficheiro processado com sucesso. "
                                f"Foram gerados {rule_run.alert_count} alertas."
                            ),
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
    rule_runs = import_batch.rule_runs.select_related("rule_definition").all()
    return render(
        request,
        "imports/detail.html",
        {
            "can_generate_dossier": membership.role != Membership.Role.VIEWER,
            "import_batch": import_batch,
            "organization": membership.organization,
            "rule_runs": rule_runs,
        },
    )
