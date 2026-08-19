"""Workflows domain URL configuration."""

from django.urls import path

from . import views

app_name = "workflows"

urlpatterns = [
    path("workflows/", views.WorkflowItemListCreateView.as_view(), name="item-list-create"),
    path(
        "workflows/<uuid:public_id>/",
        views.WorkflowItemDetailView.as_view(),
        name="item-detail",
    ),
    path(
        "workflows/<uuid:public_id>/history/",
        views.WorkflowHistoryView.as_view(),
        name="item-history",
    ),
    path("workflows/<uuid:public_id>/submit/", views.SubmitView.as_view(), name="item-submit"),
    path(
        "workflows/<uuid:public_id>/begin-review/",
        views.BeginReviewView.as_view(),
        name="item-begin-review",
    ),
    path("workflows/<uuid:public_id>/approve/", views.ApproveView.as_view(), name="item-approve"),
    path("workflows/<uuid:public_id>/reject/", views.RejectView.as_view(), name="item-reject"),
    path("workflows/<uuid:public_id>/cancel/", views.CancelView.as_view(), name="item-cancel"),
    path(
        "workflows/<uuid:public_id>/return-to-draft/",
        views.ReturnToDraftView.as_view(),
        name="item-return-to-draft",
    ),
    path("workflows/<uuid:public_id>/assign/", views.AssignView.as_view(), name="item-assign"),
    path(
        "workflows/<uuid:public_id>/evidence/",
        views.WorkflowEvidenceView.as_view(),
        name="item-evidence",
    ),
    path(
        "workflows/<uuid:public_id>/evidence/<uuid:evidence_public_id>/",
        views.WorkflowEvidenceDetailView.as_view(),
        name="item-evidence-detail",
    ),
]
