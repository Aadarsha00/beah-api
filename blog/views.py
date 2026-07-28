from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F
from .models import BlogPost
from .serializers import BlogPostSerializer, BlogPostListSerializer


class BlogPostViewSet(viewsets.ModelViewSet):
    queryset = BlogPost.objects.all()
    serializer_class = BlogPostSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["category", "is_published", "is_featured"]
    lookup_field = "slug"

    def get_permissions(self):
        """Public read access, admin only for write operations"""
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list":
            return BlogPostListSerializer
        return BlogPostSerializer

    def get_queryset(self):
        if self.action in ["list", "retrieve"] and not self.request.user.is_staff:
            return BlogPost.objects.filter(is_published=True)
        return BlogPost.objects.all()

    def retrieve(self, request, *args, **kwargs):
        """Override retrieve to increment view count"""
        instance = self.get_object()
        if instance.is_published:
            # Increment view count
            BlogPost.objects.filter(pk=instance.pk).update(
                views_count=F("views_count") + 1
            )
            instance.refresh_from_db()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """Get featured blog posts"""
        featured_posts = BlogPost.objects.filter(is_featured=True, is_published=True)
        serializer = BlogPostListSerializer(
            featured_posts, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        """Get blog posts grouped by category"""
        categories = BlogPost.CATEGORY_CHOICES
        result = {}

        for category_code, category_name in categories:
            posts = BlogPost.objects.filter(category=category_code, is_published=True)[
                :5
            ]
            result[category_code] = {
                "name": category_name,
                "posts": BlogPostListSerializer(
                    posts, many=True, context={"request": request}
                ).data,
            }

        return Response(result)

    @action(detail=False, methods=["get"])
    def recent(self, request):
        """Get recent blog posts"""
        recent_posts = BlogPost.objects.filter(is_published=True)[:5]
        serializer = BlogPostListSerializer(
            recent_posts, many=True, context={"request": request}
        )
        return Response(serializer.data)
