# payments/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class Payment(models.Model):
    PAYMENT_TYPE_CHOICES = [
        ("deposit", "Deposit"),
        ("full_payment", "Full Payment"),
        ("refund", "Refund"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
        ("refunded", "Refunded"),
        ("partially_refunded", "Partially Refunded"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("card", "Credit/Debit Card"),
        ("cash", "Cash"),
        ("bank_transfer", "Bank Transfer"),
    ]

    # Identifiers
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True)

    # Relationships
    appointment = models.ForeignKey(
        "appointments.Appointment", on_delete=models.CASCADE, related_name="payments"
    )
    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="payments", null=True, blank=True
    )

    # Payment Details
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default="card"
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")

    # Status and Metadata
    status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default="pending"
    )
    description = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["appointment", "payment_type"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.payment_type.title()} - ${self.amount} - {self.status}"

    def save(self, *args, **kwargs):
        # Set client from appointment if not provided
        if not self.client and self.appointment.client:
            self.client = self.appointment.client

        # Set processed_at when status changes to succeeded
        if self.status == "succeeded" and not self.processed_at:
            self.processed_at = timezone.now()

        super().save(*args, **kwargs)

    @property
    def is_successful(self):
        return self.status == "succeeded"

    @property
    def can_be_refunded(self):
        return self.status == "succeeded" and self.payment_type != "refund"


class PaymentRefund(models.Model):
    REFUND_REASON_CHOICES = [
        ("requested_by_customer", "Requested by Customer"),
        ("duplicate", "Duplicate"),
        ("fraudulent", "Fraudulent"),
        ("subscription_canceled", "Subscription Canceled"),
        ("expired_uncaptured_charge", "Expired Uncaptured Charge"),
    ]

    REFUND_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
    ]

    # Identifiers
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_refund_id = models.CharField(max_length=255, blank=True, null=True)

    # Relationships
    original_payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="refunds"
    )
    refund_payment = models.OneToOneField(
        Payment,
        on_delete=models.CASCADE,
        related_name="refund_record",
        null=True,
        blank=True,
    )

    # Refund Details
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    reason = models.CharField(
        max_length=30, choices=REFUND_REASON_CHOICES, default="requested_by_customer"
    )
    status = models.CharField(
        max_length=20, choices=REFUND_STATUS_CHOICES, default="pending"
    )
    notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund ${self.amount} for Payment {self.original_payment.id}"

    def save(self, *args, **kwargs):
        if self.status == "succeeded" and not self.processed_at:
            self.processed_at = timezone.now()
        super().save(*args, **kwargs)
