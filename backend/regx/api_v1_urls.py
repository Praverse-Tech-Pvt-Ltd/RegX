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
    path("", include("fda_data.urls")),
    path("", include("formulations.urls")),
    path("", include("iid_assessment.urls")),
    path("", include("iig_checklist.urls")),
]
