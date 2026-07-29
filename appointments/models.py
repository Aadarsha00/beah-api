from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class BookingDayLock(models.Model):
    """One row per day used to serialize reservations for that day."""

    date = models.DateField(unique=True)

    def __str__(self):
        return f"Booking lock for {self.date}"


class SalonClosure(models.Model):
    """An inclusive date range on which the salon takes no appointments.

    Closures only block new bookings and reschedules. Appointments already on
    the books are left untouched so staff can contact those customers instead
    of having bookings silently disappear.
    """

    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="salonclosure_end_date_not_before_start_date",
            )
        ]

    def __str__(self):
        if self.start_date == self.end_date:
            span = self.start_date.isoformat()
        else:
            span = f"{self.start_date} to {self.end_date}"
        return f"Closed {span} ({self.reason})" if self.reason else f"Closed {span}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )

    def booking_message(self):
        if self.reason:
            return f"The salon is closed on this date ({self.reason})."
        return "The salon is closed on this date."


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("booked", "Booked"),
        ("confirmed", "Confirmed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("no_show", "No Show"),
        ("late_cancelled", "Late Cancelled"),
    ]
    client = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="appointments",
        null=True,
        blank=True,
    )
    client_name = models.CharField(max_length=100)
    client_email = models.EmailField()
    phone_regex = RegexValidator(
        regex=r"^\+?1?\d{9,15}$",
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.",
    )
    client_phone = models.CharField(validators=[phone_regex], max_length=17)

    service = models.ForeignKey("services.Service", on_delete=models.PROTECT)
    stylist = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stylist_appointments",
    )

    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="booked")
    # Snapshot of the service price at the time of booking.
    total_amount = models.DecimalField(max_digits=6, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-appointment_date", "-appointment_time"]

    def __str__(self):
        return f"{self.client_name} - {self.service.name} on {self.appointment_date} at {self.appointment_time}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.total_amount:
            self.total_amount = self.service.price
        if self._state.adding and not self.duration_minutes:
            self.duration_minutes = self.service.duration_minutes
        super().save(*args, **kwargs)

    def appointment_datetime(self):
        naive_value = timezone.datetime.combine(
            self.appointment_date, self.appointment_time
        )
        return timezone.make_aware(naive_value, timezone.get_default_timezone())

    def can_cancel(self):
        return (
            self.status in {"booked", "confirmed"}
            and timezone.now() + timedelta(hours=24) < self.appointment_datetime()
        )

    def is_past_due(self):
        return timezone.now() > self.appointment_datetime()
