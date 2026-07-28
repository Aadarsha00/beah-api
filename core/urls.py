from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("appointments.urls")),
    path("api/", include("blog.urls")),
    path("api/", include("gallery.urls")),
    path("api/", include("payments.urls")),
    path("api/", include("services.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)