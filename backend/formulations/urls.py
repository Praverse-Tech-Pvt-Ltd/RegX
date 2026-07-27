"""Formulations domain URL configuration."""

from django.urls import path

from . import views

app_name = "formulations"

urlpatterns = [
    path("formulations/products/", views.ProductListView.as_view(), name="product-list"),
    path(
        "formulations/products/<uuid:public_id>/",
        views.ProductDetailView.as_view(),
        name="product-detail",
    ),
    path(
        "formulations/products/<uuid:public_id>/select-reference/",
        views.SelectReferenceProductView.as_view(),
        name="product-select-reference",
    ),
    path(
        "formulations/products/<uuid:public_id>/versions/",
        views.FormulationVersionListCreateView.as_view(),
        name="version-list-create",
    ),
    path(
        "formulations/versions/<uuid:public_id>/",
        views.FormulationVersionDetailView.as_view(),
        name="version-detail",
    ),
    path(
        "formulations/versions/<uuid:public_id>/components/",
        views.FormulationComponentListView.as_view(),
        name="component-list",
    ),
    path(
        "formulations/versions/<uuid:public_id>/dosing-regimens/",
        views.DosingRegimenListView.as_view(),
        name="dosing-regimen-list",
    ),
]
