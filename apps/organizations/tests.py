from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Membership, Organization


class MembershipModelTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Empresa Exemplo",
            slug="empresa-exemplo",
        )
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="password",
        )

    def test_user_can_only_have_one_membership_per_organization(self):
        Membership.objects.create(
            organization=self.organization,
            user=self.user,
            role=Membership.Role.OWNER,
        )

        with self.assertRaises(ValidationError):
            Membership.objects.create(
                organization=self.organization,
                user=self.user,
                role=Membership.Role.ANALYST,
            )
