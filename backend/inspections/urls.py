from django.urls import path

from .views import (
    Form483DetailView,
    Form483ListView,
    InspectionFacetsView,
    ObservationSearchView,
    WarningLetterDetailView,
    WarningLetterListView,
)

urlpatterns = [
    path("inspections/form483/", Form483ListView.as_view(), name="form483-list"),
    path(
        "inspections/form483/facets/",
        InspectionFacetsView.as_view(),
        name="inspection-facets",
    ),
    path(
        "inspections/observations/",
        ObservationSearchView.as_view(),
        name="observation-search",
    ),
    path(
        "inspections/form483/<uuid:public_id>/",
        Form483DetailView.as_view(),
        name="form483-detail",
    ),
    path(
        "inspections/warning-letters/",
        WarningLetterListView.as_view(),
        name="warning-letter-list",
    ),
    path(
        "inspections/warning-letters/<uuid:public_id>/",
        WarningLetterDetailView.as_view(),
        name="warning-letter-detail",
    ),
]
