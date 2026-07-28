from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Promotion, ContactMessage, AdminNote

User = get_user_model()


class PromotionSerializer(serializers.ModelSerializer):
    is_currently_active = serializers.ReadOnlyField()
    applicable_services_names = serializers.SerializerMethodField()

    class Meta:
        model = Promotion
        fields = [
            "id",
            "title",
            "description",
            "discount_percentage",
            "discount_amount",
            "start_date",
            "end_date",
            "is_active",
            "applicable_services",
            "applicable_services_names",
            "terms_conditions",
            "created_at",
            "updated_at",
            "is_currently_active",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_applicable_services_names(self, obj):
        return [service.name for service in obj.applicable_services.all()]

    def validate(self, data):
        if data.get("start_date") and data.get("end_date"):
            if data["start_date"] > data["end_date"]:
                raise serializers.ValidationError(
                    "Start date cannot be later than end date."
                )

        if not data.get("discount_percentage") and not data.get("discount_amount"):
            raise serializers.ValidationError(
                "Either discount percentage or discount amount must be provided."
            )

        return data


class PromotionCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = [
            "title",
            "description",
            "discount_percentage",
            "discount_amount",
            "start_date",
            "end_date",
            "is_active",
            "applicable_services",
            "terms_conditions",
        ]

    def validate(self, data):
        if data.get("start_date") and data.get("end_date"):
            if data["start_date"] > data["end_date"]:
                raise serializers.ValidationError(
                    "Start date cannot be later than end date."
                )

        if not data.get("discount_percentage") and not data.get("discount_amount"):
            raise serializers.ValidationError(
                "Either discount percentage or discount amount must be provided."
            )

        return data


class ContactMessageSerializer(serializers.ModelSerializer):
    status = serializers.ReadOnlyField()

    class Meta:
        model = ContactMessage
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "subject",
            "message",
            "is_read",
            "is_responded",
            "admin_notes",
            "status",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class ContactMessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]

    def validate_email(self, value):
        if not value:
            raise serializers.ValidationError("Email is required.")
        return value


class ContactMessageUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["is_read", "is_responded", "admin_notes"]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]


class AdminNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = AdminNote
        fields = [
            "id",
            "title",
            "content",
            "created_by",
            "created_by_name",
            "is_important",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by"]

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.email


class AdminNoteCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminNote
        fields = ["title", "content", "is_important"]

    def validate_title(self, value):
        if len(value.strip()) < 3:
            raise serializers.ValidationError(
                "Title must be at least 3 characters long."
            )
        return value.strip()

    def validate_content(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError(
                "Content must be at least 10 characters long."
            )
        return value.strip()
