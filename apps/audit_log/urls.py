from django.urls import path

from . import views


app_name = "audit_log"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/audit-log/",
        views.audit_event_list,
        name="list",
    ),
]
