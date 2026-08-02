from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.test import SimpleTestCase

from apps.core.choices import Severity
from apps.rules.duplicate_invoices import DUPLICATE_INVOICE_EXACT_RULE
from apps.rules.engine import InvoiceFact, RuleContext, execute_rule


class DuplicateInvoiceExactRuleTests(SimpleTestCase):
    def invoice(
        self,
        *,
        row,
        supplier="FORN-001",
        number="FT 2026/001",
        invoice_date=date(2026, 8, 1),
        amount="100.00",
        currency="EUR",
    ):
        return InvoiceFact(
            id=uuid4(),
            source_row_number=row,
            supplier_identifier=supplier,
            invoice_number=number,
            normalized_invoice_number=number,
            invoice_date=invoice_date,
            gross_amount=Decimal(amount),
            currency=currency,
        )

    def context(self, *invoices):
        return RuleContext(
            organization_id=uuid4(),
            import_batch_id=uuid4(),
            invoices=invoices,
        )

    def test_exact_duplicates_generate_one_explainable_finding(self):
        first = self.invoice(row=2, supplier="FORN-001", number="FT 2026/001")
        second = self.invoice(row=3, supplier="forn-001", number="ft 2026/001")

        findings = execute_rule(
            DUPLICATE_INVOICE_EXACT_RULE,
            self.context(first, second),
        )

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.severity, Severity.MEDIUM)
        self.assertEqual(
            [item.invoice_id for item in finding.evidence],
            [first.id, second.id],
        )
        self.assertEqual(
            finding.evidence[0].facts["supplier_identifier"],
            "FORN-001",
        )
        self.assertEqual(finding.evidence[0].facts["gross_amount"], "100.00")
        self.assertIn("2 faturas", finding.explanation)

    def test_three_duplicates_remain_a_single_finding(self):
        invoices = tuple(self.invoice(row=row) for row in (4, 2, 3))

        findings = execute_rule(
            DUPLICATE_INVOICE_EXACT_RULE,
            self.context(*invoices),
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(
            [item.facts["source_row_number"] for item in findings[0].evidence],
            [2, 3, 4],
        )

    def test_differences_in_any_key_field_do_not_generate_alert(self):
        invoices = (
            self.invoice(row=2),
            self.invoice(row=3, supplier="FORN-002"),
            self.invoice(row=4, number="FT 2026/002"),
            self.invoice(row=5, invoice_date=date(2026, 8, 2)),
            self.invoice(row=6, amount="100.01"),
            self.invoice(row=7, currency="USD"),
        )

        findings = execute_rule(
            DUPLICATE_INVOICE_EXACT_RULE,
            self.context(*invoices),
        )

        self.assertEqual(findings, ())

    def test_finding_fingerprint_is_deterministic(self):
        invoices = (self.invoice(row=2), self.invoice(row=3))
        context = self.context(*invoices)

        first = execute_rule(DUPLICATE_INVOICE_EXACT_RULE, context)
        second = execute_rule(DUPLICATE_INVOICE_EXACT_RULE, context)

        self.assertEqual(first[0].fingerprint, second[0].fingerprint)
