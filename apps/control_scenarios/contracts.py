import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from apps.rules.catalog import rule_registry
from apps.rules.engine import RuleNotFoundError


CONTROL_SCENARIO_CONTRACT = "auditflow-control-scenario-v1"
STABLE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

OBJECTIVE_CATEGORIES = {"operations", "reporting", "compliance"}
CONTROL_TYPES = {"preventive", "detective", "corrective"}
CONTROL_FREQUENCIES = {
    "per_transaction",
    "per_import",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
    "ad_hoc",
}
INDICATOR_TYPES = {"kpi", "kri", "control_indicator"}
INDICATOR_UNITS = {"count", "percentage", "currency", "days", "ratio"}
INDICATOR_DIRECTIONS = {
    "lower_is_better",
    "higher_is_better",
    "informational",
}
MEASUREMENT_WINDOWS = {
    "per_import",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
}
TARGET_OPERATORS = {"eq", "gt", "gte", "lt", "lte"}
SEVERITIES = {"low", "medium", "high", "critical"}
ORIGIN_TYPES = {"internal", "contractual", "regulatory", "suggested_template"}

METRIC_PARAMETER_KEYS = {
    ("RULE_ALERT_COUNT", 1): {"rule_key"},
}

LIMITATION_MESSAGES = {
    "not_a_professional_conclusion": (
        "O cenário não constitui opinião de auditoria, certificação ou garantia "
        "de conformidade."
    ),
    "configured_criteria_only": (
        "Os resultados representam apenas correspondências aos critérios "
        "aprovados pela organização."
    ),
    "indicators_are_not_controls": (
        "Os indicadores não substituem o desenho, a execução e a revisão do "
        "controlo."
    ),
    "human_review_required": (
        "A configuração, as alterações e as conclusões exigem decisão humana "
        "registada."
    ),
}


class ControlScenarioContractError(ValueError):
    pass


