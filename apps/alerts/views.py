from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.access import get_active_membership
from apps.organizations.models import Membership

from .forms import AlertFilterForm, AlertStatusForm
from .models import Alert, AlertEvidence, AlertStatusEvent
from .services import AlertStatusChangeError, change_alert_status


@login_required
def alert_list(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    alerts = Alert.objects.for_organization(membership.organization)
    filter_form = AlertFilterForm(
        request.GET or None,
        organization=membership.organization,
    )
    filter_parameters = []
    if filter_form.is_valid():
        query = filter_form.cleaned_data["query"]
        status = filter_form.cleaned_data["status"]
        severity = filter_form.cleaned_data["severity"]
        import_batch = filter_form.cleaned_data["import_batch"]

        if query:
            alerts = alerts.filter(
                Q(title__icontains=query)
                | Q(explanation__icontains=query)
                | Q(rule_run__rule_definition__name__icontains=query)
                | Q(rule_run__import_batch__original_filename__icontains=query)
                | Q(
                    evidence__invoice_record__supplier_identifier__icontains=query
                )
                | Q(evidence__invoice_record__supplier_name__icontains=query)
                | Q(evidence__invoice_record__invoice_number__icontains=query)
            ).distinct()
            filter_parameters.append(("query", query))
        if status:
            alerts = alerts.filter(status=status)
            filter_parameters.append(("status", status))
        if severity:
            alerts = alerts.filter(severity=severity)
            filter_parameters.append(("severity", severity))
        if import_batch:
            alerts = alerts.filter(rule_run__import_batch=import_batch)
            filter_parameters.append(("import_batch", str(import_batch.id)))

    alerts = alerts.select_related(
        "rule_run__rule_definition",
        "rule_run__import_batch",
    )
    page = Paginator(alerts, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "alerts/list.html",
        {
            "filter_form": filter_form,
            "filter_query": urlencode(filter_parameters),
            "filters_applied": bool(filter_parameters),
            "organization": membership.organization,
            "page": page,
        },
    )


@login_required
def alert_detail(request, organization_id, alert_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    evidence_queryset = AlertEvidence.objects.for_organization(
        membership.organization
    ).select_related("invoice_record")
    status_event_queryset = AlertStatusEvent.objects.for_organization(
        membership.organization
    ).select_related("changed_by")
    alert = get_object_or_404(
        Alert.objects.for_organization(membership.organization)
        .select_related(
            "rule_run__rule_definition",
            "rule_run__import_batch",
        )
        .prefetch_related(
            Prefetch("evidence", queryset=evidence_queryset),
            Prefetch("status_events", queryset=status_event_queryset),
        ),
        id=alert_id,
    )
    can_triage = membership.role != Membership.Role.VIEWER
    status_form = None
    if request.method == "POST":
        if not can_triage:
            raise PermissionDenied("Este utilizador não pode alterar alertas.")
        status_form = AlertStatusForm(
            request.POST,
            current_status=alert.status,
        )
        if status_form.is_valid():
            try:
                change_alert_status(
                    alert=alert,
                    organization=membership.organization,
                    changed_by=request.user,
                    to_status=status_form.cleaned_data["status"],
                    note=status_form.cleaned_data["note"],
                    expected_status=status_form.cleaned_data["expected_status"],
                )
            except AlertStatusChangeError as exc:
                status_form.add_error(None, str(exc))
            else:
                messages.success(request, "O estado do alerta foi atualizado.")
                return redirect(
                    "alerts:detail",
                    organization_id=membership.organization_id,
                    alert_id=alert.id,
                )
    elif can_triage:
        status_form = AlertStatusForm(current_status=alert.status)

    return render(
        request,
        "alerts/detail.html",
        {
            "alert": alert,
            "can_triage": can_triage,
            "organization": membership.organization,
            "status_form": status_form,
        },
    )
