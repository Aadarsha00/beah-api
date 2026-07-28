# payments/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"payments", views.PaymentViewSet)
router.register(r"refunds", views.PaymentRefundViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
]
