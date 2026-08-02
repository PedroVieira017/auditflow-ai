from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import OrganizationScopedModel


class InvoiceRecord(OrganizationScopedModel):
    import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.CASCADE,
        related_name="invoice_records",
    )
    source_row_number = models.PositiveIntegerField()
    supplier_identifier = models.CharField(max_length=120)
    supplier_name = models.CharField(max_length=255, blank=True)
    invoice_number = models.CharField(max_length=120)
    normalized_invoice_number = models.CharField(max_length=120)
    invoice_date = models.DateField()
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(
        max_length=3,
        validators=[
            RegexValidator(
                regex=r"^[A-Z]{3}$",
                message="A moeda deve usar um codigo ISO com tres letras maiusculas.",
            )
        ],
    )
    source_values = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("import_batch", "source_row_number"),
                name="uniq_invoice_import_source_row",
            )
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization",
                    "supplier_identifier",
                    "normalized_invoice_number",
                ),
                name="invoice_duplicate_lookup_idx",
            )
        ]
        ordering = ("source_row_number",)

    def clean(self):
        super().clean()
        if (
            self.organization_id
            and self.import_batch_id
            and self.import_batch.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"import_batch": "A importacao pertence a outra organizacao."}
            )

    def __str__(self):
        return f"{self.supplier_identifier} - {self.invoice_number}"

