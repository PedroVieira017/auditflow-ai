from django.conf import settings
from django.db import models

from apps.core.models import OrganizationScopedModel


class AuditEvent(OrganizationScopedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=120)
    resource_type = models.CharField(max_length=120)
    resource_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("organization", "created_at"),
                name="audit_org_created_idx",
            )
        ]
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.action} - {self.resource_type}"

