from django.shortcuts import get_object_or_404

from .models import Membership


def get_active_membership(*, user, organization_id):
    return get_object_or_404(
        Membership.objects.select_related("organization"),
        organization_id=organization_id,
        organization__is_active=True,
        user=user,
        is_active=True,
    )
