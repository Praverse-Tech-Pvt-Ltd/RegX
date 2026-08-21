"""Regulatory case URL configuration."""

from django.urls import path

from . import views

app_name = "regulatory_cases"

urlpatterns = [
    path(
        "regulatory-cases/",
        views.RegulatoryCaseListCreateView.as_view(),
        name="case-list-create",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/",
        views.RegulatoryCaseDetailView.as_view(),
        name="case-detail",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/complete/",
        views.RegulatoryCaseCompleteView.as_view(),
        name="case-complete",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/cancel/",
        views.RegulatoryCaseCancelView.as_view(),
        name="case-cancel",
    ),
    # One pair per link kind. The kind is part of the path rather than the body
    # so the URL resolver rejects an unknown kind before any view runs.
    path(
        "regulatory-cases/<uuid:public_id>/workflows/",
        views.CaseWorkflowListCreateView.as_view(),
        name="case-workflows",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/workflows/<uuid:link_public_id>/",
        views.CaseWorkflowDetailView.as_view(),
        name="case-workflow-detail",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/documents/",
        views.CaseDocumentListCreateView.as_view(),
        name="case-documents",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/documents/<uuid:link_public_id>/",
        views.CaseDocumentDetailView.as_view(),
        name="case-document-detail",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/checklists/",
        views.CaseChecklistListCreateView.as_view(),
        name="case-checklists",
    ),
    path(
        "regulatory-cases/<uuid:public_id>/checklists/<uuid:link_public_id>/",
        views.CaseChecklistDetailView.as_view(),
        name="case-checklist-detail",
    ),
]
