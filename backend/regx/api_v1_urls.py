"""Versioned API v1 URL routing."""

from django.urls import include, path

urlpatterns = [
    path("", include("common.urls")),  # health, readiness, version
    path("auth/", include("identity.urls")),  # csrf, login, logout, me
    path("tenants/", include("tenancy.urls")),
    path("permissions/", include("authorization.urls")),
    path("mfa/", include("identity.mfa_urls")),
    path("documents/", include("documents.urls")),
    path("", include("templates_registry.urls")),
    path("", include("controlled_correspondence.urls")),
    path("", include("product_comparison.urls")),
    path("", include("deficiencies.urls")),
    path("", include("fda_data.urls")),
    path("", include("inspections.urls")),
    path("", include("formulations.urls")),
    path("", include("iid_assessment.urls")),
    path("", include("iig_checklist.urls")),
    path("", include("workflows.urls")),
    path("", include("regulatory_cases.urls")),
    path("", include("submission_dossiers.urls")),
    path("", include("dossier_blueprints.urls")),
    path("", include("dossier_upgrades.urls")),
    path("", include("submission_operations.urls")),
    path("", include("submission_packages.urls")),
    path("", include("external_integrations.urls")),
    path("", include("ai_gateway.urls")),
]
