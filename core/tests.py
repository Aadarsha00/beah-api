from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase


class HealthEndpointTests(TestCase):
    def test_liveness_does_not_require_database_work(self):
        with patch("core.views.connection.cursor") as cursor:
            response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        cursor.assert_not_called()

    def test_readiness_checks_database(self):
        response = self.client.get("/api/ready/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_readiness_returns_503_without_leaking_error_details(self):
        with patch(
            "core.views.connection.cursor",
            side_effect=OperationalError("secret database details"),
        ):
            response = self.client.get("/api/ready/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
