import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence
from uuid import UUID

from apps.core.choices import Severity


class RuleEngineError(ValueError):
    pass


class InvalidRuleDefinitionError(RuleEngineError):
    pass


class InvalidRuleFindingError(RuleEngineError):
    pass


class DuplicateRuleRegistrationError(RuleEngineError):
    pass


class RuleNotFoundError(LookupError):
    pass


def _immutable_mapping(value: Mapping) -> Mapping:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class RuleMetadata:
    key: str
    version: int
    name: str
    description: str
    default_severity: str
    parameters_schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self,
            "parameters_schema",
            _immutable_mapping(self.parameters_schema),
        )


@dataclass(frozen=True)
class InvoiceFact:
    id: UUID
    source_row_number: int
    supplier_identifier: str
    invoice_number: str
    normalized_invoice_number: str
    invoice_date: date
    gross_amount: Decimal
    currency: str


@dataclass(frozen=True)
class RuleContext:
    organization_id: UUID
    import_batch_id: UUID
    invoices: tuple[InvoiceFact, ...]
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "invoices", tuple(self.invoices))
        object.__setattr__(self, "parameters", _immutable_mapping(self.parameters))


@dataclass(frozen=True)
class RuleEvidence:
    invoice_id: UUID
    facts: Mapping[str, object]

    def __post_init__(self):
        object.__setattr__(self, "facts", _immutable_mapping(self.facts))


@dataclass(frozen=True)
class RuleFinding:
    identity: Mapping[str, object]
    title: str
    explanation: str
    severity: str
    recommended_action: str
    evidence: tuple[RuleEvidence, ...]

    def __post_init__(self):
        object.__setattr__(self, "identity", _immutable_mapping(self.identity))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class EvaluatedFinding:
    fingerprint: str
    title: str
    explanation: str
    severity: str
    recommended_action: str
    evidence: tuple[RuleEvidence, ...]


class AuditRule(Protocol):
    metadata: RuleMetadata

    def evaluate(self, context: RuleContext) -> Sequence[RuleFinding]: ...


