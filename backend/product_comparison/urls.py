from django.urls import path

from .views import (
    ComparisonAttributeView,
    ComparisonDetailView,
    ComparisonListView,
    ComparisonMatrixView,
)

urlpatterns = [
    path("product-comparisons/", ComparisonListView.as_view(), name="comparison-list"),
    path(
        "product-comparisons/<uuid:public_id>/",
        ComparisonDetailView.as_view(),
        name="comparison-detail",
    ),
    path(
        "product-comparisons/<uuid:public_id>/matrix/",
        ComparisonMatrixView.as_view(),
        name="comparison-matrix",
    ),
    path(
        "product-comparisons/<uuid:public_id>/attributes/",
        ComparisonAttributeView.as_view(),
        name="comparison-attribute",
    ),
]
