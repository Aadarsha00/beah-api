from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import ContactMessage


class ContactMessageTests(TestCase):
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
