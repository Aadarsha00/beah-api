from rest_framework import serializers
from .models import Appointment
from .booking import (
    ensure_slot_available,
    reserve_appointment,
    reschedule_appointment,
)
from services.serializers import ServiceListSerializer


class AppointmentSerializer(serializers.ModelSerializer):
    service_details = ServiceListSerializer(source="service", read_only=True)
    stylist_name = serializers.CharField(source="stylist.get_full_name", read_only=True)
    can_cancel = serializers.SerializerMethodField()
    is_past_due = serializers.SerializerMethodField()

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
            "total_amount",
            "can_cancel",
            "is_past_due",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_can_cancel(self, obj):
        return obj.can_cancel()

    def get_is_past_due(self, obj):
        return obj.is_past_due()


class AppointmentCreateSerializer(serializers.ModelSerializer):
    service_details = ServiceListSerializer(source="service", read_only=True)
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
            "appointment_date",
            "appointment_time",
            "notes",
            "total_amount",
        ]

    def validate(self, data):
        service = data["service"]
        if not service.is_active:
            raise serializers.ValidationError(
                {"service": "This service is no longer available."}
            )
        ensure_slot_available(
            data["appointment_date"],
            data["appointment_time"],
            service.duration_minutes,
        )
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["client"] = request.user
        return reserve_appointment(validated_data)

    def to_representation(self, instance):
        # Use full serializer for response
        serializer = AppointmentSerializer(instance, context=self.context)
        return serializer.data

class AppointmentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = ["appointment_date", "appointment_time", "notes"]

    def validate(self, data):
        if "appointment_date" in data or "appointment_time" in data:
            if self.instance.status not in {"booked", "confirmed"}:
                raise serializers.ValidationError(
                    "Only active appointments can be rescheduled."
                )
            appointment_date = data.get(
                "appointment_date", self.instance.appointment_date
            )
            appointment_time = data.get(
                "appointment_time", self.instance.appointment_time
            )
            ensure_slot_available(
                appointment_date,
                appointment_time,
                self.instance.duration_minutes,
                exclude_id=self.instance.pk,
            )
        return data

    def update(self, instance, validated_data):
        if "appointment_date" in validated_data or "appointment_time" in validated_data:
            return reschedule_appointment(instance, validated_data)
        instance.notes = validated_data.get("notes", instance.notes)
        instance.save(update_fields=["notes", "updated_at"])
        return instance
