from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.core.choices import Severity
from apps.core.models import OrganizationScopedModel, UUIDTimestampedModel


class RuleDefinition(UUIDTimestampedModel):
    key = models.CharField(
        max_length=100,
        validators=[
            RegexValidator(
                regex=r"^[A-Z][A-Z0-9_]*$",
                message="A chave deve usar letras maiusculas, numeros e underscores.",
            )
        ],
    )
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    description = models.TextField()
    default_severity = models.CharField(max_length=20, choices=Severity.choices)
    parameters_schema = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version"),
                name="uniq_rule_key_version",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="rule_version_positive",
            ),
        ]
        ordering = ("key", "-version")

    def __str__(self):
        return f"{self.key} v{self.version}"


class RuleRun(OrganizationScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        RUNNING = "running", "Em execucao"
        COMPLETED = "completed", "Concluida"
        FAILED = "failed", "Falhou"

    import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.CASCADE,
        related_name="rule_runs",
    )
    rule_definition = models.ForeignKey(
        RuleDefinition,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    parameters = models.JSONField(default=dict, blank=True)
    alert_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(alert_count__gte=0),
                name="rule_run_alert_count_nonnegative",
            )
        ]
        ordering = ("-created_at",)

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
        return f"{self.rule_definition} - {self.import_batch}"

