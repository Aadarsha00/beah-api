from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"promotions", views.PromotionViewSet)
router.register(r"contact-messages", views.ContactMessageViewSet)
router.register(r"admin-notes", views.AdminNoteViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path(
        "promotions/active/",
        views.PromotionViewSet.as_view({"get": "active"}),
        name="active-promotions",
    ),
    path(
        "contact-messages/unread/",
        views.ContactMessageViewSet.as_view({"get": "unread"}),
        name="unread-messages",
    ),
]
