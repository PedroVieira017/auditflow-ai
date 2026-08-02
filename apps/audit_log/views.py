from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.organizations.access import get_active_membership

from .forms import AuditEventFilterForm
from .models import AuditEvent
from .presentation import present_audit_event


@login_required
@require_GET
def audit_event_list(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    events = AuditEvent.objects.for_organization(
        membership.organization
    ).select_related("actor")
    filter_form = AuditEventFilterForm(request.GET or None)
    filter_parameters = []
    if filter_form.is_valid():
        action = filter_form.cleaned_data["action"]
        if action:
            events = events.filter(action=action)
            filter_parameters.append(("action", action))

    page = Paginator(events, 25).get_page(request.GET.get("page"))
    entries = [present_audit_event(event) for event in page.object_list]
    return render(
        request,
        "audit_log/list.html",
        {
            "entries": entries,
            "filter_form": filter_form,
            "filter_query": urlencode(filter_parameters),
            "filters_applied": bool(filter_parameters),
            "organization": membership.organization,
            "page": page,
        },
    )
