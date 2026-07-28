from rest_framework import serializers
from .models import Service


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "description",
            "price",
            "category",
            "duration_minutes",
            "is_active",
            "requires_deposit",
            "deposit_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")


class ServiceListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing services"""

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "price",
            "category",
            "duration_minutes",
            "requires_deposit",
            "deposit_amount",
        ]
