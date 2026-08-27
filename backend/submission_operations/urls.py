from django.urls import path

from .views import (
    OperationsAttentionView,
    OperationsCaseListView,
    OperationsDossierListView,
    OperationsOverviewView,
    OperationsOwnerListView,
    OperationsRecentActivityView,
)

urlpatterns = [
    path(
        "submission-operations/overview/",
        OperationsOverviewView.as_view(),
        name="operations-overview",
    ),
    path(
        "submission-operations/attention/",
        OperationsAttentionView.as_view(),
        name="operations-attention",
    ),
    path(
        "submission-operations/cases/",
        OperationsCaseListView.as_view(),
        name="operations-cases",
    ),
    path(
        "submission-operations/dossiers/",
        OperationsDossierListView.as_view(),
        name="operations-dossiers",
    ),
    path(
        "submission-operations/owners/",
        OperationsOwnerListView.as_view(),
        name="operations-owners",
    ),
    path(
        "submission-operations/recent-activity/",
        OperationsRecentActivityView.as_view(),
        name="operations-recent-activity",
    ),
]
