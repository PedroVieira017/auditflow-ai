from django.urls import path

from . import views


app_name = "imports"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/imports/new/",
        views.upload_invoice_csv,
        name="upload",
    ),
    path(
        "organizations/<uuid:organization_id>/imports/<uuid:batch_id>/",
        views.import_detail,
        name="detail",
    ),
]
