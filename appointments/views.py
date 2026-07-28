from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from .models import Appointment
from .serializers import (
    AppointmentSerializer,
    AppointmentCreateSerializer,
    AppointmentPaymentSummarySerializer,
)
from api.permissions import IsOwnerOrAdmin


class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "status",
        "payment_status",
        "appointment_date",
        "service",
        "stylist",
    ]

    def get_permissions(self):
        if self.action == "create":
            permission_classes = [permissions.AllowAny]
        elif self.action in ["list", "retrieve", "payment_summary"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["confirm", "mark_completed", "mark_no_show"]:
            permission_classes = [permissions.IsAdminUser]
        else:
            permission_classes = [IsOwnerOrAdmin]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "create":
            return AppointmentCreateSerializer
        elif self.action == "payment_summary":
            return AppointmentPaymentSummarySerializer
        return AppointmentSerializer

    def get_queryset(self):
        if self.request.user.is_staff:
            return Appointment.objects.all()
        elif self.request.user.is_authenticated:
            return Appointment.objects.filter(client=self.request.user)
        return Appointment.objects.none()

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel an appointment with appropriate status based on timing"""
        appointment = self.get_object()

        with transaction.atomic():
            if not appointment.can_cancel():
                appointment.status = "late_cancelled"
                appointment.save()

                # Handle refund logic for late cancellation
                if appointment.can_be_refunded():
                    # You might want to apply a cancellation fee here
                    # and process partial refund
                    pass

                return Response(
                    {
                        "message": "Appointment cancelled with late cancellation policy applied.",
                        "status": "late_cancelled",
                        "refund_eligible": appointment.can_be_refunded(),
                    },
                    status=status.HTTP_200_OK,
                )

            appointment.status = "cancelled"
            appointment.save()

            return Response(
                {
                    "message": "Appointment cancelled successfully.",
                    "status": "cancelled",
                    "refund_eligible": appointment.can_be_refunded(),
                },
                status=status.HTTP_200_OK,
            )

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def confirm(self, request, pk=None):
        """Confirm an appointment (admin only)"""
        appointment = self.get_object()

        # Check if deposit is required and paid
        if appointment.service.requires_deposit and not appointment.has_deposit_paid():
            return Response(
                {"error": "Cannot confirm appointment: deposit not paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = "confirmed"
        appointment.save()

        return Response(
            {"message": "Appointment confirmed."}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def mark_completed(self, request, pk=None):
        """Mark appointment as completed"""
        appointment = self.get_object()

        if appointment.status not in ["confirmed", "booked"]:
            return Response(
                {
                    "error": "Only confirmed or booked appointments can be marked as completed."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = "completed"
        appointment.save()

        return Response(
            {"message": "Appointment marked as completed."}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def mark_no_show(self, request, pk=None):
        """Mark appointment as no show"""
        appointment = self.get_object()

        if not appointment.is_past_due():
            return Response(
                {"error": "Cannot mark as no show: appointment time has not passed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = "no_show"
        appointment.save()

        return Response(
            {"message": "Appointment marked as no show."}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["get"])
    def payment_summary(self, request, pk=None):
        """Get payment summary for an appointment"""
        appointment = self.get_object()

        return Response(appointment.payment_summary, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def check_payment_status(self, request, pk=None):
        """Check if appointment payments are up to date"""
        appointment = self.get_object()

        payment_info = {
            "appointment_id": appointment.id,
            "total_amount": appointment.total_amount,
            "deposit_required": appointment.deposit_amount > 0,
            "deposit_amount": appointment.deposit_amount,
            "deposit_paid": appointment.has_deposit_paid(),
            "total_paid": appointment.get_total_paid(),
            "remaining_balance": appointment.get_remaining_balance(),
            "is_fully_paid": appointment.is_fully_paid(),
            "payment_status": appointment.payment_status,
            "can_be_refunded": appointment.can_be_refunded(),
        }

        return Response(payment_info, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def my_upcoming(self, request):
        """Get user's upcoming appointments"""
        if not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        upcoming_appointments = Appointment.objects.filter(
            client=request.user,
            appointment_date__gte=timezone.now().date(),
            status__in=["booked", "confirmed"],
        ).order_by("appointment_date", "appointment_time")

        serializer = self.get_serializer(upcoming_appointments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def payment_pending(self, request):
        """Get appointments with pending payments"""
        if not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        pending_appointments = Appointment.objects.filter(
            client=request.user,
            payment_status__in=["pending", "deposit_paid"],
            status__in=["booked", "confirmed"],
        ).order_by("appointment_date", "appointment_time")

        serializer = self.get_serializer(pending_appointments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
