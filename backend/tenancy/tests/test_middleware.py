"""
TenantMiddleware regression tests.

Proves that the middleware change (tenant resolution regardless of session-auth
state) does not create authorization bypasses. All test cases use the real
middleware stack via DRF APIClient so the request lifecycle is accurate.
"""

import pytest
from rest_framework.test import APIClient

DOCUMENTS_URL = "/api/regx/v1/documents/"


@pytest.fixture
def doer_membership(db, user, tenant):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    mem, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(name="doer", tenant=None, defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=mem, role=role)
    return mem


def _client(user=None, tenant_slug=None):
    """Build an APIClient, optionally authenticated and with a tenant header."""
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    if tenant_slug is not None:
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant_slug})
    return client


# ---------------------------------------------------------------------------
# Unauthenticated requests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUnauthenticatedTenantHeader:
    def test_unknown_tenant_slug_returns_404(self):
        """A completely unknown tenant slug returns 404 from middleware."""
        client = _client(tenant_slug="no-such-tenant")
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 404

    def test_valid_tenant_slug_without_auth_returns_403(self, tenant):
        """Valid tenant slug but no credentials → DRF authentication check
        rejects the request (403/401) — tenant is not activated for attacker."""
        client = _client(tenant_slug=tenant.slug)
        resp = client.get(DOCUMENTS_URL)
        # DRF IsAuthenticated yields 403 (or 401 with WWW-Authenticate)
        assert resp.status_code in (401, 403)

    def test_no_tenant_header_no_auth_returns_403(self):
        """No header, no auth → still rejected by authentication."""
        client = _client()
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Authenticated non-member
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthenticatedNonMember:
    def test_non_member_receives_403(self, user, tenant):
        """Authenticated user who is NOT a member of the tenant is rejected
        by middleware with 403 when session auth has resolved the user."""
        # Use session authentication so middleware can see is_authenticated=True
        from rest_framework.test import APIClient

        # force_authenticate bypasses Django session middleware, so middleware
        # sees AnonymousUser. We need to test the session-auth path instead.
        # Use APIClient.login() to exercise the session-auth middleware path.
        client_session = APIClient()
        client_session.force_login(user)
        client_session.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
        resp = client_session.get(DOCUMENTS_URL)
        assert resp.status_code == 403

    def test_non_member_cannot_escalate_with_force_authenticate(self, user, tenant):
        """force_authenticate sets user at view layer; middleware cannot check
        membership. The DRF permission class (CanViewDocument) must handle this."""
        client = _client(user=user, tenant_slug=tenant.slug)
        # Tenant context is set (middleware resolved slug), but view-layer
        # permission check must reject non-member access.
        resp = client.get(DOCUMENTS_URL)
        # CanViewDocument calls has_document_permission which checks role;
        # user has no role → 403
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Authenticated member
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthenticatedMember:
    def test_member_can_activate_own_tenant(self, user, tenant, doer_membership):
        """Member with force_authenticate can reach the documents list (200)."""
        client = _client(user=user, tenant_slug=tenant.slug)
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 200

    def test_member_cannot_access_other_tenant(self, user, tenant, doer_membership):
        """Member of tenant A cannot access tenant B even with a valid slug."""
        from tenancy.models import Tenant

        other = Tenant.objects.create(name="Other Org", slug="other-org")
        client = _client(user=user, tenant_slug=other.slug)
        # Middleware resolves other-org; permission class checks membership
        # for force_authenticate path → 403
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 403

    def test_inactive_tenant_returns_404(self, user, tenant, doer_membership):
        """Middleware rejects an inactive (suspended) tenant slug with 404."""
        from tenancy.models import Tenant

        tenant.status = Tenant.Status.SUSPENDED
        tenant.save()
        client = _client(user=user, tenant_slug=tenant.slug)
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Header edge cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTenantHeaderEdgeCases:
    def test_empty_header_value_ignored(self, user, doer_membership):
        """Empty string header value: middleware skips tenant resolution;
        view-layer sees no tenant context → 403/PermissionDenied."""
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_TENANT_SLUG="")
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 403

    def test_missing_header_gives_no_tenant_context(self, user, doer_membership):
        """Request without the header: no tenant set → view rejects."""
        client = _client(user=user)  # no tenant header
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 403

    def test_sql_injection_in_slug_returns_404(self, user):
        """Adversarial slug value that would trip a naive query is handled
        safely — slug field lookup fails, returns 404."""
        client = _client(user=user, tenant_slug="'; DROP TABLE tenancy_tenant; --")
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 404

    def test_very_long_slug_returns_404(self, user):
        """Oversized slug (not in DB) returns 404, no crash."""
        client = _client(user=user, tenant_slug="a" * 500)
        resp = client.get(DOCUMENTS_URL)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth/CSRF endpoints unaffected by middleware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthEndpointsUnaffected:
    def test_csrf_endpoint_works_without_tenant_header(self):
        """The CSRF endpoint must not require a tenant header."""
        client = APIClient()
        resp = client.get("/api/regx/v1/auth/csrf/")
        assert resp.status_code == 200

    def test_login_endpoint_works_without_tenant_header(self):
        """Login does not require a tenant header."""
        client = APIClient()
        resp = client.post(
            "/api/regx/v1/auth/login/",
            {"email": "x@example.com", "password": "bad"},
            format="json",
        )
        # 400 (bad creds) but NOT a 404 from middleware
        assert resp.status_code != 404

    def test_tenant_header_on_auth_endpoint_does_not_crash(self, tenant):
        """Tenant header on a non-document endpoint is resolved harmlessly."""
        client = APIClient()
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
        resp = client.get("/api/regx/v1/auth/csrf/")
        assert resp.status_code == 200
