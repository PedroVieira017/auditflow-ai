from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.organizations.access import get_active_membership

from .dashboard import build_dashboard


@require_GET
def health_check(request):
    return JsonResponse({"status": "ok", "service": "auditflow"})


@login_required
@require_GET
def organization_dashboard(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    dashboard = build_dashboard(organization=membership.organization)
    return render(
        request,
        "core/dashboard.html",
        {
            "dashboard": dashboard,
            "organization": membership.organization,
        },
    )
