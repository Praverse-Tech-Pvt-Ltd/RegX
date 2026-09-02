"""Upgrade plan routes.

Plans are created and listed under their dossier -- a plan only exists for one
dossier -- and addressed directly once they have an id, since a plan public_id
locates one on its own. Same shape `submission_dossiers` and `dossier_blueprints`
already use.
"""

from django.urls import path

from .views import (
    DossierUpgradeHistoryView,
    DossierUpgradePlanListCreateView,
    UpgradePlanApplyView,
    UpgradePlanCancelView,
    UpgradePlanDetailView,
    UpgradePlanItemAcceptView,
    UpgradePlanItemRejectView,
    UpgradePlanReadyView,
    UpgradePlanRegenerateView,
)

urlpatterns = [
    path(
        "submission-dossiers/<uuid:public_id>/upgrade-plans/",
        DossierUpgradePlanListCreateView.as_view(),
        name="dossier-upgrade-plans",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/upgrade-history/",
        DossierUpgradeHistoryView.as_view(),
        name="dossier-upgrade-history",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/",
        UpgradePlanDetailView.as_view(),
        name="upgrade-plan-detail",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/regenerate/",
        UpgradePlanRegenerateView.as_view(),
        name="upgrade-plan-regenerate",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/ready/",
        UpgradePlanReadyView.as_view(),
        name="upgrade-plan-ready",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/apply/",
        UpgradePlanApplyView.as_view(),
        name="upgrade-plan-apply",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/cancel/",
        UpgradePlanCancelView.as_view(),
        name="upgrade-plan-cancel",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/items/<uuid:item_public_id>/accept/",
        UpgradePlanItemAcceptView.as_view(),
        name="upgrade-plan-item-accept",
    ),
    path(
        "dossier-upgrade-plans/<uuid:public_id>/items/<uuid:item_public_id>/reject/",
        UpgradePlanItemRejectView.as_view(),
        name="upgrade-plan-item-reject",
    ),
]
