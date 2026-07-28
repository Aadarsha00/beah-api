from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Promotion, ContactMessage, AdminNote


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "discount_display",
        "start_date",
        "end_date",
        "is_active",
        "status_display",
        "created_at",
    ]
    list_filter = ["is_active", "start_date", "end_date", "created_at"]
    search_fields = ["title", "description", "terms_conditions"]
    date_hierarchy = "start_date"
    readonly_fields = ["created_at", "updated_at", "status_display"]
    filter_horizontal = ["applicable_services"]

    fieldsets = (
        ("Basic Information", {"fields": ("title", "description", "is_active")}),
        (
            "Discount Details",
            {
                "fields": ("discount_percentage", "discount_amount"),
                "description": "Provide either percentage or amount discount",
            },
        ),
        ("Date Range", {"fields": ("start_date", "end_date")}),
        ("Services", {"fields": ("applicable_services",), "classes": ("collapse",)}),
        (
            "Terms & Conditions",
            {"fields": ("terms_conditions",), "classes": ("collapse",)},
        ),
        (
            "Status & Timestamps",
            {
                "fields": ("status_display", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = ["activate_promotions", "deactivate_promotions"]

    def discount_display(self, obj):
        if obj.discount_percentage:
            return f"{obj.discount_percentage}%"
        elif obj.discount_amount:
            return f"${obj.discount_amount}"
        return "No discount"

    discount_display.short_description = "Discount"

    def status_display(self, obj):
        today = timezone.now().date()
        if obj.is_currently_active():
            return format_html(
                '<span style="color: green; font-weight: bold;">● Active</span>'
            )
        elif obj.is_active and obj.start_date and obj.start_date > today:
            return format_html(
                '<span style="color: orange; font-weight: bold;">● Upcoming</span>'
            )
        elif obj.end_date and obj.end_date < today:
            return format_html(
                '<span style="color: red; font-weight: bold;">● Expired</span>'
            )
        else:
            return format_html(
                '<span style="color: gray; font-weight: bold;">● Inactive</span>'
            )

    status_display.short_description = "Status"

    def activate_promotions(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} promotion(s) have been activated.")

    activate_promotions.short_description = "Activate selected promotions"

    def deactivate_promotions(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} promotion(s) have been deactivated.")

    deactivate_promotions.short_description = "Deactivate selected promotions"


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "email",
        "subject",
        "status_display",
        "is_read",
        "is_responded",
        "created_at",
    ]
    list_filter = ["is_read", "is_responded", "created_at"]
    search_fields = ["name", "email", "subject", "message"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "status_display"]

    fieldsets = (
        ("Contact Information", {"fields": ("name", "email", "phone")}),
        ("Message Details", {"fields": ("subject", "message")}),
        ("Status", {"fields": ("status_display", "is_read", "is_responded")}),
        ("Admin Section", {"fields": ("admin_notes",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    actions = ["mark_as_read", "mark_as_responded", "mark_as_unread"]

    def status_display(self, obj):
        status = obj.status
        if status == "Responded":
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Responded</span>'
            )
        elif status == "Read":
            return format_html(
                '<span style="color: orange; font-weight: bold;">👁 Read</span>'
            )
        else:
            return format_html(
                '<span style="color: red; font-weight: bold;">● Unread</span>'
            )

    status_display.short_description = "Status"

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} message(s) marked as read.")

    mark_as_read.short_description = "Mark selected messages as read"

    def mark_as_responded(self, request, queryset):
        updated = queryset.update(is_read=True, is_responded=True)
        self.message_user(request, f"{updated} message(s) marked as responded.")

    mark_as_responded.short_description = "Mark selected messages as responded"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False, is_responded=False)
        self.message_user(request, f"{updated} message(s) marked as unread.")

    mark_as_unread.short_description = "Mark selected messages as unread"


@admin.register(AdminNote)
class AdminNoteAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "created_by",
        "importance_display",
        "created_at",
        "updated_at",
    ]
    list_filter = ["is_important", "created_by", "created_at"]
    search_fields = ["title", "content"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Note Information", {"fields": ("title", "content", "is_important")}),
        (
            "Meta Information",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = ["mark_as_important", "mark_as_normal"]

    def importance_display(self, obj):
        if obj.is_important:
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠ Important</span>'
            )
        return format_html('<span style="color: gray;">📝 Normal</span>')

    importance_display.short_description = "Priority"

    def save_model(self, request, obj, form, change):
        if not change:  # If creating a new object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def mark_as_important(self, request, queryset):
        updated = queryset.update(is_important=True)
        self.message_user(request, f"{updated} note(s) marked as important.")

    mark_as_important.short_description = "Mark selected notes as important"

    def mark_as_normal(self, request, queryset):
        updated = queryset.update(is_important=False)
        self.message_user(request, f"{updated} note(s) marked as normal.")

    mark_as_normal.short_description = "Mark selected notes as normal"


# Optional: Custom admin site configuration
admin.site.site_header = "Beautiful Administration"
admin.site.site_title = "Beautiful Admin"
admin.site.index_title = "Welcome to Beautiful Administration"
