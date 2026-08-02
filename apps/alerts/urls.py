from django.urls import path

from . import views


app_name = "alerts"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/alerts/",
        views.alert_list,
        name="list",
    ),
    path(
        "organizations/<uuid:organization_id>/alerts/<uuid:alert_id>/",
        views.alert_detail,
        name="detail",
    ),
]
