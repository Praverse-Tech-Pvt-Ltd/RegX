from django.urls import path

from .views import DeficiencyDetailView, DeficiencyFacetsView, DeficiencyListView

urlpatterns = [
    path("deficiencies/", DeficiencyListView.as_view(), name="deficiency-list"),
    path("deficiencies/facets/", DeficiencyFacetsView.as_view(), name="deficiency-facets"),
    path(
        "deficiencies/<uuid:public_id>/",
        DeficiencyDetailView.as_view(),
        name="deficiency-detail",
    ),
]
