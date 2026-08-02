from django.conf import settings
from django.db import models

from apps.core.models import OrganizationScopedModel, UUIDTimestampedModel


class Organization(UUIDTimestampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Membership(OrganizationScopedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Proprietario"
        ANALYST = "analyst", "Analista"
        VIEWER = "viewer", "Leitor"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="uniq_membership_org_user",
            )
        ]
        ordering = ("organization__name", "user__email")

    def __str__(self):
        return f"{self.user.email} - {self.organization.name}"

