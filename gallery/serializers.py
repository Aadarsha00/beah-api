from rest_framework import serializers
from .models import GalleryImage


class GalleryImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GalleryImage
        fields = [
            "id",
            "image",
            "image_url",
            "caption",
            "category",
            "is_featured",
            "is_active",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class GalleryImageListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing gallery images"""

    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GalleryImage
        fields = ["id", "image_url", "caption", "category", "is_featured"]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
