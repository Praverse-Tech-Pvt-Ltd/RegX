"""IID assessment domain URL configuration."""

from django.urls import path

from . import views

app_name = "iid_assessment"

urlpatterns = [
    path("iid-assessments/preview/", views.MatchPreviewView.as_view(), name="preview"),
    path("iid-assessments/snapshot/", views.SnapshotView.as_view(), name="snapshot"),
    path(
        "iid-assessments/<uuid:public_id>/",
        views.SnapshotDetailView.as_view(),
        name="snapshot-detail",
    ),
]
