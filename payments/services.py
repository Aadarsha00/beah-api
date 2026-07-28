import stripe
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import logging
from typing import Dict, Optional, Tuple

from .models import Payment, PaymentRefund
from appointments.models import Appointment

logger = logging.getLogger(__name__)

# Set Stripe API key
stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")


class StripeService:
    """Service class for handling Stripe payment operations"""

    @staticmethod
    def create_payment_intent(
        appointment: Appointment,
        payment_type: str,
        amount: Decimal,
        client_email: Optional[str] = None,
    ) -> Tuple[stripe.PaymentIntent, Payment]:
        """
        Create a Stripe PaymentIntent and corresponding Payment record

        Args:
            appointment: The appointment to create payment for
            payment_type: Type of payment (deposit, full_payment)
            amount: Payment amount
            client_email: Client email for Stripe customer

        Returns:
            Tuple of (PaymentIntent, Payment)
        """
        try:
            # Convert amount to cents for Stripe
            amount_cents = int(amount * 100)

            # Create description
            service_name = (
                appointment.service.name if appointment.service else "Service"
            )
            description = (
                f"{payment_type.replace('_', ' ').title()} for {service_name} "
                f"on {appointment.appointment_date}"
            )

            # Prepare metadata
            metadata = {
                "appointment_id": str(appointment.id),
                "payment_type": payment_type,
                "client_name": appointment.client_name,
                "service_name": service_name,
            }

            # Create PaymentIntent
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=settings.STRIPE_CURRENCY.lower(),
                automatic_payment_methods={"enabled": True},
                description=description,
                metadata=metadata,
                receipt_email=client_email or appointment.client_email,
            )

            # Create Payment record
            payment = Payment.objects.create(
                stripe_payment_intent_id=payment_intent.id,
                appointment=appointment,
                client=appointment.client,
                payment_type=payment_type,
                amount=amount,
                currency=settings.STRIPE_CURRENCY,
                status="pending",
                description=description,
            )

            logger.info(
                f"Created PaymentIntent {payment_intent.id} for appointment {appointment.id}"
            )

            return payment_intent, payment

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating PaymentIntent: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating PaymentIntent: {e}")
            raise

    @staticmethod
    def confirm_payment(payment: Payment) -> Payment:
        """
        Confirm a payment by checking its status with Stripe

        Args:
            payment: Payment object to confirm

        Returns:
            Updated Payment object
        """
        try:
            if not payment.stripe_payment_intent_id:
                raise ValueError("Payment has no associated PaymentIntent")

            # Retrieve PaymentIntent from Stripe
            payment_intent = stripe.PaymentIntent.retrieve(
                payment.stripe_payment_intent_id
            )

            # Update payment status based on PaymentIntent status
            status_mapping = {
                "succeeded": "succeeded",
                "processing": "processing",
                "requires_payment_method": "failed",
                "requires_confirmation": "pending",
                "requires_action": "pending",
                "canceled": "canceled",
            }

            new_status = status_mapping.get(payment_intent.status, "pending")

            # Update payment record
            payment.status = new_status

            if payment_intent.charges.data:
                charge = payment_intent.charges.data[0]
                payment.stripe_charge_id = charge.id

                if charge.outcome:
                    payment.failure_reason = charge.outcome.reason or ""

            if new_status == "succeeded":
                payment.processed_at = timezone.now()

                # Update appointment payment status
                StripeService._update_appointment_payment_status(payment.appointment)

            payment.save()

            logger.info(f"Updated payment {payment.id} status to {new_status}")

            return payment

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error confirming payment: {e}")
            payment.status = "failed"
            payment.failure_reason = str(e)
            payment.save()
            raise
        except Exception as e:
            logger.error(f"Error confirming payment: {e}")
            raise

    @staticmethod
    def create_refund(
        payment: Payment,
        amount: Decimal,
        reason: str = "requested_by_customer",
        notes: str = "",
    ) -> Tuple[stripe.Refund, PaymentRefund]:
        """
        Create a refund for a payment

        Args:
            payment: Original payment to refund
            amount: Refund amount
            reason: Reason for refund
            notes: Additional notes

        Returns:
            Tuple of (Stripe Refund, PaymentRefund)
        """
        try:
            if not payment.can_be_refunded:
                raise ValueError("Payment cannot be refunded")

            # Convert amount to cents for Stripe
            amount_cents = int(amount * 100)

            # Create refund in Stripe
            refund = stripe.Refund.create(
                charge=payment.stripe_charge_id,
                amount=amount_cents,
                reason=reason,
                metadata={
                    "original_payment_id": str(payment.id),
                    "appointment_id": str(payment.appointment.id),
                },
            )

            # Create refund Payment record
            refund_payment = Payment.objects.create(
                appointment=payment.appointment,
                client=payment.client,
                payment_type="refund",
                amount=amount,
                currency=payment.currency,
                status="processing",
                description=f"Refund for {payment.payment_type}",
            )

            # Create PaymentRefund record
            payment_refund = PaymentRefund.objects.create(
                stripe_refund_id=refund.id,
                original_payment=payment,
                refund_payment=refund_payment,
                amount=amount,
                reason=reason,
                status="processing",
                notes=notes,
            )

            # Update refund status based on Stripe response
            if refund.status == "succeeded":
                payment_refund.status = "succeeded"
                payment_refund.processed_at = timezone.now()
                refund_payment.status = "succeeded"
                refund_payment.processed_at = timezone.now()

                # Update original payment status if fully refunded
                total_refunded = PaymentRefund.objects.filter(
                    original_payment=payment, status="succeeded"
                ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

                if total_refunded >= payment.amount:
                    payment.status = "refunded"
                else:
                    payment.status = "partially_refunded"
                payment.save()

                # Update appointment payment status
                StripeService._update_appointment_payment_status(payment.appointment)

            payment_refund.save()
            refund_payment.save()

            logger.info(f"Created refund {refund.id} for payment {payment.id}")

            return refund, payment_refund

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating refund: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating refund: {e}")
            raise

    @staticmethod
    def _update_appointment_payment_status(appointment: Appointment) -> None:
        """
        Update appointment payment status based on successful payments

        Args:
            appointment: Appointment to update
        """
        # Calculate total paid amount
        total_paid = Payment.objects.filter(
            appointment=appointment,
            status="succeeded",
            payment_type__in=["deposit", "full_payment"],
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        # Calculate total refunded amount
        total_refunded = Payment.objects.filter(
            appointment=appointment, status="succeeded", payment_type="refund"
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        net_paid = total_paid - total_refunded

        # Update appointment payment status
        if net_paid >= appointment.total_amount:
            appointment.payment_status = "paid"
        elif net_paid >= appointment.deposit_amount and appointment.deposit_amount > 0:
            appointment.payment_status = "deposit_paid"
        elif net_paid <= 0:
            appointment.payment_status = "pending"

        appointment.save()

        logger.info(
            f"Updated appointment {appointment.id} payment status to {appointment.payment_status}"
        )

    @staticmethod
    def handle_webhook_event(event: Dict) -> None:
        """
        Handle Stripe webhook events

        Args:
            event: Stripe event data
        """
        try:
            event_type = event["type"]

            if event_type == "payment_intent.succeeded":
                payment_intent = event["data"]["object"]
                StripeService._handle_payment_intent_succeeded(payment_intent)

            elif event_type == "payment_intent.payment_failed":
                payment_intent = event["data"]["object"]
                StripeService._handle_payment_intent_failed(payment_intent)

            elif event_type == "charge.dispute.created":
                charge = event["data"]["object"]
                StripeService._handle_chargeback(charge)

            logger.info(f"Processed webhook event: {event_type}")

        except Exception as e:
            logger.error(f"Error processing webhook event {event_type}: {e}")
            raise

    @staticmethod
    def _handle_payment_intent_succeeded(payment_intent: Dict) -> None:
        """Handle successful payment intent"""
        try:
            payment = Payment.objects.get(stripe_payment_intent_id=payment_intent["id"])
            payment.status = "succeeded"
            payment.processed_at = timezone.now()
            payment.save()

            # Update appointment payment status
            StripeService._update_appointment_payment_status(payment.appointment)

        except Payment.DoesNotExist:
            logger.warning(
                f"Payment not found for PaymentIntent {payment_intent['id']}"
            )

    @staticmethod
    def _handle_payment_intent_failed(payment_intent: Dict) -> None:
        """Handle failed payment intent"""
        try:
            payment = Payment.objects.get(stripe_payment_intent_id=payment_intent["id"])
            payment.status = "failed"
            payment.failure_reason = payment_intent.get("last_payment_error", {}).get(
                "message", ""
            )
            payment.save()

        except Payment.DoesNotExist:
            logger.warning(
                f"Payment not found for PaymentIntent {payment_intent['id']}"
            )

    @staticmethod
    def _handle_chargeback(charge: Dict) -> None:
        """Handle chargeback/dispute"""
        try:
            payment = Payment.objects.get(stripe_charge_id=charge["id"])
            # You might want to create a separate model for disputes
            # For now, just log the event
            logger.warning(f"Chargeback created for payment {payment.id}")

        except Payment.DoesNotExist:
            logger.warning(f"Payment not found for charge {charge['id']}")


# Add to your Django models for proper imports
from django.db import models
