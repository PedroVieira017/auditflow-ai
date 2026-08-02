from django.conf import settings
from django.core.validators import MinLengthValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.core.models import OrganizationScopedModel


class ImportBatch(OrganizationScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Em processamento"
        COMPLETED = "completed", "Concluida"
        FAILED = "failed", "Falhou"

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="import_batches",
    )
    original_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=500, blank=True)
    file_sha256 = models.CharField(
        max_length=64,
        validators=[
            MinLengthValidator(64),
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="O hash deve ser um SHA-256 hexadecimal em minusculas.",
            ),
        ],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    column_mapping = models.JSONField(default=dict, blank=True)
    error_summary = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    valid_row_count = models.PositiveIntegerField(default=0)
    invalid_row_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "file_sha256"),
                name="uniq_import_org_file_hash",
            ),
            models.CheckConstraint(
                condition=Q(row_count__gte=0),
                name="import_row_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(valid_row_count__gte=0),
                name="import_valid_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(invalid_row_count__gte=0),
                name="import_invalid_count_nonnegative",
            ),
        ]
        ordering = ("-created_at",)

    def __str__(self):
        return self.original_filename

