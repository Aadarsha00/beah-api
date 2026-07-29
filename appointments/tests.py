import threading
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from services.models import Service

from . import booking
from .models import Appointment, SalonClosure
from .views import AppointmentViewSet

User = get_user_model()


class BookingFixtureMixin:
    """Shared salon fixtures: two customers, a staff user, and two services."""

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


class AppointmentApiTests(BookingFixtureMixin, TestCase):
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

    @override_settings(TIME_ZONE="America/New_York")
    def test_same_day_availability_excludes_elapsed_slots_in_salon_timezone(self):
        # 14:15 UTC is 10:15 AM in Baltimore during daylight-saving time.
        fixed_now = datetime(2026, 7, 28, 14, 15, tzinfo=ZoneInfo("UTC"))
        with (
            patch("django.utils.timezone.now", return_value=fixed_now),
            # A visitor's active timezone must not change the salon's schedule.
            timezone.override(ZoneInfo("Asia/Kathmandu")),
        ):
            response = self.client.get(
                "/api/appointments/availability/",
                {"date": "2026-07-28", "service": self.short_service.pk},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["time_zone"], "America/New_York")
        slot_values = {slot["value"] for slot in response.data["slots"]}
        self.assertNotIn("09:00:00", slot_values)
        self.assertNotIn("09:30:00", slot_values)
        self.assertNotIn("10:00:00", slot_values)
        self.assertIn("10:30:00", slot_values)

    @override_settings(TIME_ZONE="America/New_York")
    def test_direct_booking_rejects_elapsed_same_day_time(self):
        fixed_now = datetime(2026, 7, 28, 14, 15, tzinfo=ZoneInfo("UTC"))
        self.client.force_authenticate(self.user)

        with (
            patch("django.utils.timezone.now", return_value=fixed_now),
            timezone.override(ZoneInfo("Asia/Kathmandu")),
        ):
            response = self.client.post(
                "/api/appointments/",
                {
                    "client_name": "Test Customer",
                    "client_email": self.user.email,
                    "client_phone": self.user.phone_number,
                    "service": self.short_service.pk,
                    "appointment_date": "2026-07-28",
                    "appointment_time": "10:00:00",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("appointment_time", response.data)
        self.assertEqual(Appointment.objects.count(), 0)

    @override_settings(TIME_ZONE="America/New_York")
    def test_direct_booking_accepts_next_future_same_day_slot(self):
        fixed_now = datetime(2026, 7, 28, 14, 15, tzinfo=ZoneInfo("UTC"))
        self.client.force_authenticate(self.user)

        with (
            patch("django.utils.timezone.now", return_value=fixed_now),
            timezone.override(ZoneInfo("Asia/Kathmandu")),
        ):
            response = self.client.post(
                "/api/appointments/",
                {
                    "client_name": "Test Customer",
                    "client_email": self.user.email,
                    "client_phone": self.user.phone_number,
                    "service": self.short_service.pk,
                    "appointment_date": "2026-07-28",
                    "appointment_time": "10:30:00",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Appointment.objects.count(), 1)

    @override_settings(TIME_ZONE="America/New_York")
    def test_my_upcoming_excludes_elapsed_same_day_appointments(self):
        fixed_now = datetime(2026, 7, 28, 14, 15, tzinfo=ZoneInfo("UTC"))
        past_today = self.appointment(
            appointment_date=fixed_now.date(),
            appointment_time=time(10, 0),
        )
        future_today = self.appointment(
            appointment_date=fixed_now.date(),
            appointment_time=time(10, 30),
        )
        future_day = self.appointment(
            appointment_date=fixed_now.date() + timedelta(days=1),
            appointment_time=time(9, 0),
        )
        self.client.force_authenticate(self.user)

        with (
            patch("django.utils.timezone.now", return_value=fixed_now),
            timezone.override(ZoneInfo("Asia/Kathmandu")),
        ):
            response = self.client.get("/api/appointments/my_upcoming/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appointment_ids = {item["id"] for item in response.data}
        self.assertNotIn(past_today.pk, appointment_ids)
        self.assertIn(future_today.pk, appointment_ids)
        self.assertIn(future_day.pk, appointment_ids)

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

    def test_confirm_does_not_revert_a_concurrent_reschedule(self):
        """Status writes must not carry a stale snapshot of the whole row back."""
        appointment = self.appointment()
        rescheduled_time = time(14, 0)
        real_get_object = AppointmentViewSet.get_object

        def reschedule_during_confirm(viewset):
            stale = real_get_object(viewset)
            # The customer reschedules between the permission check and the write.
            Appointment.objects.filter(pk=stale.pk).update(
                appointment_time=rescheduled_time
            )
            return stale

        self.client.force_authenticate(self.staff_user)
        with patch.object(
            AppointmentViewSet, "get_object", reschedule_during_confirm
        ):
            response = self.client.post(
                f"/api/appointments/{appointment.pk}/confirm/"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "confirmed")
        self.assertEqual(appointment.appointment_time, rescheduled_time)

    def test_reservation_rechecks_the_slot_after_taking_the_day_lock(self):
        """A booking that commits between validation and reservation must lose.

        Serializer validation runs before the day lock is held, so the re-check
        inside reserve_appointment is the only thing standing between two
        customers and the same chair. ConcurrentBookingTests proves the lock
        itself works, but only on MySQL; this keeps the re-check honest
        everywhere by simulating the competing write deterministically.
        """
        original_lock = booking.lock_booking_days

        def steal_slot(*dates):
            original_lock(*dates)
            self.appointment(
                client=self.other_user,
                client_name="Faster Customer",
                client_email=self.other_user.email,
                service=self.short_service,
                appointment_time=time(11, 0),
                duration_minutes=30,
                total_amount=Decimal("12.00"),
            )

        self.client.force_authenticate(self.user)
        with patch(
            "appointments.booking.lock_booking_days", side_effect=steal_slot
        ):
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

        # The simulated competitor is created inside reserve_appointment's atomic
        # block, so it rolls back with the rejected booking. What matters is that
        # the caller's booking was refused rather than stacked on the same slot.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Appointment.objects.filter(client=self.user).exists())

    def test_availability_does_not_query_once_per_slot(self):
        """Availability must not scale its query count with the slot count."""
        for hour in range(9, 17):
            self.appointment(
                appointment_time=time(hour, 0), duration_minutes=30
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                "/api/appointments/availability/",
                {
                    "date": self.booking_date.isoformat(),
                    "service": self.short_service.pk,
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLess(len(queries.captured_queries), 10)


class SalonClosureTests(BookingFixtureMixin, TestCase):
    def close_salon(self, start=None, end=None, reason="Thanksgiving"):
        start = start or self.booking_date
        return SalonClosure.objects.create(
            start_date=start, end_date=end or start, reason=reason
        )

    def test_booking_is_rejected_on_a_closed_date(self):
        self.close_salon()
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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("appointment_date", response.data)
        self.assertIn("Thanksgiving", str(response.data["appointment_date"]))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_multi_day_closure_covers_every_date_in_range(self):
        self.close_salon(
            start=self.booking_date,
            end=self.booking_date + timedelta(days=6),
            reason="Staff holiday",
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/appointments/",
            {
                "client_name": "Test Customer",
                "client_email": self.user.email,
                "client_phone": self.user.phone_number,
                "service": self.short_service.pk,
                "appointment_date": (
                    self.booking_date + timedelta(days=3)
                ).isoformat(),
                "appointment_time": "11:00:00",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_availability_reports_closure_and_offers_no_slots(self):
        self.close_salon()

        response = self.client.get(
            "/api/appointments/availability/",
            {
                "date": self.booking_date.isoformat(),
                "service": self.short_service.pk,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_closed"])
        self.assertEqual(response.data["closure_reason"], "Thanksgiving")
        self.assertEqual(response.data["slots"], [])

    def test_reschedule_into_a_closed_date_is_rejected(self):
        appointment = self.appointment()
        closed_date = self.booking_date + timedelta(days=1)
        self.close_salon(start=closed_date)
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/api/appointments/{appointment.pk}/",
            {"appointment_date": closed_date.isoformat()},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        appointment.refresh_from_db()
        self.assertEqual(appointment.appointment_date, self.booking_date)

    def test_closure_leaves_existing_bookings_for_staff_to_handle(self):
        appointment = self.appointment()
        self.close_salon()

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "booked")

    def test_staff_can_manage_closures_through_the_api(self):
        self.appointment()
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            "/api/salon-closures/",
            {
                "start_date": self.booking_date.isoformat(),
                "end_date": self.booking_date.isoformat(),
                "reason": "Thanksgiving",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Staff need to know the closed day already has customers on the books.
        self.assertEqual(response.data["affected_appointments"], 1)

    def test_closure_rejects_an_end_date_before_the_start_date(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            "/api/salon-closures/",
            {
                "start_date": self.booking_date.isoformat(),
                "end_date": (self.booking_date - timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SalonClosure.objects.exists())

    def test_customers_cannot_manage_closures(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/salon-closures/",
            {
                "start_date": self.booking_date.isoformat(),
                "end_date": self.booking_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SalonClosure.objects.exists())

    def test_unrelated_closure_does_not_block_open_dates(self):
        self.close_salon(start=self.booking_date + timedelta(days=10))
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


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentBookingTests(TransactionTestCase):
    """Row-level locking is a no-op on SQLite, so these only run on MySQL.

    Without them the double-booking defence in booking.reserve_appointment is
    never actually executed by the suite.
    """

    def setUp(self):
        self.service = Service.objects.create(
            name="Quick threading",
            description="Test service",
            price=Decimal("12.00"),
            category="threading",
            duration_minutes=30,
        )
        self.customers = [
            User.objects.create_user(
                email=f"racer{index}@example.com",
                password="strong-test-password",
                first_name="Racer",
                last_name=str(index),
                phone_number=f"+1410555020{index}",
            )
            for index in range(2)
        ]
        self.booking_date = timezone.localdate() + timedelta(days=2)

    def book_concurrently(self, payload_time):
        """POST the same slot from both customers at the same instant."""
        start_line = threading.Barrier(len(self.customers))
        statuses = []
        lock = threading.Lock()

        def book(customer):
            try:
                client = APIClient()
                client.force_authenticate(customer)
                start_line.wait(timeout=10)
                response = client.post(
                    "/api/appointments/",
                    {
                        "client_name": customer.first_name,
                        "client_email": customer.email,
                        "client_phone": customer.phone_number,
                        "service": self.service.pk,
                        "appointment_date": self.booking_date.isoformat(),
                        "appointment_time": payload_time,
                    },
                )
                with lock:
                    statuses.append(response.status_code)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=book, args=(customer,))
            for customer in self.customers
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "A booking thread deadlocked.")
        return statuses

    def test_simultaneous_requests_cannot_double_book_one_slot(self):
        statuses = self.book_concurrently("11:00:00")

        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(
            Appointment.objects.filter(
                appointment_date=self.booking_date,
                appointment_time=time(11, 0),
            ).count(),
            1,
        )

    def test_simultaneous_requests_cannot_double_book_overlapping_slots(self):
        Appointment.objects.create(
            client=self.customers[0],
            client_name="Existing",
            client_email="existing@example.com",
            client_phone="+14105550300",
            service=self.service,
            appointment_date=self.booking_date,
            appointment_time=time(9, 0),
            duration_minutes=30,
            total_amount=Decimal("12.00"),
        )

        statuses = self.book_concurrently("09:00:00")

        self.assertEqual(sorted(statuses), [400, 400])
        self.assertEqual(Appointment.objects.count(), 1)
