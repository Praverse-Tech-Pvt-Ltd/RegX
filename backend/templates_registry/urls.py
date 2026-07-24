"""Template registry domain URL configuration."""

from django.urls import path

from . import views

app_name = "templates_registry"

urlpatterns = [
    # Templates
    path("templates/", views.TemplateListView.as_view(), name="template-list"),
    path("templates/<uuid:public_id>/", views.TemplateDetailView.as_view(), name="template-detail"),
    path(
        "templates/<uuid:public_id>/versions/",
        views.TemplateVersionListView.as_view(),
        name="version-list",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/",
        views.TemplateVersionDetailView.as_view(),
        name="version-detail",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/sections/",
        views.TemplateSectionListView.as_view(),
        name="version-sections",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/items/",
        views.TemplateItemListView.as_view(),
        name="version-items",
    ),
    # Lifecycle actions
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/submit-review/",
        views.TemplateVersionSubmitReviewView.as_view(),
        name="version-submit-review",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/approve/",
        views.TemplateVersionApproveView.as_view(),
        name="version-approve",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/return/",
        views.TemplateVersionReturnView.as_view(),
        name="version-return",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/reject/",
        views.TemplateVersionRejectView.as_view(),
        name="version-reject",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/activate/",
        views.TemplateVersionActivateView.as_view(),
        name="version-activate",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/supersede/",
        views.TemplateVersionSupersedeView.as_view(),
        name="version-supersede",
    ),
    path(
        "templates/<uuid:public_id>/versions/<uuid:version_public_id>/retire/",
        views.TemplateVersionRetireView.as_view(),
        name="version-retire",
    ),
    # Source packages
    path(
        "template-sources/",
        views.TemplateSourcePackageListView.as_view(),
        name="source-package-list",
    ),
    # Migration batches
    path("migration-batches/", views.MigrationBatchListView.as_view(), name="batch-list"),
    path(
        "migration-batches/<uuid:public_id>/",
        views.MigrationBatchDetailView.as_view(),
        name="batch-detail",
    ),
    path(
        "migration-batches/<uuid:public_id>/results/",
        views.MigrationBatchResultsView.as_view(),
        name="batch-results",
    ),
    path(
        "migration-batches/<uuid:public_id>/review/",
        views.MigrationBatchReviewView.as_view(),
        name="batch-review",
    ),
    path(
        "migration-batches/<uuid:public_id>/reconciliation.csv",
        views.MigrationBatchReconciliationCsvView.as_view(),
        name="batch-reconciliation-csv",
    ),
    path(
        "migration-batches/<uuid:public_id>/reconciliation.json",
        views.MigrationBatchReconciliationJsonView.as_view(),
        name="batch-reconciliation-json",
    ),
]
