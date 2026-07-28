from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class RegistrationTests(TestCase):
    def test_registration_accepts_profile_fields_and_activates_user(self):
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
        self.assertTrue(user.is_active)
        self.assertEqual(user.phone_number, "+14105550123")

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
