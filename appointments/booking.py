from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import Appointment, BookingDayLock

OPENING_TIME = time(hour=9)
CLOSING_TIME = time(hour=18)
SUNDAY_OPENING_TIME = time(hour=10)
SUNDAY_CLOSING_TIME = time(hour=16)
SLOT_INTERVAL_MINUTES = 30
MAX_ADVANCE_DAYS = 90
ACTIVE_STATUSES = ("booked", "confirmed")


def _as_datetime(appointment_date, appointment_time):
    return datetime.combine(appointment_date, appointment_time)


def business_hours(appointment_date):
    if appointment_date.weekday() == 6:
        return SUNDAY_OPENING_TIME, SUNDAY_CLOSING_TIME
    return OPENING_TIME, CLOSING_TIME


def validate_slot(appointment_date, appointment_time, duration_minutes):
    today = timezone.localdate()
    if appointment_date < today:
        raise serializers.ValidationError(
            {"appointment_date": "Choose today or a future date."}
        )
    if appointment_date > today + timedelta(days=MAX_ADVANCE_DAYS):
        raise serializers.ValidationError(
            {
                "appointment_date": (
                    f"Appointments can be booked up to {MAX_ADVANCE_DAYS} days ahead."
                )
            }
        )

    opening_time, closing_time = business_hours(appointment_date)
    start = _as_datetime(appointment_date, appointment_time)
    end = start + timedelta(minutes=duration_minutes)
    opening = _as_datetime(appointment_date, opening_time)
    closing = _as_datetime(appointment_date, closing_time)

    if appointment_time.second or appointment_time.microsecond:
        raise serializers.ValidationError(
            {"appointment_time": "Choose a time on a 30-minute boundary."}
        )
    minutes_from_open = int((start - opening).total_seconds() // 60)
    if minutes_from_open < 0 or minutes_from_open % SLOT_INTERVAL_MINUTES:
        raise serializers.ValidationError(
            {"appointment_time": "Choose a time on a 30-minute boundary."}
        )
    if end > closing:
        raise serializers.ValidationError(
            {
                "appointment_time": (
                    f"The service must finish by {closing.strftime('%I:%M %p').lstrip('0')}."
                )
            }
        )

    aware_start = timezone.make_aware(start, timezone.get_current_timezone())
    if aware_start <= timezone.now():
        raise serializers.ValidationError(
            {"appointment_time": "Choose a future appointment time."}
        )


def slot_is_available(
    appointment_date, appointment_time, duration_minutes, exclude_id=None
):
    proposed_start = _as_datetime(appointment_date, appointment_time)
    proposed_end = proposed_start + timedelta(minutes=duration_minutes)
    appointments = Appointment.objects.filter(
        appointment_date=appointment_date,
        status__in=ACTIVE_STATUSES,
    )
    if exclude_id:
        appointments = appointments.exclude(pk=exclude_id)

    for appointment in appointments.only(
        "appointment_time", "duration_minutes"
    ):
        existing_start = _as_datetime(
            appointment_date, appointment.appointment_time
        )
        existing_end = existing_start + timedelta(
            minutes=appointment.duration_minutes
        )
        if existing_start < proposed_end and existing_end > proposed_start:
            return False
    return True


def ensure_slot_available(
    appointment_date, appointment_time, duration_minutes, exclude_id=None
):
    validate_slot(appointment_date, appointment_time, duration_minutes)
    if not slot_is_available(
        appointment_date, appointment_time, duration_minutes, exclude_id
    ):
        raise serializers.ValidationError(
            {"appointment_time": "This time overlaps an existing booking."}
        )


def lock_booking_days(*dates):
    """Lock dates in a stable order to prevent overlapping concurrent bookings."""
    for booking_date in sorted(set(dates)):
        BookingDayLock.objects.get_or_create(date=booking_date)
        BookingDayLock.objects.select_for_update().get(date=booking_date)


@transaction.atomic
def reserve_appointment(validated_data):
    appointment_date = validated_data["appointment_date"]
    service = validated_data["service"]
    lock_booking_days(appointment_date)
    ensure_slot_available(
        appointment_date,
        validated_data["appointment_time"],
        service.duration_minutes,
    )
    return Appointment.objects.create(
        duration_minutes=service.duration_minutes,
        total_amount=service.price,
        **validated_data,
    )


@transaction.atomic
def reschedule_appointment(instance, validated_data):
    new_date = validated_data.get("appointment_date", instance.appointment_date)
    new_time = validated_data.get("appointment_time", instance.appointment_time)
    lock_booking_days(instance.appointment_date, new_date)
    ensure_slot_available(
        new_date,
        new_time,
        instance.duration_minutes,
        exclude_id=instance.pk,
    )
    for field, value in validated_data.items():
        setattr(instance, field, value)
    instance.save()
    return instance


def available_slots(appointment_date, duration_minutes):
    slots = []
    opening_time, closing_time = business_hours(appointment_date)
    cursor = _as_datetime(appointment_date, opening_time)
    closing = _as_datetime(appointment_date, closing_time)

    while cursor + timedelta(minutes=duration_minutes) <= closing:
        slot_time = cursor.time()
        try:
            validate_slot(appointment_date, slot_time, duration_minutes)
        except serializers.ValidationError:
            pass
        else:
            if slot_is_available(appointment_date, slot_time, duration_minutes):
                slots.append(
                    {
                        "value": slot_time.strftime("%H:%M:%S"),
                        "label": cursor.strftime("%I:%M %p").lstrip("0"),
                    }
                )
        cursor += timedelta(minutes=SLOT_INTERVAL_MINUTES)
    return slots
