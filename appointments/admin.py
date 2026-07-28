from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client_name",
        "service_name",
        "stylist_name",
        "appointment_datetime",
        "status",
        "payment_status",
        "payment_info",
        "created_at",
    ]

    list_filter = [
        "status",
        "payment_status",
        "appointment_date",
        "service__category",
        "stylist",
        "created_at",
    ]

    search_fields = [
        "client_name",
        "client_email",
        "client_phone",
        "service__name",
        "stylist__first_name",
        "stylist__last_name",
    ]

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "payment_summary_display",
        "can_cancel",
        "is_past_due",
    ]

    fieldsets = (
        (
            "Client Information",
            {
                "fields": (
                    "client",
                    "client_name",
                    "client_email",
                    "client_phone",
                )
            },
        ),
        (
            "Appointment Details",
            {
                "fields": (
                    "service",
                    "stylist",
                    "appointment_date",
                    "appointment_time",
                    "duration_minutes",
                    "notes",
                )
            },
        ),
        (
            "Status & Payment",
            {
                "fields": (
                    "status",
                    "payment_status",
                    "total_amount",
                    "deposit_amount",
                    "payment_summary_display",
                )
            },
        ),
        (
            "System Info",
            {
                "fields": (
                    "id",
                    "can_cancel",
                    "is_past_due",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    actions = [
        "confirm_appointments",
        "mark_completed",
        "mark_no_show",
        "cancel_appointments",
    ]

    def service_name(self, obj):
        return obj.service.name

    service_name.short_description = "Service"
    service_name.admin_order_field = "service__name"

    def stylist_name(self, obj):
        if obj.stylist:
            return obj.stylist.get_full_name()
        return "No stylist assigned"

    stylist_name.short_description = "Stylist"
    stylist_name.admin_order_field = "stylist__first_name"

    def appointment_datetime(self, obj):
        return f"{obj.appointment_date} at {obj.appointment_time}"

    appointment_datetime.short_description = "Date & Time"
    appointment_datetime.admin_order_field = "appointment_date"

    def payment_info(self, obj):
        total_paid = obj.get_total_paid()
        remaining = obj.get_remaining_balance()

        if obj.is_fully_paid():
            color = "green"
            text = f"Paid: ${total_paid}"
        elif total_paid > 0:
            color = "orange"
            text = f"Partial: ${total_paid} / ${obj.total_amount}"
        else:
            color = "red"
            text = f"Unpaid: ${obj.total_amount}"

        return format_html('<span style="color: {};">{}</span>', color, text)

    payment_info.short_description = "Payment Info"

    def payment_summary_display(self, obj):
        summary = obj.payment_summary

        html = f"""
        <div style="background: #f8f9fa; padding: 10px; border-radius: 5px;">
            <strong>Payment Summary:</strong><br>
            Total Amount: ${summary['total_amount']}<br>
            Deposit Required: ${summary['deposit_amount']}<br>
            Total Paid: ${summary['total_paid']}<br>
            Remaining Balance: ${summary['remaining_balance']}<br>
            
            <br><strong>Status:</strong><br>
            Deposit Paid: {"✅" if summary['has_deposit_paid'] else "❌"}<br>
            Fully Paid: {"✅" if summary['is_fully_paid'] else "❌"}<br>
            Payment Status: {summary['payment_status']}<br>
        </div>
        """

        if summary["payments"]:
            html += "<br><strong>Payment History:</strong><br>"
            for payment in summary["payments"][:5]:  # Show last 5 payments
                status_icon = "✅" if payment.status == "succeeded" else "❌"
                html += f"{status_icon} ${payment.amount} - {payment.payment_type} - {payment.created_at.strftime('%Y-%m-%d %H:%M')}<br>"

        return mark_safe(html)

    payment_summary_display.short_description = "Payment Summary"

    def can_cancel(self, obj):
        return "✅" if obj.can_cancel() else "❌"

    can_cancel.short_description = "Can Cancel"
    can_cancel.boolean = True

    def is_past_due(self, obj):
        return "✅" if obj.is_past_due() else "❌"

    is_past_due.short_description = "Past Due"
    is_past_due.boolean = True

    # Admin actions
    def confirm_appointments(self, request, queryset):
        count = 0
        for appointment in queryset:
            if appointment.status in ["booked"] and appointment.has_deposit_paid():
                appointment.status = "confirmed"
                appointment.save()
                count += 1

        self.message_user(request, f"Successfully confirmed {count} appointments.")

    confirm_appointments.short_description = "Confirm selected appointments"

    def mark_completed(self, request, queryset):
        count = queryset.filter(status__in=["confirmed", "booked"]).update(
            status="completed"
        )

        self.message_user(
            request, f"Successfully marked {count} appointments as completed."
        )

    mark_completed.short_description = "Mark selected appointments as completed"

    def mark_no_show(self, request, queryset):
        count = 0
        for appointment in queryset:
            if appointment.is_past_due():
                appointment.status = "no_show"
                appointment.save()
                count += 1

        self.message_user(
            request, f"Successfully marked {count} appointments as no show."
        )

    mark_no_show.short_description = "Mark selected appointments as no show"

    def cancel_appointments(self, request, queryset):
        count = queryset.filter(status__in=["booked", "confirmed"]).update(
            status="cancelled"
        )

        self.message_user(request, f"Successfully cancelled {count} appointments.")

    cancel_appointments.short_description = "Cancel selected appointments"

    # Customize the changelist view
    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("service", "stylist", "client")
            .prefetch_related("payment_set")
        )
