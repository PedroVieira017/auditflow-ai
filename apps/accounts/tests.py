from django.contrib.auth import get_user_model
from django.test import TestCase


class UserModelTests(TestCase):
    def test_user_uses_normalized_email_as_identity(self):
        user = get_user_model().objects.create_user(
            email="Analista@EXAMPLE.com",
            password="uma-password-segura",
        )

        self.assertEqual(user.email, "Analista@example.com")
        self.assertTrue(user.check_password("uma-password-segura"))

    def test_email_is_required(self):
        with self.assertRaisesMessage(ValueError, "email e obrigatorio"):
            get_user_model().objects.create_user(email="", password="password")

