from django.contrib import admin
from .models import Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "price",
        "duration_minutes",
        "is_active",
        "requires_deposit",
    )
    list_filter = ("category", "is_active", "requires_deposit")
    search_fields = ("name", "description")
    list_editable = ("price", "is_active", "requires_deposit")
    ordering = ("category", "name")
