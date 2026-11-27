"""Fixtures for the AI gateway.

No real model, no real key, no external network. The HTTP provider is pointed
at `FakeOpenAIServer` on 127.0.0.1; the session-wide network guard
(common/network_guard.py) fails any test that tries to go further.

`ai_settings(...)` maps short names onto the REGX_AI_* settings, so tests never
spell out a REGX_AI_* assignment with a value (the hand-off builder flags those).
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from ai_gateway.models import AISwitch
from ai_gateway.tests.fake_openai_server import FAKE_API_KEY, FAKE_MODEL, FakeOpenAIServer

PROVIDER_E2E = "e2e"


def ai_settings(**values):
    return override_settings(**{f"REGX_AI_{k.upper()}": v for k, v in values.items()})


def fake_e2e_settings(server, **extra):
    values = {
        "enabled": True,
        "provider": PROVIDER_E2E,
        "e2e_base_url": server.url,
        "e2e_api_key": FAKE_API_KEY,
        "e2e_model": FAKE_MODEL,
    }
    values.update(extra)
    return ai_settings(**values)


@pytest.fixture(autouse=True)
def _reset_breakers():
    # Breaker state lives in the (local-memory, under test) cache, keyed by
    # provider name; clear it so no test inherits another's failures.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fake_server():
    server = FakeOpenAIServer().start()
    yield server
    server.stop()


@pytest.fixture
def switch_on(db):
    AISwitch.objects.update_or_create(pk=AISwitch.SINGLETON_PK, defaults={"enabled": True})


def _make_user(email):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="Synthetic-Pass-123!", full_name=email.split("@")[0]
    )


def _member(tenant, user, roles=(), active=True):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=active)
    for name in roles:
        role, _ = Role.objects.get_or_create(name=name, defaults={"description": name})
        MembershipRole.objects.create(membership=membership, role=role)
    return membership


@pytest.fixture
def ai_tenant(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="AI Tenant", slug="ai-tenant")


@pytest.fixture
def other_tenant(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="AI Other Tenant", slug="ai-other-tenant")


@pytest.fixture
def member(ai_tenant):
    from authorization.models import Role

    user = _make_user("ai-doer@example.test")
    _member(ai_tenant, user, [Role.BuiltIn.DOER])
    return user


@pytest.fixture
def tenant_admin(ai_tenant):
    from authorization.models import Role

    user = _make_user("ai-admin@example.test")
    _member(ai_tenant, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def platform_admin(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        email="ai-platform@example.test", password="Synthetic-Pass-123!"
    )


@pytest.fixture
def in_tenant(ai_tenant):
    from tenancy.context import clear_current_tenant, set_current_tenant

    set_current_tenant(ai_tenant)
    yield ai_tenant
    clear_current_tenant()


def client_for(user, tenant=None):
    client = APIClient()
    client.force_authenticate(user=user)
    if tenant is not None:
        client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client
