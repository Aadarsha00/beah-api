import re

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

# The activation link is built from the deployment's frontend settings, which a
# developer's local .env points at localhost. Pin them so this test asserts the
# link format rather than whatever environment happens to be configured.
PRODUCTION_FRONTEND_DJOSER = {
    **django_settings.DJOSER,
    "EMAIL_FRONTEND_DOMAIN": "beautifulbrowsandhenna.com",
    "EMAIL_FRONTEND_PROTOCOL": "https",
}


class RegistrationTests(TestCase):
    @override_settings(DJOSER=PRODUCTION_FRONTEND_DJOSER)
    def test_registration_sends_activation_email_before_login(self):
        response = APIClient().post(
            "/api/auth/users/",
            {
                "first_name": "New",
                "last_name": "Customer",
                "email": "new@example.com",
                "phone_number": "+14105550123",
                "password": "a-strong-test-password",
                "re_password": "a-strong-test-password",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new@example.com")
        self.assertFalse(user.is_active)
        self.assertEqual(user.phone_number, "+14105550123")
        self.assertEqual(len(mail.outbox), 1)

        activation_email = mail.outbox[0]
        self.assertEqual(activation_email.to, ["new@example.com"])
        activation_match = re.search(
            r"https://beautifulbrowsandhenna\.com/activate/([^/\s]+)/([^/\s<]+)",
            activation_email.body,
        )
        self.assertIsNotNone(activation_match)

        mail.outbox.clear()
        resend_response = APIClient().post(
            "/api/auth/users/resend_activation/",
            {"email": "new@example.com"},
        )
        self.assertEqual(resend_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(len(mail.outbox), 1)

        login_before_activation = APIClient().post(
            "/api/auth/jwt/create/",
            {
                "email": "new@example.com",
                "password": "a-strong-test-password",
            },
        )
        self.assertEqual(
            login_before_activation.status_code, status.HTTP_401_UNAUTHORIZED
        )

        uid, token = activation_match.groups()
        activation_response = APIClient().post(
            "/api/auth/users/activation/",
            {"uid": uid, "token": token},
        )
        self.assertEqual(
            activation_response.status_code, status.HTTP_204_NO_CONTENT
        )

        user.refresh_from_db()
        self.assertTrue(user.is_active)

        login_after_activation = APIClient().post(
            "/api/auth/jwt/create/",
            {
                "email": "new@example.com",
                "password": "a-strong-test-password",
            },
        )
        self.assertEqual(login_after_activation.status_code, status.HTTP_200_OK)
        self.assertIn("access", login_after_activation.data)

    def test_normal_user_does_not_have_arbitrary_permissions(self):
        user = User.objects.create_user(
            email="user@example.com",
            password="a-strong-test-password",
            first_name="Normal",
            last_name="User",
            phone_number="+14105550124",
        )
        self.assertFalse(user.has_perm("accounts.delete_user"))

    def test_logout_blacklists_refresh_token(self):
        user = User.objects.create_user(
            email="logout@example.com",
            password="a-strong-test-password",
            first_name="Logout",
            last_name="User",
            phone_number="+14105550126",
        )
        refresh = RefreshToken.for_user(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = client.post("/api/auth/logout/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        refresh_response = APIClient().post(
            "/api/auth/jwt/refresh/", {"refresh": str(refresh)}
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_current_user_exposes_staff_status_without_allowing_escalation(self):
        user = User.objects.create_user(
            email="profile@example.com",
            password="a-strong-test-password",
            first_name="Profile",
            last_name="User",
            phone_number="+14105550127",
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.get("/api/auth/users/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_staff"])

        update_response = client.patch(
            "/api/auth/users/me/", {"is_staff": True}, format="json"
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
