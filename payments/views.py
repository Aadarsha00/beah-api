# payments/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.conf import settings
import stripe
import json
import logging
from decimal import Decimal

from .models import Payment, PaymentRefund
from .serializers import (
    PaymentSerializer,
    PaymentIntentCreateSerializer,
    PaymentConfirmSerializer,
    PaymentRefundSerializer,
)
from .services import StripeService
from appointments.models import Appointment

logger = logging.getLogger(__name__)


class PaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing payments"""

    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "payment_type", "appointment"]

    def get_permissions(self):
        if self.action in ["create_payment_intent", "confirm_payment"]:
            permission_classes = [permissions.AllowAny]  # Allow anonymous payments
        elif self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Payment.objects.all()
        elif self.request.user.is_authenticated:
            return Payment.objects.filter(client=self.request.user)
        return Payment.objects.none()

    @action(detail=False, methods=["post"])
    def create_payment_intent(self, request):
        """
        Create a Stripe PaymentIntent for an appointment

        Expected payload:
        {
            "appointment_id": 1,
            "payment_type": "deposit",  # or "full_payment"
            "amount": "50.00"  # optional, will be calculated if not provided
        }
        """
        serializer = PaymentIntentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            appointment = Appointment.objects.get(
                id=serializer.validated_data["appointment_id"]
            )
            payment_type = serializer.validated_data["payment_type"]
            amount = serializer.validated_data["amount"]

            # Create PaymentIntent and Payment record
            payment_intent, payment = StripeService.create_payment_intent(
                appointment=appointment,
                payment_type=payment_type,
                amount=amount,
                client_email=appointment.client_email,
            )

            return Response(
                {
                    "client_secret": payment_intent.client_secret,
                    "payment_id": payment.id,
                    "amount": str(payment.amount),
                    "currency": payment.currency.upper(),
                },
                status=status.HTTP_201_CREATED,
            )

        except Appointment.DoesNotExist:
            return Response(
                {"error": "Appointment not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error creating PaymentIntent: {e}")
            return Response(
                {"error": "Failed to create payment intent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def confirm_payment(self, request):
        """
        Confirm a payment by checking its status with Stripe

        Expected payload:
        {
            "stripe_payment_intent_id": "pi_..."
        }
        """
        serializer = PaymentConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_intent_id = serializer.validated_data["stripe_payment_intent_id"]
            payment = Payment.objects.get(stripe_payment_intent_id=payment_intent_id)

            # Confirm payment with Stripe
            updated_payment = StripeService.confirm_payment(payment)

            response_serializer = PaymentSerializer(updated_payment)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Payment.DoesNotExist:
            return Response(
                {"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error confirming payment: {e}")
            return Response(
                {"error": "Failed to confirm payment"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def refund(self, request, pk=None):
        """
        Create a refund for a payment

        Expected payload:
        {
            "amount": "25.00",  # optional, defaults to full amount
            "reason": "requested_by_customer",
            "notes": "Customer requested refund"
        }
        """
        payment = self.get_object()

        if not payment.can_be_refunded:
            return Response(
                {"error": "Payment cannot be refunded"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get refund amount (default to full payment amount)
        refund_amount = request.data.get("amount")
        if refund_amount:
            try:
                refund_amount = Decimal(str(refund_amount))
            except:
                return Response(
                    {"error": "Invalid refund amount"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            refund_amount = payment.amount

        reason = request.data.get("reason", "requested_by_customer")
        notes = request.data.get("notes", "")

        try:
            stripe_refund, payment_refund = StripeService.create_refund(
                payment=payment, amount=refund_amount, reason=reason, notes=notes
            )

            serializer = PaymentRefundSerializer(payment_refund)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating refund: {e}")
            return Response(
                {"error": "Failed to create refund"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PaymentRefundViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing payment refunds"""

    queryset = PaymentRefund.objects.all()
    serializer_class = PaymentRefundSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "reason", "original_payment__appointment"]

    def get_queryset(self):
        if self.request.user.is_staff:
            return PaymentRefund.objects.all()
        elif self.request.user.is_authenticated:
            return PaymentRefund.objects.filter(
                original_payment__client=self.request.user
            )
        return PaymentRefund.objects.none()


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Handle Stripe webhook events
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        logger.error("Invalid payload in webhook")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid signature in webhook")
        return HttpResponse(status=400)

    try:
        # Handle the event
        StripeService.handle_webhook_event(event)

        return HttpResponse(status=200)

    except Exception as e:
        logger.error(f"Error handling webhook event: {e}")
        return HttpResponse(status=500)
