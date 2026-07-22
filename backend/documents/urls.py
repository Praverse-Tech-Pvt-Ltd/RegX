"""Document domain URL configuration."""

from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    # Collection
    path("", views.DocumentListCreateView.as_view(), name="list-create"),
    # Document detail
    path("<uuid:public_id>/", views.DocumentDetailView.as_view(), name="detail"),
    # Versions
    path(
        "<uuid:public_id>/versions/",
        views.DocumentVersionListCreateView.as_view(),
        name="version-list-create",
    ),
    path(
        "<uuid:public_id>/versions/<uuid:version_public_id>/",
        views.DocumentVersionDetailView.as_view(),
        name="version-detail",
    ),
    path(
        "<uuid:public_id>/versions/<uuid:version_public_id>/status/",
        views.DocumentVersionStatusView.as_view(),
        name="version-status",
    ),
    path(
        "<uuid:public_id>/versions/<uuid:version_public_id>/locators/",
        views.DocumentLocatorListView.as_view(),
        name="version-locators",
    ),
    # Document lifecycle
    path("<uuid:public_id>/archive/", views.DocumentArchiveView.as_view(), name="archive"),
    path("<uuid:public_id>/restore/", views.DocumentRestoreView.as_view(), name="restore"),
]