def canonical_payload_bytes(payload):
    payload_without_integrity = {
        key: value
        for key, value in payload.items()
        if key != "integrity"
    }
    return json.dumps(
        payload_without_integrity,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculate_payload_hash(payload):
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _require_object(value, *, label, keys):
    if not isinstance(value, dict):
        raise ControlScenarioContractError(f"{label} deve ser um objeto JSON.")
    if set(value) != set(keys):
        raise ControlScenarioContractError(
            f"{label} não contém exatamente os campos previstos no contrato."
        )


def _require_nonblank(value, *, label):
    if not isinstance(value, str) or not value.strip():
        raise ControlScenarioContractError(f"{label} é obrigatório.")


def _require_stable_key(value, *, label):
    if not isinstance(value, str) or not STABLE_KEY_PATTERN.fullmatch(value):
        raise ControlScenarioContractError(
            f"{label} deve usar maiúsculas, números e underscores."
        )


def _require_positive_integer(value, *, label):
    if type(value) is not int or value < 1:
        raise ControlScenarioContractError(
            f"{label} deve ser um inteiro positivo."
        )


def _require_json(value, *, label):
    try:
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ControlScenarioContractError(
            f"{label} deve conter apenas valores JSON válidos."
        ) from exc


def _validate_objective(objective):
    _require_object(
        objective,
        label="O objetivo",
        keys={"category", "statement"},
    )
    if objective["category"] not in OBJECTIVE_CATEGORIES:
        raise ControlScenarioContractError("A categoria do objetivo é inválida.")
    _require_nonblank(objective["statement"], label="A descrição do objetivo")


def _validate_risk(risk):
    _require_object(risk, label="O risco", keys={"statement"})
    _require_nonblank(risk["statement"], label="A descrição do risco")


def _validate_control(control):
    _require_object(
        control,
        label="O controlo",
        keys={
            "description",
            "evidence_expectations",
            "frequency",
            "name",
            "owner_role",
            "type",
        },
    )
    _require_nonblank(control["name"], label="O nome do controlo")
    _require_nonblank(control["description"], label="A descrição do controlo")
    _require_nonblank(control["owner_role"], label="O responsável pelo controlo")
    if control["type"] not in CONTROL_TYPES:
        raise ControlScenarioContractError("O tipo de controlo é inválido.")
    if control["frequency"] not in CONTROL_FREQUENCIES:
        raise ControlScenarioContractError("A frequência do controlo é inválida.")
    evidence = control["evidence_expectations"]
    if not isinstance(evidence, list) or not evidence:
        raise ControlScenarioContractError(
            "O controlo deve indicar pelo menos uma evidência esperada."
        )
    for item in evidence:
        _require_nonblank(item, label="A descrição da evidência esperada")


def _validate_target(target):
    _require_object(
        target,
        label="O objetivo do indicador",
        keys={"operator", "value"},
    )
    if target["operator"] not in TARGET_OPERATORS:
        raise ControlScenarioContractError(
            "O operador do objetivo do indicador é inválido."
        )
    if not isinstance(target["value"], str):
        raise ControlScenarioContractError(
            "O valor do objetivo do indicador deve ser uma string decimal."
        )
    try:
        numeric_value = Decimal(target["value"])
    except InvalidOperation as exc:
        raise ControlScenarioContractError(
            "O valor do objetivo do indicador não é decimal."
        ) from exc
    if not numeric_value.is_finite():
        raise ControlScenarioContractError(
            "O valor do objetivo do indicador deve ser finito."
        )


def _validate_monitoring(monitoring, *, rule_keys):
    _require_object(
        monitoring,
        label="A monitorização",
        keys={"indicators", "review_due_days", "reviewer_role"},
    )
    _require_nonblank(
        monitoring["reviewer_role"],
        label="O responsável pela revisão",
    )
    _require_positive_integer(
        monitoring["review_due_days"],
        label="O prazo de revisão",
    )
    indicators = monitoring["indicators"]
    if not isinstance(indicators, list) or not indicators:
        raise ControlScenarioContractError(
            "A monitorização deve possuir pelo menos um indicador."
        )
    seen_keys = set()
    for indicator in indicators:
        expected_keys = {
            "description",
            "direction",
            "key",
            "measurement",
            "name",
            "type",
            "unit",
        }
        if (
            isinstance(indicator, dict)
            and indicator.get("direction") != "informational"
        ):
            expected_keys.add("target")
        _require_object(
            indicator,
            label="O indicador",
            keys=expected_keys,
        )
        _require_stable_key(indicator["key"], label="A chave do indicador")
        if indicator["key"] in seen_keys:
            raise ControlScenarioContractError(
                "As chaves dos indicadores não podem repetir-se."
            )
        seen_keys.add(indicator["key"])
        _require_nonblank(indicator["name"], label="O nome do indicador")
        _require_nonblank(
            indicator["description"],
            label="A descrição do indicador",
        )
        if indicator["type"] not in INDICATOR_TYPES:
            raise ControlScenarioContractError("O tipo de indicador é inválido.")
        if indicator["unit"] not in INDICATOR_UNITS:
            raise ControlScenarioContractError("A unidade do indicador é inválida.")
        if indicator["direction"] not in INDICATOR_DIRECTIONS:
            raise ControlScenarioContractError("A direção do indicador é inválida.")

        measurement = indicator["measurement"]
        _require_object(
            measurement,
            label="A medição do indicador",
            keys={"metric_key", "metric_version", "parameters", "window"},
        )
        _require_stable_key(
            measurement["metric_key"],
            label="A chave da métrica",
        )
        _require_positive_integer(
            measurement["metric_version"],
            label="A versão da métrica",
        )
        metric_identity = (
            measurement["metric_key"],
            measurement["metric_version"],
        )
        if metric_identity not in METRIC_PARAMETER_KEYS:
            raise ControlScenarioContractError(
                "O cenário referencia uma métrica que não está registada."
            )
        if not isinstance(measurement["parameters"], dict):
            raise ControlScenarioContractError(
                "Os parâmetros da métrica devem ser um objeto JSON."
            )
        if set(measurement["parameters"]) != METRIC_PARAMETER_KEYS[metric_identity]:
            raise ControlScenarioContractError(
                "Os parâmetros da métrica não correspondem à sua versão."
            )
        if measurement["window"] not in MEASUREMENT_WINDOWS:
            raise ControlScenarioContractError("A janela da métrica é inválida.")
        referenced_rule = measurement["parameters"].get("rule_key")
        if referenced_rule is not None and referenced_rule not in rule_keys:
            raise ControlScenarioContractError(
                "A métrica referencia uma regra ausente do cenário."
            )
        if indicator["direction"] != "informational":
            _validate_target(indicator["target"])


def _validate_rules(rules):
    if not isinstance(rules, list) or not rules:
        raise ControlScenarioContractError(
            "O cenário deve associar pelo menos uma regra."
        )
    seen_keys = set()
    for rule in rules:
        _require_object(
            rule,
            label="A associação da regra",
            keys={
                "key",
                "origin",
                "parameters",
                "purpose",
                "severity",
                "version",
            },
        )
        _require_stable_key(rule["key"], label="A chave da regra")
        if rule["key"] in seen_keys:
            raise ControlScenarioContractError(
                "Cada chave de regra só pode aparecer uma vez no cenário."
            )
        seen_keys.add(rule["key"])
        _require_positive_integer(rule["version"], label="A versão da regra")
        try:
            registered_rule = rule_registry.get(rule["key"], rule["version"])
        except RuleNotFoundError as exc:
            raise ControlScenarioContractError(
                "O cenário referencia uma regra que não está registada."
            ) from exc
        if not isinstance(rule["parameters"], dict):
            raise ControlScenarioContractError(
                "Os parâmetros da regra devem ser um objeto JSON."
            )
        parameter_schema = dict(registered_rule.metadata.parameters_schema)
        if set(rule["parameters"]) - set(parameter_schema):
            raise ControlScenarioContractError(
                "Os parâmetros da regra não correspondem à sua versão."
            )
        _require_nonblank(rule["purpose"], label="A finalidade da regra")
        if rule["severity"] not in SEVERITIES:
            raise ControlScenarioContractError("A prioridade da regra é inválida.")

        origin = rule["origin"]
        _require_object(
            origin,
            label="A origem da regra",
            keys={"references", "type"},
        )
        if origin["type"] not in ORIGIN_TYPES:
            raise ControlScenarioContractError("A origem da regra é inválida.")
        references = origin["references"]
        if not isinstance(references, list):
            raise ControlScenarioContractError(
                "As referências da regra devem ser uma lista."
            )
        if origin["type"] in {"contractual", "regulatory"} and not references:
            raise ControlScenarioContractError(
                "Uma origem contratual ou regulamentar exige referências."
            )
        for reference in references:
            _require_object(
                reference,
                label="A referência da regra",
                keys={"reference", "title"},
            )
            _require_nonblank(
                reference["reference"],
                label="O identificador da referência",
            )
            _require_nonblank(
                reference["title"],
                label="O título da referência",
            )
    return seen_keys


def _validate_limitations(limitations):
    if not isinstance(limitations, list) or len(limitations) != len(
        LIMITATION_MESSAGES
    ):
        raise ControlScenarioContractError(
            "O cenário deve conter todas as limitações obrigatórias."
        )
    actual = {}
    for limitation in limitations:
        _require_object(
            limitation,
            label="A limitação",
            keys={"code", "message"},
        )
        code = limitation["code"]
        if code in actual:
            raise ControlScenarioContractError(
                "Os códigos das limitações não podem repetir-se."
            )
        actual[code] = limitation["message"]
    if actual != LIMITATION_MESSAGES:
        raise ControlScenarioContractError(
            "As limitações não correspondem ao contrato em vigor."
        )


def validate_configuration(
    *,
    objective,
    risk,
    control,
    monitoring,
    rules,
    limitations,
):
    sections = {
        "objective": objective,
        "risk": risk,
        "control": control,
        "monitoring": monitoring,
        "rules": rules,
        "limitations": limitations,
    }
    _require_json(sections, label="A configuração")
    _validate_objective(objective)
    _validate_risk(risk)
    _validate_control(control)
    rule_keys = _validate_rules(rules)
    _validate_monitoring(monitoring, rule_keys=rule_keys)
    _validate_limitations(limitations)
