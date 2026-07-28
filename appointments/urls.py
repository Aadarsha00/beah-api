from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"appointments", views.AppointmentViewSet)

# Custom URL patterns for specific appointment actions
urlpatterns = [
    path("", include(router.urls)),
    # These are already handled by the viewset actions, but listed here for reference:
    # POST /appointments/{id}/cancel/ - Cancel appointment
    # POST /appointments/{id}/confirm/ - Confirm appointment (admin only)
    # POST /appointments/{id}/mark_completed/ - Mark as completed (admin only)
    # POST /appointments/{id}/mark_no_show/ - Mark as no show (admin only)
    # GET /appointments/{id}/payment_summary/ - Get payment summary
    # GET /appointments/{id}/check_payment_status/ - Check payment status
    # GET /appointments/my_upcoming/ - Get user's upcoming appointments
    # GET /appointments/payment_pending/ - Get appointments with pending payments
]
