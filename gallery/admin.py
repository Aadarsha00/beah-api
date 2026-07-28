from django.contrib import admin
from .models import GalleryImage


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = (
        "caption",
        "category",
        "is_featured",
        "is_active",
        "order",
        "created_at",
    )
    list_filter = ("category", "is_featured", "is_active")
    search_fields = ("caption",)
    list_editable = ("is_featured", "is_active", "order")
    ordering = ("-is_featured", "order", "-created_at")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Image Details", {"fields": ("image", "caption", "category")}),
        ("Display Options", {"fields": ("is_featured", "is_active", "order")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
