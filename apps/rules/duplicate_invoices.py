from collections import defaultdict

from apps.core.choices import Severity
from apps.imports.contracts import normalize_match_text

from .engine import RuleEvidence, RuleFinding, RuleMetadata


class DuplicateInvoiceExactRule:
    metadata = RuleMetadata(
        key="DUPLICATE_INVOICE_EXACT",
        version=1,
        name="Faturas potencialmente duplicadas",
        description=(
            "Agrupa faturas com o mesmo fornecedor, numero, data, valor e moeda."
        ),
        default_severity=Severity.MEDIUM,
        parameters_schema={},
    )

    def evaluate(self, context):
        grouped_invoices = defaultdict(list)
        for invoice in context.invoices:
            duplicate_key = (
                normalize_match_text(invoice.supplier_identifier),
                normalize_match_text(invoice.normalized_invoice_number),
                invoice.invoice_date.isoformat(),
                format(invoice.gross_amount, ".2f"),
                invoice.currency,
            )
            grouped_invoices[duplicate_key].append(invoice)

        findings = []
        for duplicate_key in sorted(grouped_invoices):
            invoices = sorted(
                grouped_invoices[duplicate_key],
                key=lambda invoice: (invoice.source_row_number, str(invoice.id)),
            )
            if len(invoices) < 2:
                continue

            supplier, invoice_number, invoice_date, amount, currency = duplicate_key
            findings.append(
                RuleFinding(
                    identity={
                        "supplier_identifier": supplier,
                        "invoice_number": invoice_number,
                        "invoice_date": invoice_date,
                        "gross_amount": amount,
                        "currency": currency,
                    },
                    title="Possiveis faturas duplicadas",
                    explanation=(
                        f"Foram encontradas {len(invoices)} faturas com o mesmo "
                        "fornecedor, numero, data, valor e moeda."
                    ),
                    severity=Severity.MEDIUM,
                    recommended_action=(
                        "Comparar os documentos de origem e confirmar se representam "
                        "a mesma obrigacao antes de autorizar qualquer pagamento."
                    ),
                    evidence=tuple(
                        RuleEvidence(
                            invoice_id=invoice.id,
                            facts={
                                "source_row_number": invoice.source_row_number,
                                "supplier_identifier": supplier,
                                "invoice_number": invoice_number,
                                "invoice_date": invoice_date,
                                "gross_amount": amount,
                                "currency": currency,
                            },
                        )
                        for invoice in invoices
                    ),
                )
            )

        return findings


DUPLICATE_INVOICE_EXACT_RULE = DuplicateInvoiceExactRule()
