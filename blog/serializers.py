from rest_framework import serializers
from .models import BlogPost


class BlogPostSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    featured_image_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "title",
            "slug",
            "author",
            "author_name",
            "content",
            "excerpt",
            "category",
            "featured_image",
            "featured_image_url",
            "meta_description",
            "keywords",
            "is_published",
            "is_featured",
            "views_count",
            "created_at",
            "updated_at",
            "published_at",
        ]
        read_only_fields = (
            "id",
            "slug",
            "author",
            "views_count",
            "created_at",
            "updated_at",
            "published_at",
        )

    def get_featured_image_url(self, obj):
        if obj.featured_image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.featured_image.url)
            return obj.featured_image.url
        return None

    def validate_featured_image(self, value):
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Images must be 5 MB or smaller.")
        return value


class BlogPostListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing blog posts"""

    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    featured_image_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "title",
            "slug",
            "author_name",
            "excerpt",
            "category",
            "featured_image_url",
            "is_featured",
            "published_at",
        ]

    def get_featured_image_url(self, obj):
        if obj.featured_image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.featured_image.url)
            return obj.featured_image.url
        return None
