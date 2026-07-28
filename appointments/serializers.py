from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import Appointment
from services.serializers import ServiceListSerializer

User = get_user_model()


class AppointmentSerializer(serializers.ModelSerializer):
    service_details = ServiceListSerializer(source="service", read_only=True)
    stylist_name = serializers.CharField(source="stylist.get_full_name", read_only=True)
    can_cancel = serializers.SerializerMethodField()
    is_past_due = serializers.SerializerMethodField()
    payment_summary = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "client_name",
            "client_email",
            "client_phone",
            "service",
            "service_details",
            "stylist",
            "stylist_name",
            "appointment_date",
            "appointment_time",
            "duration_minutes",
            "notes",
            "status",
            "payment_status",
            "deposit_amount",
            "total_amount",
            "can_cancel",
            "is_past_due",
            "payment_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "duration_minutes",
            "total_amount",
            "deposit_amount",
            "created_at",
            "updated_at",
        )

    def get_can_cancel(self, obj):
        return obj.can_cancel()

    def get_is_past_due(self, obj):
        return obj.is_past_due()

    def get_payment_summary(self, obj):
        return {
            "total_paid": obj.get_total_paid(),
            "remaining_balance": obj.get_remaining_balance(),
            "is_fully_paid": obj.is_fully_paid(),
            "has_deposit_paid": obj.has_deposit_paid(),
            "can_be_refunded": obj.can_be_refunded(),
        }

    def validate_appointment_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError("Cannot book appointments in the past.")
        return value

    def validate(self, data):
        # Check if the selected time slot is available
        appointment_date = data.get("appointment_date")
        appointment_time = data.get("appointment_time")
        stylist = data.get("stylist")

        if appointment_date and appointment_time and stylist:
            existing_appointment = Appointment.objects.filter(
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                stylist=stylist,
                status__in=["booked", "confirmed"],
            ).exclude(id=self.instance.id if self.instance else None)

            if existing_appointment.exists():
                raise serializers.ValidationError("This time slot is already booked.")

        return data

    def create(self, validated_data):
        # Associate with logged-in user if available
        if self.context["request"].user.is_authenticated:
            validated_data["client"] = self.context["request"].user
        return super().create(validated_data)


class AppointmentCreateSerializer(serializers.ModelSerializer):
    service_details = ServiceListSerializer(source="service", read_only=True)
    requires_deposit = serializers.SerializerMethodField()
    deposit_amount = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    total_amount = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )

    class Meta:
        model = Appointment
        fields = [
            "client_name",
            "client_email",
            "client_phone",
            "service",
            "service_details",
            "stylist",
            "appointment_date",
            "appointment_time",
            "notes",
            "requires_deposit",
            "deposit_amount",
            "total_amount",
        ]

    def get_requires_deposit(self, obj):
        return obj.service.requires_deposit if obj.service else False

    def validate_appointment_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError("Cannot book appointments in the past.")
        return value

    def validate(self, data):
        # Check if the selected time slot is available
        appointment_date = data.get("appointment_date")
        appointment_time = data.get("appointment_time")
        stylist = data.get("stylist")

        if appointment_date and appointment_time and stylist:
            existing_appointment = Appointment.objects.filter(
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                stylist=stylist,
                status__in=["booked", "confirmed"],
            )

            if existing_appointment.exists():
                raise serializers.ValidationError("This time slot is already booked.")

        return data

    def create(self, validated_data):
        # Associate with logged-in user if available
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["client"] = request.user
            # Use authenticated user's info if not provided
            if not validated_data.get("client_name"):
                validated_data["client_name"] = request.user.get_full_name()
            if not validated_data.get("client_email"):
                validated_data["client_email"] = request.user.email

        return super().create(validated_data)

    def to_representation(self, instance):
        # Use full serializer for response
        serializer = AppointmentSerializer(instance, context=self.context)
        return serializer.data


class AppointmentPaymentSummarySerializer(serializers.ModelSerializer):
    """Detailed payment summary serializer"""

    payment_details = serializers.SerializerMethodField()
    payment_history = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "client_name",
            "service",
            "appointment_date",
            "appointment_time",
            "status",
            "payment_status",
            "total_amount",
            "deposit_amount",
            "payment_details",
            "payment_history",
        ]

    def get_payment_details(self, obj):
        return {
            "total_amount": obj.total_amount,
            "deposit_amount": obj.deposit_amount,
            "total_paid": obj.get_total_paid(),
            "remaining_balance": obj.get_remaining_balance(),
            "is_fully_paid": obj.is_fully_paid(),
            "has_deposit_paid": obj.has_deposit_paid(),
            "can_be_refunded": obj.can_be_refunded(),
            "payment_status": obj.payment_status,
        }

    def get_payment_history(self, obj):
        from payments.models import Payment
        from payments.serializers import PaymentSerializer

        payments = Payment.objects.filter(appointment=obj).order_by("-created_at")
        return PaymentSerializer(payments, many=True).data


class AppointmentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating appointment details"""

    class Meta:
        model = Appointment
        fields = [
            "appointment_date",
            "appointment_time",
            "notes",
            "status",
        ]

    def validate_appointment_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError("Cannot reschedule to a past date.")
        return value

    def validate(self, data):
        # If rescheduling, check availability
        if "appointment_date" in data or "appointment_time" in data:
            appointment_date = data.get(
                "appointment_date", self.instance.appointment_date
            )
            appointment_time = data.get(
                "appointment_time", self.instance.appointment_time
            )
            stylist = self.instance.stylist

            existing_appointment = Appointment.objects.filter(
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                stylist=stylist,
                status__in=["booked", "confirmed"],
            ).exclude(id=self.instance.id)

            if existing_appointment.exists():
                raise serializers.ValidationError("This time slot is already booked.")

        return data
