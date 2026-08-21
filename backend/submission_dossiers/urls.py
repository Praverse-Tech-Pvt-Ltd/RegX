"""Submission dossier URL configuration."""

from django.urls import path

from . import views

app_name = "submission_dossiers"

urlpatterns = [
    # Dossiers live under their case for creation and listing, and at a
    # top-level path once addressed directly -- a dossier public_id is
    # sufficient to locate one, so nesting it forever would only make every
    # client carry the case id around.
    path(
        "regulatory-cases/<uuid:case_public_id>/dossiers/",
        views.CaseDossierListCreateView.as_view(),
        name="case-dossiers",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/",
        views.DossierDetailView.as_view(),
        name="dossier-detail",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/complete/",
        views.DossierCompleteView.as_view(),
        name="dossier-complete",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/cancel/",
        views.DossierCancelView.as_view(),
        name="dossier-cancel",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/sections/",
        views.DossierSectionListCreateView.as_view(),
        name="dossier-sections",
    ),
    path(
        "dossier-sections/<uuid:public_id>/",
        views.SectionDetailView.as_view(),
        name="section-detail",
    ),
    path(
        "dossier-sections/<uuid:public_id>/reorder/",
        views.SectionReorderView.as_view(),
        name="section-reorder",
    ),
    path(
        "dossier-sections/<uuid:public_id>/retire/",
        views.SectionRetireView.as_view(),
        name="section-retire",
    ),
    path(
        "dossier-sections/<uuid:public_id>/blockers/",
        views.SectionBlockerListCreateView.as_view(),
        name="section-blockers",
    ),
    path(
        "section-blockers/<uuid:public_id>/resolve/",
        views.BlockerResolveView.as_view(),
        name="blocker-resolve",
    ),
    # One pair per link kind. The kind is in the path, so a document permission
    # can never be aimed at a workflow by changing a body field.
    path(
        "dossier-sections/<uuid:public_id>/documents/",
        views.SectionDocumentListCreateView.as_view(),
        name="section-documents",
    ),
    path(
        "dossier-sections/<uuid:public_id>/documents/<uuid:link_public_id>/",
        views.SectionDocumentDetailView.as_view(),
        name="section-document-detail",
    ),
    path(
        "dossier-sections/<uuid:public_id>/workflows/",
        views.SectionWorkflowListCreateView.as_view(),
        name="section-workflows",
    ),
    path(
        "dossier-sections/<uuid:public_id>/workflows/<uuid:link_public_id>/",
        views.SectionWorkflowDetailView.as_view(),
        name="section-workflow-detail",
    ),
    path(
        "dossier-sections/<uuid:public_id>/checklists/",
        views.SectionChecklistListCreateView.as_view(),
        name="section-checklists",
    ),
    path(
        "dossier-sections/<uuid:public_id>/checklists/<uuid:link_public_id>/",
        views.SectionChecklistDetailView.as_view(),
        name="section-checklist-detail",
    ),
]
