"""FDA data-governance domain URL configuration."""

from django.urls import path

from . import views

app_name = "fda_data"

urlpatterns = [
    path("fda-data/releases/", views.FdaReleaseListView.as_view(), name="release-list"),
    path(
        "fda-data/releases/<uuid:public_id>/",
        views.FdaReleaseDetailView.as_view(),
        name="release-detail",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/validate/",
        views.FdaReleaseValidateView.as_view(),
        name="release-validate",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/submit-review/",
        views.FdaReleaseSubmitReviewView.as_view(),
        name="release-submit-review",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/approve/",
        views.FdaReleaseApproveView.as_view(),
        name="release-approve",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/activate/",
        views.FdaReleaseActivateView.as_view(),
        name="release-activate",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/reconciliation.json",
        views.FdaReleaseReconciliationJsonView.as_view(),
        name="release-reconciliation-json",
    ),
    path(
        "fda-data/releases/<uuid:public_id>/reconciliation.csv",
        views.FdaReleaseReconciliationCsvView.as_view(),
        name="release-reconciliation-csv",
    ),
    path(
        "fda-data/orange-book/products/",
        views.OrangeBookProductListView.as_view(),
        name="orange-book-product-list",
    ),
    path(
        "fda-data/orange-book/products/<uuid:public_id>/",
        views.OrangeBookProductDetailView.as_view(),
        name="orange-book-product-detail",
    ),
    path("fda-data/iid/records/", views.IidRecordListView.as_view(), name="iid-record-list"),
    path(
        "fda-data/iid/records/<uuid:public_id>/",
        views.IidRecordDetailView.as_view(),
        name="iid-record-detail",
    ),
    path(
        "fda-data/controlled-routes/",
        views.ControlledRouteListView.as_view(),
        name="controlled-route-list",
    ),
    path(
        "fda-data/controlled-dosage-forms/",
        views.ControlledDosageFormListView.as_view(),
        name="controlled-dosage-form-list",
    ),
    path(
        "fda-data/controlled-units/",
        views.ControlledUnitListView.as_view(),
        name="controlled-unit-list",
    ),
    path(
        "fda-data/controlled-units/meanings/",
        views.ControlledUnitMeaningListView.as_view(),
        name="controlled-unit-meaning-list",
    ),
    path("fda-data/mappings/", views.TerminologyMappingListView.as_view(), name="mapping-list"),
    path(
        "fda-data/mappings/substances/proposals/",
        views.SubstanceMappingProposalView.as_view(),
        name="mapping-substance-proposal",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/",
        views.TerminologyMappingDetailView.as_view(),
        name="mapping-detail",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/submit-review/",
        views.TerminologyMappingSubmitReviewView.as_view(),
        name="mapping-submit-review",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/approve/",
        views.TerminologyMappingApproveView.as_view(),
        name="mapping-approve",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/reject/",
        views.TerminologyMappingRejectView.as_view(),
        name="mapping-reject",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/return/",
        views.TerminologyMappingReturnView.as_view(),
        name="mapping-return",
    ),
    path(
        "fda-data/mappings/<uuid:public_id>/affected-records/",
        views.TerminologyMappingAffectedRecordsView.as_view(),
        name="mapping-affected-records",
    ),
]
