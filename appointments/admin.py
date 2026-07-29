from django.contrib import admin

from .booking import ACTIVE_STATUSES
from .models import Appointment, SalonClosure


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "client_name",
        "service",
        "appointment_date",
        "appointment_time",
        "status",
        "total_amount",
    )
    list_filter = ("status", "appointment_date", "service__category", "stylist")
    search_fields = (
        "client_name",
        "client_email",
        "client_phone",
        "service__name",
    )
    readonly_fields = (
        "id",
        "duration_minutes",
        "total_amount",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "appointment_date"
    list_select_related = ("service", "stylist", "client")
    actions = (
        "confirm_appointments",
        "cancel_appointments",
    )

    @admin.action(description="Confirm selected appointments")
    def confirm_appointments(self, request, queryset):
        count = queryset.filter(status="booked").update(status="confirmed")
        self.message_user(request, f"Confirmed {count} appointment(s).")

    @admin.action(description="Cancel selected appointments")
    def cancel_appointments(self, request, queryset):
        count = queryset.filter(status__in=("booked", "confirmed")).update(
            status="cancelled"
        )
        self.message_user(request, f"Cancelled {count} appointment(s).")


@admin.register(SalonClosure)
class SalonClosureAdmin(admin.ModelAdmin):
    list_display = ("start_date", "end_date", "reason", "existing_bookings")
    search_fields = ("reason",)
    ordering = ("-start_date",)

    @admin.display(description="Bookings already in range")
    def existing_bookings(self, obj):
        """Closures do not cancel anything, so surface who still needs calling."""
        return Appointment.objects.filter(
            appointment_date__range=(obj.start_date, obj.end_date),
            status__in=ACTIVE_STATUSES,
        ).count()
