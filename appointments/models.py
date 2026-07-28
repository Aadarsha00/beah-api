# appointments/models.py - Updated to work with payments

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

User = get_user_model()


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("booked", "Booked"),
        ("confirmed", "Confirmed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("no_show", "No Show"),
        ("late_cancelled", "Late Cancelled"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("deposit_paid", "Deposit Paid"),
        ("paid", "Paid"),
        ("refunded", "Refunded"),
    ]

    # Client Information
    client = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
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

    # Service Information
    service = models.ForeignKey("services.Service", on_delete=models.CASCADE)
    stylist = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stylist_appointments",
    )

    # Appointment Details
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    # Status and Payment
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="booked")
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default="pending"
    )
    deposit_amount = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00")
    )
    total_amount = models.DecimalField(max_digits=6, decimal_places=2)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-appointment_date", "-appointment_time"]
        unique_together = ["appointment_date", "appointment_time", "stylist"]

    def __str__(self):
        return f"{self.client_name} - {self.service.name} on {self.appointment_date} at {self.appointment_time}"

    def save(self, *args, **kwargs):
        # Set total amount from service price
        if not self.total_amount:
            self.total_amount = self.service.price
        # Set duration from service
        if not self.duration_minutes:
            self.duration_minutes = self.service.duration_minutes
        # Set deposit amount if required
        if self.service.requires_deposit and not self.deposit_amount:
            self.deposit_amount = self.service.deposit_amount
        super().save(*args, **kwargs)

    def can_cancel(self):
        """Check if appointment can be cancelled (24 hours before)"""
        appointment_datetime = timezone.make_aware(
            timezone.datetime.combine(self.appointment_date, self.appointment_time)
        )
        return timezone.now() + timedelta(hours=24) < appointment_datetime

    def is_past_due(self):
        """Check if appointment is past due"""
        appointment_datetime = timezone.make_aware(
            timezone.datetime.combine(self.appointment_date, self.appointment_time)
        )
        return timezone.now() > appointment_datetime

    # New payment-related methods
    def get_total_paid(self):
        """Get total amount paid for this appointment"""
        from payments.models import Payment

        total_paid = Payment.objects.filter(
            appointment=self,
            status="succeeded",
            payment_type__in=["deposit", "full_payment"],
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        total_refunded = Payment.objects.filter(
            appointment=self, status="succeeded", payment_type="refund"
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        return total_paid - total_refunded

    def get_remaining_balance(self):
        """Get remaining balance to be paid"""
        return self.total_amount - self.get_total_paid()

    def has_deposit_paid(self):
        """Check if deposit has been paid"""
        from payments.models import Payment

        if self.deposit_amount <= 0:
            return True  # No deposit required

        return Payment.objects.filter(
            appointment=self, payment_type="deposit", status="succeeded"
        ).exists()

    def is_fully_paid(self):
        """Check if appointment is fully paid"""
        return self.get_remaining_balance() <= Decimal("0.00")

    def can_be_refunded(self):
        """Check if appointment can be refunded"""
        return self.get_total_paid() > Decimal("0.00")

    @property
    def payment_summary(self):
        """Get a summary of payments for this appointment"""
        from payments.models import Payment

        payments = Payment.objects.filter(appointment=self).order_by("-created_at")

        return {
            "total_amount": self.total_amount,
            "deposit_amount": self.deposit_amount,
            "total_paid": self.get_total_paid(),
            "remaining_balance": self.get_remaining_balance(),
            "is_fully_paid": self.is_fully_paid(),
            "has_deposit_paid": self.has_deposit_paid(),
            "payments": payments,
            "payment_status": self.payment_status,
        }
