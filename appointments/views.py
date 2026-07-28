from rest_framework import viewsets, permissions, status
from datetime import timedelta
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from .models import Appointment
from .serializers import (
    AppointmentSerializer,
    AppointmentCreateSerializer,
    AppointmentUpdateSerializer,
)
from .booking import (
    MAX_ADVANCE_DAYS,
    available_slots,
    booking_now,
    booking_timezone,
    booking_today,
)
from services.models import Service
from api.permissions import IsOwnerOrAdmin


class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "status": ["exact"],
        "appointment_date": ["exact", "gte", "lte"],
        "service": ["exact"],
    }

    def get_permissions(self):
        if self.action == "availability":
            permission_classes = [permissions.AllowAny]
        elif self.action in ["create", "list", "retrieve", "my_upcoming"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["confirm", "mark_completed", "mark_no_show", "today"]:
            permission_classes = [permissions.IsAdminUser]
        elif self.action == "destroy":
            permission_classes = [permissions.IsAdminUser]
        else:
            permission_classes = [IsOwnerOrAdmin]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "create":
            return AppointmentCreateSerializer
        if self.action in ["update", "partial_update"]:
            return AppointmentUpdateSerializer
        return AppointmentSerializer

    def get_queryset(self):
        queryset = Appointment.objects.select_related("service", "stylist", "client")
        if self.request.user.is_staff:
            return queryset
        elif self.request.user.is_authenticated:
            return queryset.filter(client=self.request.user)
        return Appointment.objects.none()

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            appointment = Appointment.objects.select_for_update().get(
                pk=self.get_object().pk
            )
            if appointment.status not in {"booked", "confirmed"}:
                return Response(
                    {"detail": "Only active appointments can be cancelled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if appointment.is_past_due():
                return Response(
                    {"detail": "Past appointments cannot be cancelled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            appointment.status = (
                "cancelled" if appointment.can_cancel() else "late_cancelled"
            )
            appointment.save(update_fields=["status", "updated_at"])

        return Response(
            {
                "message": "Appointment cancelled successfully.",
                "status": appointment.status,
            }
        )

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def confirm(self, request, pk=None):
        """Confirm an appointment (admin only)"""
        appointment = self.get_object()

        if appointment.status != "booked":
            return Response(
                {"detail": "Only booked appointments can be confirmed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if appointment.is_past_due():
            return Response(
                {"detail": "Past appointments cannot be confirmed."},
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

        if appointment.status != "confirmed" or not appointment.is_past_due():
            return Response(
                {"detail": "Only past, confirmed appointments can be completed."},
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

        if appointment.status not in {"booked", "confirmed"} or not appointment.is_past_due():
            return Response(
                {"detail": "Only past, active appointments can be marked as no-show."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        appointment.status = "no_show"
        appointment.save()

        return Response(
            {"message": "Appointment marked as no show."}, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"])
    def availability(self, request):
        date_value = request.query_params.get("date")
        service_id = request.query_params.get("service")
        if not date_value or not service_id:
            return Response(
                {"detail": "Both date and service query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            appointment_date = timezone.datetime.strptime(
                date_value, "%Y-%m-%d"
            ).date()
            service_pk = int(service_id)
        except ValueError:
            return Response(
                {"detail": "Use a valid service ID and a date in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = booking_today()
        if not today <= appointment_date <= today + timedelta(days=MAX_ADVANCE_DAYS):
            return Response(
                {
                    "detail": (
                        f"Choose a date from today through {MAX_ADVANCE_DAYS} days ahead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = Service.objects.get(pk=service_pk, is_active=True)
        except Service.DoesNotExist:
            return Response(
                {"detail": "Service not found or inactive."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "date": appointment_date,
                "service": service.pk,
                "duration_minutes": service.duration_minutes,
                "time_zone": str(booking_timezone()),
                "slots": available_slots(
                    appointment_date, service.duration_minutes
                ),
            }
        )

    @action(detail=False, methods=["get"])
    def my_upcoming(self, request):
        """Get user's upcoming appointments"""
        current_time = booking_now()
        today = current_time.date()
        local_time = current_time.time().replace(tzinfo=None)
        upcoming_appointments = Appointment.objects.filter(
            client=request.user,
            status__in=["booked", "confirmed"],
        ).filter(
            Q(appointment_date__gt=today)
            | Q(appointment_date=today, appointment_time__gt=local_time)
        ).order_by("appointment_date", "appointment_time")

        serializer = self.get_serializer(upcoming_appointments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def today(self, request):
        appointments = self.get_queryset().filter(
            appointment_date=booking_today()
        )
        page = self.paginate_queryset(appointments)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
