"""Root URL configuration for AuditFlow AI."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
]

