from django.urls import include, re_path
from .views import LogoutView

urlpatterns = [
    re_path(r"^auth/logout/$", LogoutView.as_view(), name="auth-logout"),
    re_path(r"^auth/", include("djoser.urls")),
    re_path(r"^auth/", include("djoser.urls.jwt")),
]
