from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.choices import Severity
from apps.core.models import OrganizationScopedModel


class Alert(OrganizationScopedModel):
    class Status(models.TextChoices):
        NEW = "new", "Novo"
        VALID = "valid", "Valido"
        FALSE_POSITIVE = "false_positive", "Falso positivo"
        RESOLVED = "resolved", "Resolvido"

    rule_run = models.ForeignKey(
        "rules.RuleRun",
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    fingerprint = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    explanation = models.TextField()
    severity = models.CharField(max_length=20, choices=Severity.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    recommended_action = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("rule_run", "fingerprint"),
                name="uniq_alert_run_fingerprint",
            )
        ]
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        if (
            self.organization_id
            and self.rule_run_id
            and self.rule_run.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"rule_run": "A execucao pertence a outra organizacao."}
            )

    def __str__(self):
        return self.title


class AlertEvidence(OrganizationScopedModel):
    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    invoice_record = models.ForeignKey(
        "invoices.InvoiceRecord",
        on_delete=models.PROTECT,
        related_name="alert_evidence",
    )
    facts = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("alert", "invoice_record"),
                name="uniq_alert_invoice_evidence",
            )
        ]
        ordering = ("created_at",)

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.organization_id
            and self.alert_id
            and self.alert.organization_id != self.organization_id
        ):
            errors["alert"] = "O alerta pertence a outra organizacao."
        if (
            self.organization_id
            and self.invoice_record_id
            and self.invoice_record.organization_id != self.organization_id
        ):
            errors["invoice_record"] = "A fatura pertence a outra organizacao."
        if errors:
            raise ValidationError(errors)


class AlertStatusEvent(OrganizationScopedModel):
    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="alert_status_events",
    )
    from_status = models.CharField(max_length=20, choices=Alert.Status.choices)
    to_status = models.CharField(max_length=20, choices=Alert.Status.choices)
    note = models.TextField(max_length=2_000)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(from_status=F("to_status")),
                name="alert_status_event_changes_status",
            )
        ]
        ordering = ("created_at",)

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.organization_id
            and self.alert_id
            and self.alert.organization_id != self.organization_id
        ):
            errors["alert"] = "O alerta pertence a outra organizacao."
        if self.from_status == self.to_status:
            errors["to_status"] = "O novo estado deve ser diferente do atual."
        if not (self.note or "").strip():
            errors["note"] = "A justificação da alteração é obrigatória."
        if errors:
            raise ValidationError(errors)
