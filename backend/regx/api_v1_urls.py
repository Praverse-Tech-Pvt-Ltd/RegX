"""Versioned API v1 URL routing."""

from django.urls import include, path

urlpatterns = [
    path("", include("common.urls")),  # health, readiness, version
    path("auth/", include("identity.urls")),  # csrf, login, logout, me
    path("tenants/", include("tenancy.urls")),
    path("permissions/", include("authorization.urls")),
    path("mfa/", include("identity.mfa_urls")),
    path("documents/", include("documents.urls")),
]