def validate_rule_metadata(metadata: RuleMetadata) -> None:
    if not isinstance(metadata, RuleMetadata):
        raise InvalidRuleDefinitionError(
            "Os metadados devem usar o contrato RuleMetadata."
        )
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", metadata.key):
        raise InvalidRuleDefinitionError(
            "A chave da regra deve usar letras maiusculas, numeros e underscores."
        )
    if len(metadata.key) > 100:
        raise InvalidRuleDefinitionError(
            "A chave da regra nao pode exceder 100 caracteres."
        )
    if metadata.version < 1:
        raise InvalidRuleDefinitionError("A versao da regra deve ser positiva.")
    if not metadata.name.strip():
        raise InvalidRuleDefinitionError("O nome da regra e obrigatorio.")
    if len(metadata.name) > 200:
        raise InvalidRuleDefinitionError(
            "O nome da regra nao pode exceder 200 caracteres."
        )
    if not metadata.description.strip():
        raise InvalidRuleDefinitionError("A descricao da regra e obrigatoria.")
    if metadata.default_severity not in Severity.values:
        raise InvalidRuleDefinitionError("A severidade predefinida e invalida.")
    if not isinstance(metadata.parameters_schema, Mapping):
        raise InvalidRuleDefinitionError(
            "O esquema de parametros deve ser um mapeamento."
        )
    try:
        json.dumps(
            dict(metadata.parameters_schema),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRuleDefinitionError(
            "O esquema de parametros deve conter apenas valores JSON."
        ) from exc


def build_fingerprint(metadata: RuleMetadata, identity: Mapping[str, object]) -> str:
    if not identity:
        raise InvalidRuleFindingError(
            "A identidade do finding nao pode estar vazia."
        )

    payload = {
        "rule_key": metadata.key,
        "rule_version": metadata.version,
        "identity": dict(identity),
    }
    try:
        serialized_payload = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRuleFindingError(
            "A identidade do finding deve conter apenas valores JSON."
        ) from exc

    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def _validate_context(context: RuleContext) -> set[UUID]:
    invoice_ids = [invoice.id for invoice in context.invoices]
    if len(invoice_ids) != len(set(invoice_ids)):
        raise RuleEngineError("O contexto contem faturas repetidas.")
    return set(invoice_ids)


def _validate_finding(
    *,
    finding: RuleFinding,
    metadata: RuleMetadata,
    context_invoice_ids: set[UUID],
) -> EvaluatedFinding:
    if not isinstance(finding, RuleFinding):
        raise InvalidRuleFindingError(
            "A regra deve devolver apenas objetos RuleFinding."
        )
    if not finding.title.strip():
        raise InvalidRuleFindingError("O titulo do finding e obrigatorio.")
    if not finding.explanation.strip():
        raise InvalidRuleFindingError("A explicacao do finding e obrigatoria.")
    if finding.severity not in Severity.values:
        raise InvalidRuleFindingError("A severidade do finding e invalida.")
    if not finding.recommended_action.strip():
        raise InvalidRuleFindingError("A acao recomendada e obrigatoria.")
    if not finding.evidence:
        raise InvalidRuleFindingError("O finding deve possuir evidencias.")

    evidence_invoice_ids = [item.invoice_id for item in finding.evidence]
    if len(evidence_invoice_ids) != len(set(evidence_invoice_ids)):
        raise InvalidRuleFindingError(
            "Uma fatura nao pode surgir duas vezes na mesma evidencia."
        )

    for evidence in finding.evidence:
        if not isinstance(evidence, RuleEvidence):
            raise InvalidRuleFindingError(
                "As evidencias devem usar o contrato RuleEvidence."
            )
        if evidence.invoice_id not in context_invoice_ids:
            raise InvalidRuleFindingError(
                "A evidencia referencia uma fatura fora do contexto."
            )
        if not evidence.facts:
            raise InvalidRuleFindingError(
                "Cada evidencia deve explicar os factos utilizados."
            )
        try:
            json.dumps(
                dict(evidence.facts),
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidRuleFindingError(
                "Os factos da evidencia devem conter apenas valores JSON."
            ) from exc

    return EvaluatedFinding(
        fingerprint=build_fingerprint(metadata, finding.identity),
        title=finding.title.strip(),
        explanation=finding.explanation.strip(),
        severity=finding.severity,
        recommended_action=finding.recommended_action.strip(),
        evidence=finding.evidence,
    )


def execute_rule(
    rule: AuditRule,
    context: RuleContext,
) -> tuple[EvaluatedFinding, ...]:
    validate_rule_metadata(rule.metadata)
    context_invoice_ids = _validate_context(context)

    try:
        raw_findings = tuple(rule.evaluate(context))
    except TypeError as exc:
        raise RuleEngineError(
            "A regra deve devolver uma sequencia de findings."
        ) from exc

    evaluated_findings = tuple(
        _validate_finding(
            finding=finding,
            metadata=rule.metadata,
            context_invoice_ids=context_invoice_ids,
        )
        for finding in raw_findings
    )

    fingerprints = [finding.fingerprint for finding in evaluated_findings]
    if len(fingerprints) != len(set(fingerprints)):
        raise InvalidRuleFindingError(
            "A regra produziu findings com a mesma identidade."
        )

    return evaluated_findings


class RuleRegistry:
    def __init__(self):
        self._rules: dict[tuple[str, int], AuditRule] = {}

    def register(self, rule: AuditRule) -> AuditRule:
        validate_rule_metadata(rule.metadata)
        identifier = (rule.metadata.key, rule.metadata.version)
        if identifier in self._rules:
            raise DuplicateRuleRegistrationError(
                f"A regra {rule.metadata.key} v{rule.metadata.version} ja existe."
            )
        self._rules[identifier] = rule
        return rule

    def get(self, key: str, version: int | None = None) -> AuditRule:
        if version is not None:
            try:
                return self._rules[(key, version)]
            except KeyError as exc:
                raise RuleNotFoundError(f"Regra {key} v{version} nao encontrada.") from exc

        versions = [
            registered_version
            for registered_key, registered_version in self._rules
            if registered_key == key
        ]
        if not versions:
            raise RuleNotFoundError(f"Regra {key} nao encontrada.")
        return self._rules[(key, max(versions))]

    def definitions(self) -> tuple[RuleMetadata, ...]:
        return tuple(
            rule.metadata
            for _, rule in sorted(self._rules.items(), key=lambda item: item[0])
        )
