from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AppointmentViewSet, SalonClosureViewSet

router = DefaultRouter()
router.register("appointments", AppointmentViewSet)
router.register("salon-closures", SalonClosureViewSet)

urlpatterns = [path("", include(router.urls))]
