from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from django.test import SimpleTestCase

from apps.core.choices import Severity
from apps.rules.engine import (
    DuplicateRuleRegistrationError,
    InvalidRuleDefinitionError,
    InvalidRuleFindingError,
    InvoiceFact,
    RuleContext,
    RuleEvidence,
    RuleFinding,
    RuleMetadata,
    RuleNotFoundError,
    RuleRegistry,
    build_fingerprint,
    execute_rule,
)


class HighValueTestRule:
    metadata = RuleMetadata(
        key="TEST_HIGH_VALUE",
        version=1,
        name="Valor elevado de teste",
        description="Regra ficticia usada apenas para validar o motor.",
        default_severity=Severity.MEDIUM,
        parameters_schema={"threshold": "decimal_string"},
    )

    def evaluate(self, context):
        threshold = Decimal(str(context.parameters["threshold"]))
        findings = []
        for invoice in context.invoices:
            if invoice.gross_amount <= threshold:
                continue
            findings.append(
                RuleFinding(
                    identity={
                        "invoice_id": str(invoice.id),
                        "threshold": str(threshold),
                    },
                    title="Fatura acima do limite de teste",
                    explanation=(
                        f"O valor {invoice.gross_amount} excede o limite {threshold}."
                    ),
                    severity=Severity.MEDIUM,
                    recommended_action="Rever a fatura e a respetiva aprovacao.",
                    evidence=(
                        RuleEvidence(
                            invoice_id=invoice.id,
                            facts={
                                "gross_amount": str(invoice.gross_amount),
                                "threshold": str(threshold),
                            },
                        ),
                    ),
                )
            )
        return findings


class RuleEngineTests(SimpleTestCase):
    def setUp(self):
        self.invoice_low = self.invoice(amount="50.00", row=2)
        self.invoice_high = self.invoice(amount="150.00", row=3)
        self.context = RuleContext(
            organization_id=uuid4(),
            import_batch_id=uuid4(),
            invoices=(self.invoice_low, self.invoice_high),
            parameters={"threshold": "100.00"},
        )
        self.rule = HighValueTestRule()

    def invoice(self, *, amount, row):
        return InvoiceFact(
            id=uuid4(),
            source_row_number=row,
            supplier_identifier="FORN-001",
            invoice_number=f"FT {row}",
            normalized_invoice_number=f"FT {row}",
            invoice_date=date(2026, 8, 1),
            gross_amount=Decimal(amount),
            currency="EUR",
        )

    def test_rule_executes_in_memory_and_returns_explainable_finding(self):
        findings = execute_rule(self.rule, self.context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.severity, Severity.MEDIUM)
        self.assertEqual(finding.evidence[0].invoice_id, self.invoice_high.id)
        self.assertEqual(
            finding.evidence[0].facts["gross_amount"],
            "150.00",
        )
        self.assertRegex(finding.fingerprint, r"^[0-9a-f]{64}$")

    def test_execution_is_deterministic(self):
        first_execution = execute_rule(self.rule, self.context)
        second_execution = execute_rule(self.rule, self.context)

        self.assertEqual(first_execution, second_execution)

    def test_fingerprint_is_independent_of_identity_key_order(self):
        first = build_fingerprint(
            self.rule.metadata,
            {"invoice_id": "one", "threshold": "100.00"},
        )
        second = build_fingerprint(
            self.rule.metadata,
            {"threshold": "100.00", "invoice_id": "one"},
        )

        self.assertEqual(first, second)

    def test_evidence_cannot_reference_invoice_outside_context(self):
        class InvalidEvidenceRule(HighValueTestRule):
            def evaluate(self, context):
                return [
                    RuleFinding(
                        identity={"case": "invalid-evidence"},
                        title="Finding invalido",
                        explanation="Referencia uma fatura que nao foi analisada.",
                        severity=Severity.MEDIUM,
                        recommended_action="Corrigir a implementacao da regra.",
                        evidence=(
                            RuleEvidence(invoice_id=uuid4(), facts={"reason": "test"}),
                        ),
                    )
                ]

        with self.assertRaisesMessage(
            InvalidRuleFindingError,
            "fora do contexto",
        ):
            execute_rule(InvalidEvidenceRule(), self.context)

    def test_finding_must_have_evidence(self):
        class NoEvidenceRule(HighValueTestRule):
            def evaluate(self, context):
                return [
                    RuleFinding(
                        identity={"case": "no-evidence"},
                        title="Finding sem evidencia",
                        explanation="Este finding nao apresenta factos.",
                        severity=Severity.MEDIUM,
                        recommended_action="Corrigir a regra.",
                        evidence=(),
                    )
                ]

        with self.assertRaisesMessage(InvalidRuleFindingError, "evidencias"):
            execute_rule(NoEvidenceRule(), self.context)

    def test_duplicate_finding_identities_are_rejected(self):
        finding = RuleFinding(
            identity={"same": "identity"},
            title="Finding repetido",
            explanation="Dois findings nao podem ter a mesma identidade.",
            severity=Severity.MEDIUM,
            recommended_action="Corrigir a regra.",
            evidence=(
                RuleEvidence(
                    invoice_id=self.invoice_high.id,
                    facts={"reason": "test"},
                ),
            ),
        )

        class DuplicateFindingRule(HighValueTestRule):
            def evaluate(self, context):
                return [finding, finding]

        with self.assertRaisesMessage(
            InvalidRuleFindingError,
            "mesma identidade",
        ):
            execute_rule(DuplicateFindingRule(), self.context)

    def test_identity_must_be_json_serializable(self):
        with self.assertRaisesMessage(InvalidRuleFindingError, "valores JSON"):
            build_fingerprint(
                self.rule.metadata,
                {"invoice_id": UUID(int=0)},
            )

    def test_invalid_rule_metadata_is_rejected(self):
        invalid_metadata = RuleMetadata(
            key="invalid-key",
            version=1,
            name="Regra invalida",
            description="Chave fora do contrato.",
            default_severity=Severity.MEDIUM,
        )

        class InvalidRule:
            metadata = invalid_metadata

            def evaluate(self, context):
                return []

        with self.assertRaises(InvalidRuleDefinitionError):
            execute_rule(InvalidRule(), self.context)

    def test_rule_must_return_rule_finding_objects(self):
        class InvalidReturnRule(HighValueTestRule):
            def evaluate(self, context):
                return ["not-a-finding"]

        with self.assertRaisesMessage(InvalidRuleFindingError, "RuleFinding"):
            execute_rule(InvalidReturnRule(), self.context)


class RuleRegistryTests(SimpleTestCase):
    def test_registry_resolves_exact_and_latest_versions(self):
        registry = RuleRegistry()
        version_one = HighValueTestRule()

        class VersionTwoRule(HighValueTestRule):
            metadata = RuleMetadata(
                key="TEST_HIGH_VALUE",
                version=2,
                name="Valor elevado de teste",
                description="Segunda versao da regra ficticia.",
                default_severity=Severity.HIGH,
            )

        version_two = VersionTwoRule()
        registry.register(version_one)
        registry.register(version_two)

        self.assertIs(registry.get("TEST_HIGH_VALUE", version=1), version_one)
        self.assertIs(registry.get("TEST_HIGH_VALUE"), version_two)

    def test_registry_rejects_duplicate_key_and_version(self):
        registry = RuleRegistry()
        registry.register(HighValueTestRule())

        with self.assertRaises(DuplicateRuleRegistrationError):
            registry.register(HighValueTestRule())

    def test_registry_reports_missing_rule(self):
        with self.assertRaises(RuleNotFoundError):
            RuleRegistry().get("MISSING_RULE")
