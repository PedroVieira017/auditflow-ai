from django.test import SimpleTestCase
from django.urls import reverse


class HealthCheckTests(SimpleTestCase):
    def test_health_check_reports_service_is_available(self):
        response = self.client.get(reverse("core:health-check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "auditflow"},
        )

    def test_health_check_rejects_post_requests(self):
        response = self.client.post(reverse("core:health-check"))

        self.assertEqual(response.status_code, 405)

