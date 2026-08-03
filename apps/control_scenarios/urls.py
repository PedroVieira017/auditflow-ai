from django.urls import path

from .views import (
    control_scenario_approve,
    control_scenario_create,
    control_scenario_detail,
    control_scenario_list,
)


app_name = "control_scenarios"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/control-scenarios/",
        control_scenario_list,
        name="list",
    ),
    path(
        "organizations/<uuid:organization_id>/control-scenarios/new/",
        control_scenario_create,
        name="create",
    ),
    path(
        "organizations/<uuid:organization_id>/control-scenarios/"
        "<uuid:scenario_id>/",
        control_scenario_detail,
        name="detail",
    ),
    path(
        "organizations/<uuid:organization_id>/control-scenarios/"
        "<uuid:scenario_id>/approve/",
        control_scenario_approve,
        name="approve",
    ),
]
