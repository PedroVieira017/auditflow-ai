from django.urls import path

from . import views


app_name = "dossiers"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/imports/<uuid:batch_id>/dossier/",
        views.download_work_dossier,
        name="download",
    ),
]
