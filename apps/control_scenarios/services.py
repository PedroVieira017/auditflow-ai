from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.audit_log.models import AuditEvent
from apps.organizations.models import Membership

from .contracts import LIMITATION_MESSAGES
from .models import ControlScenario, ControlScenarioVersion


class DuplicateControlScenarioKeyError(ValueError):
    pass


def _decimal_text(value):
    return format(value, "f")


def _build_configuration(data):
    return {
        "objective": {
            "category": data["objective_category"],
            "statement": data["objective_statement"],
        },
        "risk": {"statement": data["risk_statement"]},
        "control": {
            "name": data["control_name"],
            "description": data["control_description"],
            "type": data["control_type"],
            "frequency": data["control_frequency"],
            "owner_role": data["control_owner_role"],
            "evidence_expectations": [
                "Dados normalizados usados pela regra de duplicação",
                "Alerta com as linhas que satisfizeram os critérios configurados",
                "Decisão humana justificada e respetiva evidência de suporte",
            ],
        },
        "monitoring": {
            "reviewer_role": data["reviewer_role"],
            "review_due_days": data["review_due_days"],
            "indicators": [
                {
                    "key": "POTENTIAL_DUPLICATE_GROUP_COUNT",
                    "name": "Grupos de potenciais faturas duplicadas",
                    "description": (
                        "Número de grupos de faturas que satisfazem os critérios "
                        "exatos de potencial duplicação em cada importação."
                    ),
                    "type": "control_indicator",
                    "unit": "count",
                    "direction": "lower_is_better",
                    "measurement": {
                        "metric_key": "RULE_ALERT_COUNT",
                        "metric_version": 1,
                        "parameters": {
                            "rule_key": "DUPLICATE_INVOICE_EXACT"
                        },
                        "window": "per_import",
                    },
                    "target": {
                        "operator": "eq",
                        "value": _decimal_text(data["indicator_target"]),
                    },
                }
            ],
        },
        "rules": [
            {
                "key": "DUPLICATE_INVOICE_EXACT",
                "version": 1,
                "parameters": {},
                "severity": data["rule_severity"],
                "purpose": (
                    "Identificar grupos de faturas com fornecedor, número, data, "
                    "valor e moeda iguais para investigação humana."
                ),
                "origin": {"type": "internal", "references": []},
            }
        ],
        "limitations": [
            {"code": code, "message": message}
            for code, message in LIMITATION_MESSAGES.items()
        ],
    }


def create_control_scenario_draft(*, membership, created_by, data):
    if (
        not membership.is_active
        or membership.user_id != created_by.id
        or membership.role not in (Membership.Role.OWNER, Membership.Role.ANALYST)
    ):
        raise PermissionDenied(
            "Apenas proprietários e analistas ativos podem criar cenários."
        )

    if ControlScenario.objects.for_organization(membership.organization).filter(
        key=data["key"]
    ).exists():
        raise DuplicateControlScenarioKeyError(
            "Já existe um cenário com esta chave na organização."
        )

    configuration = _build_configuration(data)
    try:
        with transaction.atomic():
            scenario = ControlScenario(
                organization=membership.organization,
                key=data["key"],
            )
            scenario.full_clean()
            scenario.save()

            version = ControlScenarioVersion(
                organization=membership.organization,
                scenario=scenario,
                version=1,
                organization_name=membership.organization.name,
                name=data["name"],
                description=data["description"],
                objective=configuration["objective"],
                risk=configuration["risk"],
                control=configuration["control"],
                monitoring=configuration["monitoring"],
                rules=configuration["rules"],
                limitations=configuration["limitations"],
                created_by=created_by,
                created_by_email=created_by.email,
                created_by_user_id=created_by.id,
                created_by_role=membership.role,
                change_reason=data["change_reason"],
            )
            version.full_clean()
            version.save()

            AuditEvent.objects.create(
                organization=membership.organization,
                actor=created_by,
                action="control_scenario.draft_created",
                resource_type="control_scenario_version",
                resource_id=version.id,
                metadata={
                    "scenario_id": str(scenario.id),
                    "scenario_key": scenario.key,
                    "scenario_version": version.version,
                    "state": version.state,
                },
            )
    except IntegrityError as exc:
        raise DuplicateControlScenarioKeyError(
            "Já existe um cenário com esta chave na organização."
        ) from exc

    return version
