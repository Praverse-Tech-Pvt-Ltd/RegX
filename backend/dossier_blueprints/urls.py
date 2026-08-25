"""Blueprint routes.

Versions and sections are addressed directly once they have an id -- a version
`public_id` locates one on its own -- and created under their parent, matching
the shape `submission_dossiers` already uses.
"""

from django.urls import path

from .views import (
    BlueprintArchiveView,
    BlueprintDetailView,
    BlueprintListCreateView,
    BlueprintSectionDetailView,
    BlueprintSectionListCreateView,
    BlueprintSectionReorderView,
    BlueprintSectionRetireView,
    BlueprintVersionActivateView,
    BlueprintVersionDetailView,
    BlueprintVersionInstantiateView,
    BlueprintVersionListCreateView,
    BlueprintVersionRetireView,
    DossierProvenanceView,
)

urlpatterns = [
    path("dossier-blueprints/", BlueprintListCreateView.as_view(), name="blueprint-list"),
    path(
        "dossier-blueprints/<uuid:public_id>/",
        BlueprintDetailView.as_view(),
        name="blueprint-detail",
    ),
    path(
        "dossier-blueprints/<uuid:public_id>/archive/",
        BlueprintArchiveView.as_view(),
        name="blueprint-archive",
    ),
    path(
        "dossier-blueprints/<uuid:public_id>/versions/",
        BlueprintVersionListCreateView.as_view(),
        name="blueprint-versions",
    ),
    path(
        "dossier-blueprint-versions/<uuid:public_id>/",
        BlueprintVersionDetailView.as_view(),
        name="blueprint-version-detail",
    ),
    path(
        "dossier-blueprint-versions/<uuid:public_id>/activate/",
        BlueprintVersionActivateView.as_view(),
        name="blueprint-version-activate",
    ),
    path(
        "dossier-blueprint-versions/<uuid:public_id>/retire/",
        BlueprintVersionRetireView.as_view(),
        name="blueprint-version-retire",
    ),
    path(
        "dossier-blueprint-versions/<uuid:public_id>/sections/",
        BlueprintSectionListCreateView.as_view(),
        name="blueprint-version-sections",
    ),
    path(
        "dossier-blueprint-versions/<uuid:public_id>/instantiate/",
        BlueprintVersionInstantiateView.as_view(),
        name="blueprint-version-instantiate",
    ),
    path(
        "dossier-blueprint-sections/<uuid:public_id>/",
        BlueprintSectionDetailView.as_view(),
        name="blueprint-section-detail",
    ),
    path(
        "dossier-blueprint-sections/<uuid:public_id>/reorder/",
        BlueprintSectionReorderView.as_view(),
        name="blueprint-section-reorder",
    ),
    path(
        "dossier-blueprint-sections/<uuid:public_id>/retire/",
        BlueprintSectionRetireView.as_view(),
        name="blueprint-section-retire",
    ),
    path(
        "submission-dossiers/<uuid:public_id>/blueprint-provenance/",
        DossierProvenanceView.as_view(),
        name="dossier-blueprint-provenance",
    ),
]
