from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import ContactMessage, Promotion

User = get_user_model()


class ContactMessageTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_visitor_can_send_real_contact_message(self):
        response = APIClient().post(
            "/api/contact-messages/",
            {
                "name": "Visitor",
                "email": "visitor@example.com",
                "phone": "+14105550125",
                "subject": "Service enquiry: Henna",
                "message": "I would like more information about henna.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)

    @override_settings(
        SEND_CONTACT_EMAILS=True,
        ADMIN_EMAIL="owner@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_contact_message_notifies_owner_and_sends_reply(self):
        response = APIClient().post(
            "/api/contact-messages/",
            {
                "name": "<Visitor>",
                "email": "visitor@example.com",
                "subject": "Service enquiry",
                "message": "<strong>Please call me</strong>",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertEqual(mail.outbox[1].to, ["visitor@example.com"])
        self.assertIn("&lt;strong&gt;", mail.outbox[0].alternatives[0].content)

    @override_settings(SEND_CONTACT_EMAILS=False)
    def test_contact_message_has_tighter_abuse_throttle(self):
        client = APIClient()
        payload = {
            "name": "Visitor",
            "email": "visitor@example.com",
            "subject": "Service enquiry",
            "message": "Please tell me more.",
        }
        responses = [
            client.post(
                "/api/contact-messages/",
                payload,
                REMOTE_ADDR="203.0.113.75",
            )
            for _ in range(6)
        ]

        self.assertTrue(
            all(response.status_code == status.HTTP_201_CREATED for response in responses[:5])
        )
        self.assertEqual(
            responses[5].status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )


class PublicPromotionTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        common = {
            "description": "Promotion details",
            "discount_percentage": Decimal("10.00"),
        }
        self.current = Promotion.objects.create(
            title="Current",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            is_active=True,
            **common,
        )
        self.inactive = Promotion.objects.create(
            title="Inactive",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            is_active=False,
            **common,
        )
        self.upcoming = Promotion.objects.create(
            title="Upcoming",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
            is_active=True,
            **common,
        )
        self.staff = User.objects.create_user(
            email="promotion-admin@example.com",
            password="strong-test-password",
            first_name="Promotion",
            last_name="Admin",
            phone_number="+14105550145",
            is_staff=True,
        )

    def test_public_list_and_retrieve_expose_only_current_promotions(self):
        client = APIClient()
        response = client.get("/api/promotions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [self.current.pk],
        )
        hidden_response = client.get(f"/api/promotions/{self.inactive.pk}/")
        self.assertEqual(hidden_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_future_promotion_action_requires_staff(self):
        response = APIClient().get("/api/promotions/upcoming/")
        self.assertIn(
            response.status_code,
            {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN},
        )

        staff_client = APIClient()
        staff_client.force_authenticate(self.staff)
        staff_response = staff_client.get("/api/promotions/upcoming/")
        self.assertEqual(staff_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in staff_response.data],
            [self.upcoming.pk],
        )
