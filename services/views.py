from django.db.models.deletion import ProtectedError
from rest_framework import filters, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Service
from .serializers import ServiceSerializer, ServiceListSerializer


class ServiceViewSet(viewsets.ModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category", "is_active"]
    search_fields = ["name", "description"]

    def get_permissions(self):
        """Public read access, admin only for write operations"""
        if self.action in ["list", "retrieve", "by_category"]:
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list" and not self.request.user.is_staff:
            return ServiceListSerializer
        return ServiceSerializer

    def get_queryset(self):
        if self.action in ["list", "retrieve"] and not self.request.user.is_staff:
            return Service.objects.filter(is_active=True)
        return Service.objects.all()

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        """Get services grouped by category"""
        categories = Service.SERVICE_CATEGORIES
        result = {}

        for category_code, category_name in categories:
            services = Service.objects.filter(category=category_code, is_active=True)
            result[category_code] = {
                "name": category_name,
                "services": ServiceListSerializer(services, many=True).data,
            }

        return Response(result)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "This service is used by existing appointments. "
                        "Deactivate it instead of deleting it."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
