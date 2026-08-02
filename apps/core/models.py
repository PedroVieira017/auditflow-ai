import uuid

from django.db import models


class UUIDTimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrganizationScopedQuerySet(models.QuerySet):
    def for_organization(self, organization):
        organization_id = getattr(organization, "pk", organization)
        return self.filter(organization_id=organization_id)


class OrganizationScopedModel(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = OrganizationScopedQuerySet.as_manager()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True
