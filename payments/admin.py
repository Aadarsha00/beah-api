# payments/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Payment, PaymentRefund


class PaymentRefundInline(admin.TabularInline):
    model = PaymentRefund
    fk_name = "original_payment"  # Specify which ForeignKey to use
    fields = ["amount", "reason", "status", "notes", "created_at"]
    readonly_fields = ["created_at", "stripe_refund_id"]
    extra = 0

    def has_add_permission(self, request, obj=None):
        # Only allow adding refunds if the payment is successful
        if obj and obj.status == "succeeded":
            return True
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "appointment_link",
        "client_name",
        "payment_type",
        "amount_display",
        "status",
        "payment_method",
        "created_at",
    ]
    list_filter = ["status", "payment_type", "payment_method", "created_at", "currency"]
    search_fields = [
        "client__email",
        "client__first_name",
        "client__last_name",
        "appointment__client_name",
        "stripe_payment_intent_id",
        "stripe_charge_id",
    ]
    readonly_fields = [
        "id",
        "stripe_payment_intent_id",
        "stripe_charge_id",
        "created_at",
        "updated_at",
        "processed_at",
        "stripe_link",
        "refund_summary",
    ]
    fieldsets = (
        (
            "Payment Information",
            {
                "fields": (
                    "id",
                    "appointment",
                    "client",
                    "payment_type",
                    "payment_method",
                    "amount",
                    "currency",
                )
            },
        ),
        (
            "Stripe Details",
            {
                "fields": (
                    "stripe_payment_intent_id",
                    "stripe_charge_id",
                    "stripe_link",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "failure_reason",
                    "description",
                )
            },
        ),
        (
            "Refund Information",
            {"fields": ("refund_summary",)},
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "processed_at",
                )
            },
        ),
    )

    inlines = [PaymentRefundInline]

    actions = [
        "mark_as_succeeded",
        "mark_as_failed",
    ]

    def appointment_link(self, obj):
        if obj.appointment:
            url = reverse(
                "admin:appointments_appointment_change", args=[obj.appointment.id]
            )
            return format_html('<a href="{}">{}</a>', url, obj.appointment)
        return "-"

    appointment_link.short_description = "Appointment"

    def client_name(self, obj):
        if obj.client:
            return obj.client.get_full_name()
        return obj.appointment.client_name if obj.appointment else "-"

    client_name.short_description = "Client"

    def amount_display(self, obj):
        color = (
            "green"
            if obj.status == "succeeded"
            else "red" if obj.status == "failed" else "orange"
        )
        return format_html(
            '<span style="color: {};">{} {}</span>', color, obj.currency, obj.amount
        )

    amount_display.short_description = "Amount"

    def stripe_link(self, obj):
        if obj.stripe_payment_intent_id:
            # Note: This assumes you're using Stripe test mode
            # For live mode, remove 'test/' from the URL
            url = f"https://dashboard.stripe.com/test/payments/{obj.stripe_payment_intent_id}"
            return format_html('<a href="{}" target="_blank">View in Stripe</a>', url)
        return "-"

    stripe_link.short_description = "Stripe Dashboard"

    def refund_summary(self, obj):
        refunds = obj.refunds.all()
        if not refunds:
            return "No refunds"

        html = "<div>"
        total_refunded = 0
        for refund in refunds:
            status_icon = (
                "✅"
                if refund.status == "succeeded"
                else "❌" if refund.status == "failed" else "🔄"
            )
            html += f"{status_icon} ${refund.amount} - {refund.reason} ({refund.status})<br>"
            if refund.status == "succeeded":
                total_refunded += refund.amount

        html += f"<br><strong>Total Refunded: ${total_refunded}</strong>"
        html += "</div>"

        return mark_safe(html)

    refund_summary.short_description = "Refund Summary"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("appointment", "client", "appointment__service")
            .prefetch_related("refunds")
        )

    # Admin actions
    def mark_as_succeeded(self, request, queryset):
        count = queryset.filter(status__in=["pending", "processing"]).update(
            status="succeeded"
        )
        self.message_user(
            request, f"Successfully marked {count} payments as succeeded."
        )

    mark_as_succeeded.short_description = "Mark selected payments as succeeded"

    def mark_as_failed(self, request, queryset):
        count = queryset.filter(status__in=["pending", "processing"]).update(
            status="failed"
        )
        self.message_user(request, f"Successfully marked {count} payments as failed.")

    mark_as_failed.short_description = "Mark selected payments as failed"


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "original_payment_link",
        "amount_display",
        "reason",
        "status",
        "created_at",
    ]
    list_filter = ["status", "reason", "created_at"]
    search_fields = [
        "original_payment__appointment__client_name",
        "original_payment__client__email",
        "stripe_refund_id",
        "notes",
    ]
    readonly_fields = [
        "id",
        "stripe_refund_id",
        "created_at",
        "updated_at",
        "processed_at",
        "stripe_refund_link",
        "original_payment_details",
    ]
    fieldsets = (
        (
            "Refund Information",
            {
                "fields": (
                    "id",
                    "original_payment",
                    "original_payment_details",
                    "refund_payment",
                    "amount",
                    "reason",
                    "notes",
                )
            },
        ),
        (
            "Stripe Details",
            {
                "fields": (
                    "stripe_refund_id",
                    "stripe_refund_link",
                )
            },
        ),
        ("Status", {"fields": ("status",)}),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "processed_at",
                )
            },
        ),
    )

    actions = [
        "mark_as_succeeded",
        "mark_as_failed",
    ]

    def original_payment_link(self, obj):
        url = reverse("admin:payments_payment_change", args=[obj.original_payment.id])
        return format_html('<a href="{}">{}</a>', url, str(obj.original_payment.id)[:8])

    original_payment_link.short_description = "Original Payment"

    def amount_display(self, obj):
        color = (
            "green"
            if obj.status == "succeeded"
            else "red" if obj.status == "failed" else "orange"
        )
        return format_html(
            '<span style="color: {};">{} {}</span>',
            color,
            obj.original_payment.currency,
            obj.amount,
        )

    amount_display.short_description = "Refund Amount"

    def stripe_refund_link(self, obj):
        if obj.stripe_refund_id:
            # Note: This assumes you're using Stripe test mode
            url = f"https://dashboard.stripe.com/test/refunds/{obj.stripe_refund_id}"
            return format_html('<a href="{}" target="_blank">View in Stripe</a>', url)
        return "-"

    stripe_refund_link.short_description = "Stripe Dashboard"

    def original_payment_details(self, obj):
        payment = obj.original_payment
        html = f"""
        <div style="background: #f8f9fa; padding: 10px; border-radius: 5px;">
            <strong>Original Payment Details:</strong><br>
            Amount: {payment.currency} {payment.amount}<br>
            Type: {payment.get_payment_type_display()}<br>
            Status: {payment.get_status_display()}<br>
            Method: {payment.get_payment_method_display()}<br>
            Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}<br>
        </div>
        """
        return mark_safe(html)

    original_payment_details.short_description = "Original Payment"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "original_payment",
                "original_payment__appointment",
                "original_payment__client",
                "refund_payment",
            )
        )

    # Admin actions
    def mark_as_succeeded(self, request, queryset):
        count = queryset.filter(status="pending").update(status="succeeded")
        self.message_user(request, f"Successfully marked {count} refunds as succeeded.")

    mark_as_succeeded.short_description = "Mark selected refunds as succeeded"

    def mark_as_failed(self, request, queryset):
        count = queryset.filter(status="pending").update(status="failed")
        self.message_user(request, f"Successfully marked {count} refunds as failed.")

    mark_as_failed.short_description = "Mark selected refunds as failed"
