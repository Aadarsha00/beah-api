from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from services.models import Service

from .models import Appointment

User = get_user_model()


class AppointmentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="customer@example.com",
            password="strong-test-password",
            first_name="Test",
            last_name="Customer",
            phone_number="+14105550100",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="strong-test-password",
            first_name="Other",
            last_name="Customer",
            phone_number="+14105550101",
        )
        self.staff_user = User.objects.create_user(
            email="staff@example.com",
            password="strong-test-password",
            first_name="Staff",
            last_name="User",
            phone_number="+14105550102",
            is_staff=True,
        )
        self.service = Service.objects.create(
            name="Detailed threading",
            description="Test service",
            price=Decimal("25.00"),
            category="threading",
            duration_minutes=60,
        )
        self.short_service = Service.objects.create(
            name="Quick threading",
            description="Test service",
            price=Decimal("12.00"),
            category="threading",
            duration_minutes=30,
        )
        self.booking_date = timezone.localdate() + timedelta(days=2)

    def appointment(self, **overrides):
        values = {
            "client": self.user,
            "client_name": "Test Customer",
            "client_email": self.user.email,
            "client_phone": self.user.phone_number,
            "service": self.service,
            "appointment_date": self.booking_date,
            "appointment_time": time(10, 0),
            "duration_minutes": 60,
            "total_amount": Decimal("25.00"),
        }
        values.update(overrides)
        return Appointment.objects.create(**values)

    def test_anonymous_customer_cannot_create_booking(self):
        response = self.client.post("/api/appointments/", {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_availability_accounts_for_full_duration_without_exposing_clients(self):
        self.appointment()
        response = self.client.get(
            "/api/appointments/availability/",
            {"date": self.booking_date.isoformat(), "service": self.short_service.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slot_values = {slot["value"] for slot in response.data["slots"]}
        self.assertNotIn("10:00:00", slot_values)
        self.assertNotIn("10:30:00", slot_values)
        self.assertIn("09:30:00", slot_values)
        self.assertNotIn("client_name", response.data)

    def test_overlapping_booking_is_rejected_without_a_stylist(self):
        self.appointment()
        self.client.force_authenticate(self.other_user)
        response = self.client.post(
            "/api/appointments/",
            {
                "client_name": "Other Customer",
                "client_email": self.other_user.email,
                "client_phone": self.other_user.phone_number,
                "service": self.short_service.pk,
                "appointment_date": self.booking_date.isoformat(),
                "appointment_time": "10:30:00",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_booking_uses_authenticated_owner_and_price_snapshot(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/appointments/",
            {
                "client_name": "Test Customer",
                "client_email": self.user.email,
                "client_phone": self.user.phone_number,
                "service": self.short_service.pk,
                "appointment_date": self.booking_date.isoformat(),
                "appointment_time": "11:00:00",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.client, self.user)
        self.assertEqual(appointment.duration_minutes, 30)
        self.assertEqual(appointment.total_amount, Decimal("12.00"))
        self.assertNotIn("payment_status", response.data)
        self.assertNotIn("deposit_amount", response.data)

    def test_customer_cannot_cancel_someone_elses_appointment(self):
        appointment = self.appointment()
        self.client.force_authenticate(self.other_user)
        response = self.client.post(f"/api/appointments/{appointment.pk}/cancel/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "booked")

    def test_service_must_finish_before_closing(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/appointments/",
            {
                "client_name": "Test Customer",
                "client_email": self.user.email,
                "client_phone": self.user.phone_number,
                "service": self.service.pk,
                "appointment_date": self.booking_date.isoformat(),
                "appointment_time": "17:30:00",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_date_range_filter_is_applied(self):
        first = self.appointment()
        later = self.appointment(
            appointment_date=self.booking_date + timedelta(days=5),
            appointment_time=time(12, 0),
        )
        self.client.force_authenticate(self.staff_user)

        response = self.client.get(
            "/api/appointments/",
            {
                "appointment_date__gte": (
                    self.booking_date + timedelta(days=1)
                ).isoformat()
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data["results"]}
        self.assertNotIn(first.pk, ids)
        self.assertIn(later.pk, ids)

    def test_admin_cannot_confirm_a_past_appointment(self):
        appointment = self.appointment(
            appointment_date=timezone.localdate() - timedelta(days=1)
        )
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            f"/api/appointments/{appointment.pk}/confirm/"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "booked")

    def test_service_with_booking_cannot_be_deleted(self):
        appointment = self.appointment()
        self.client.force_authenticate(self.staff_user)

        response = self.client.delete(f"/api/services/{self.service.pk}/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Service.objects.filter(pk=self.service.pk).exists())
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())
