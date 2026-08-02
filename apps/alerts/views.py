from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from apps.organizations.access import get_active_membership

from .models import Alert, AlertEvidence


@login_required
def alert_list(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    alerts = (
        Alert.objects.for_organization(membership.organization)
        .select_related(
            "rule_run__rule_definition",
            "rule_run__import_batch",
        )
        .all()
    )
    page = Paginator(alerts, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "alerts/list.html",
        {
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
    alert = get_object_or_404(
        Alert.objects.for_organization(membership.organization)
        .select_related(
            "rule_run__rule_definition",
            "rule_run__import_batch",
        )
        .prefetch_related(
            Prefetch("evidence", queryset=evidence_queryset),
        ),
        id=alert_id,
    )
    return render(
        request,
        "alerts/detail.html",
        {
            "alert": alert,
            "organization": membership.organization,
        },
    )
