from rest_framework import filters, viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import GalleryImage
from .serializers import GalleryImageSerializer, GalleryImageListSerializer


class GalleryImageViewSet(viewsets.ModelViewSet):
    queryset = GalleryImage.objects.all()
    serializer_class = GalleryImageSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category", "is_featured", "is_active"]
    search_fields = ["caption", "category"]

    def get_permissions(self):
        """Public read access, admin only for write operations"""
        if self.action in ["list", "retrieve", "featured", "by_category"]:
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list" and not self.request.user.is_staff:
            return GalleryImageListSerializer
        return GalleryImageSerializer

    def get_queryset(self):
        if (
            self.action in ["list", "retrieve", "featured", "by_category"]
            and not self.request.user.is_staff
        ):
            return GalleryImage.objects.filter(is_active=True)
        return GalleryImage.objects.all()

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """Get featured gallery images"""
        featured_images = GalleryImage.objects.filter(is_featured=True, is_active=True)
        serializer = GalleryImageListSerializer(
            featured_images, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        """Get gallery images grouped by category"""
        categories = GalleryImage.CATEGORY_CHOICES
        result = {}

        for category_code, category_name in categories:
            images = GalleryImage.objects.filter(category=category_code, is_active=True)
            result[category_code] = {
                "name": category_name,
                "images": GalleryImageListSerializer(
                    images, many=True, context={"request": request}
                ).data,
            }

        return Response(result)
