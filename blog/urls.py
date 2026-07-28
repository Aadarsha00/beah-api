from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"blog", views.BlogPostViewSet)

app_name = "blog"

urlpatterns = [
    path("", include(router.urls)),
]
