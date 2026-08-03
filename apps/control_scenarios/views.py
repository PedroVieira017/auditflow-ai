from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.choices import Severity
from apps.organizations.access import get_active_membership
from apps.organizations.models import Membership

from .forms import (
    CONTROL_FREQUENCY_CHOICES,
    CONTROL_TYPE_CHOICES,
    OBJECTIVE_CATEGORY_CHOICES,
    ControlScenarioApprovalForm,
    ControlScenarioDraftForm,
)
from .models import ControlScenario, ControlScenarioVersion
from .services import (
    ControlScenarioApprovalError,
    DuplicateControlScenarioKeyError,
    approve_control_scenario_version,
    create_control_scenario_draft,
)


@login_required
def control_scenario_list(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    versions = ControlScenarioVersion.objects.for_organization(
        membership.organization
    ).select_related("created_by", "approved_by")
    scenarios = (
        ControlScenario.objects.for_organization(membership.organization)
        .select_related("active_version")
        .prefetch_related(
            Prefetch("versions", queryset=versions, to_attr="ordered_versions")
        )
    )
    page = Paginator(scenarios, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "control_scenarios/list.html",
        {
            "can_create": membership.role != Membership.Role.VIEWER,
            "organization": membership.organization,
            "page": page,
        },
    )


@login_required
def control_scenario_create(request, organization_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    if membership.role == Membership.Role.VIEWER:
        raise PermissionDenied("Este utilizador não pode criar cenários.")

    if request.method == "POST":
        form = ControlScenarioDraftForm(
            request.POST,
            organization=membership.organization,
        )
        if form.is_valid():
            try:
                version = create_control_scenario_draft(
                    membership=membership,
                    created_by=request.user,
                    data=form.cleaned_data,
                )
            except DuplicateControlScenarioKeyError as exc:
                form.add_error("key", str(exc))
            else:
                messages.success(request, "O rascunho do cenário foi criado.")
                return redirect(
                    "control_scenarios:detail",
                    organization_id=membership.organization_id,
                    scenario_id=version.scenario_id,
                )
    else:
        form = ControlScenarioDraftForm(
            organization=membership.organization,
            initial={
                "key": "AP_DUPLICATE_INVOICE_REVIEW",
                "name": "Revisão de duplicação de faturas",
                "description": (
                    "Monitorização das exceções ao procedimento de prevenção "
                    "de pagamentos repetidos."
                ),
                "change_reason": (
                    "Configuração inicial do cenário para o processo de compras "
                    "e pagamentos."
                ),
                "objective_statement": (
                    "Pagar apenas obrigações válidas e evitar o pagamento "
                    "repetido da mesma fatura."
                ),
                "risk_statement": (
                    "A mesma obrigação pode ser registada ou paga mais do que "
                    "uma vez."
                ),
                "control_name": "Revisão de potenciais faturas duplicadas",
                "control_description": (
                    "Rever as faturas registadas através de um teste de unicidade "
                    "e investigar as exceções antes da libertação do lote de "
                    "pagamento."
                ),
                "control_owner_role": "Responsável de contas a pagar",
                "reviewer_role": "Responsável de contas a pagar",
            },
        )

    return render(
        request,
        "control_scenarios/create.html",
        {"form": form, "organization": membership.organization},
    )


@login_required
def control_scenario_detail(request, organization_id, scenario_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    versions = ControlScenarioVersion.objects.for_organization(
        membership.organization
    ).select_related("created_by", "approved_by")
    scenario = get_object_or_404(
        ControlScenario.objects.for_organization(membership.organization)
        .select_related("active_version")
        .prefetch_related(
            Prefetch("versions", queryset=versions, to_attr="ordered_versions")
        ),
        id=scenario_id,
    )
    if not scenario.ordered_versions:
        raise Http404("O cenário não possui versões.")
    version = scenario.ordered_versions[0]
    can_approve = (
        membership.role == Membership.Role.OWNER
        and version.state == ControlScenarioVersion.State.DRAFT
    )
    rule = version.rules[0] if version.rules else None
    indicators = (
        version.monitoring.get("indicators", [])
        if isinstance(version.monitoring, dict)
        else []
    )
    indicator = indicators[0] if indicators else None
    return render(
        request,
        "control_scenarios/detail.html",
        {
            "approval_form": (
                ControlScenarioApprovalForm(version=version)
                if can_approve
                else None
            ),
            "can_approve": can_approve,
            "category_label": dict(OBJECTIVE_CATEGORY_CHOICES).get(
                version.objective.get("category"),
                version.objective.get("category"),
            ),
            "control_frequency_label": dict(CONTROL_FREQUENCY_CHOICES).get(
                version.control.get("frequency"),
                version.control.get("frequency"),
            ),
            "control_type_label": dict(CONTROL_TYPE_CHOICES).get(
                version.control.get("type"),
                version.control.get("type"),
            ),
            "indicator": indicator,
            "organization": membership.organization,
            "rule": rule,
            "rule_severity_label": dict(Severity.choices).get(
                rule.get("severity") if rule else None,
                rule.get("severity") if rule else None,
            ),
            "scenario": scenario,
            "version": version,
        },
    )


@login_required
@require_POST
def control_scenario_approve(request, organization_id, scenario_id):
    membership = get_active_membership(
        user=request.user,
        organization_id=organization_id,
    )
    if membership.role != Membership.Role.OWNER:
        raise PermissionDenied("Apenas um proprietário pode aprovar cenários.")

    scenario = get_object_or_404(
        ControlScenario.objects.for_organization(membership.organization),
        id=scenario_id,
    )
    version = (
        ControlScenarioVersion.objects.for_organization(
            membership.organization
        )
        .filter(scenario=scenario)
        .order_by("-version")
        .first()
    )
    if version is None:
        raise Http404("O cenário não possui versões.")

    form = ControlScenarioApprovalForm(request.POST, version=version)
    if not form.is_valid():
        error_messages = [
            message
            for errors in form.errors.values()
            for message in errors
        ]
        messages.error(
            request,
            "Não foi possível aprovar a versão. " + " ".join(error_messages),
        )
    elif form.cleaned_data["expected_version_id"] != version.id:
        messages.error(
            request,
            "A versão apresentada foi alterada. Reveja o cenário antes de aprovar.",
        )
    else:
        try:
            approve_control_scenario_version(
                membership=membership,
                approved_by=request.user,
                scenario_id=scenario.id,
                version_id=version.id,
                effective_from=form.cleaned_data["effective_from"],
                approval_note=form.cleaned_data["approval_note"],
            )
        except (ControlScenarioApprovalError, ValidationError) as exc:
            messages.error(
                request,
                f"Não foi possível aprovar a versão. {exc}",
            )
        else:
            messages.success(
                request,
                "A versão do cenário foi aprovada e o snapshot foi preservado.",
            )

    return redirect(
        "control_scenarios:detail",
        organization_id=membership.organization_id,
        scenario_id=scenario.id,
    )
