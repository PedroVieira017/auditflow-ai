from django.urls import path

from .views import health_check, organization_dashboard


app_name = "core"

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path(
        "organizations/<uuid:organization_id>/dashboard/",
        organization_dashboard,
        name="dashboard",
    ),
]
