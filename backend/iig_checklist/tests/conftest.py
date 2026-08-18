"""Fixtures for iig_checklist domain tests. Synthetic content only."""

import pytest


@pytest.fixture
def tenant_a(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")


@pytest.fixture
def tenant_b(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")


def _make_user(email, full_name):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


@pytest.fixture
def user_a(db):
    return _make_user("checklist-user-a@example.com", "User A")


@pytest.fixture
def reviewer_user(db):
    return _make_user("checklist-reviewer@example.com", "Reviewer")


@pytest.fixture
def vp_user(db):
    return _make_user("checklist-vp@example.com", "VP")


@pytest.fixture
def tenant_admin_user(db):
    return _make_user("checklist-tenant-admin@example.com", "Tenant Admin")


@pytest.fixture
def platform_support_user(db):
    return _make_user("checklist-platform-support@example.com", "Platform Support")


@pytest.fixture
def platform_actor_user(db):
    """The only kind of user that satisfies can_author_platform_master():
    Django's is_superuser flag, deliberately independent of tenant
    membership/role."""
    user = _make_user("checklist-platform-actor@example.com", "Platform Actor")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    return user


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name=role_name, defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


@pytest.fixture
def doer_membership(db, tenant_a, user_a):
    return _membership_with_role(tenant_a, user_a, "doer")


@pytest.fixture
def reviewer_membership(db, tenant_a, reviewer_user):
    return _membership_with_role(tenant_a, reviewer_user, "reviewer")


@pytest.fixture
def vp_membership(db, tenant_a, vp_user):
    return _membership_with_role(tenant_a, vp_user, "vp")


@pytest.fixture
def api_client_doer(user_a, tenant_a, doer_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_a)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_reviewer(reviewer_user, tenant_a, reviewer_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=reviewer_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_vp(vp_user, tenant_a, vp_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=vp_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def tenant_admin_membership(db, tenant_a, tenant_admin_user):
    return _membership_with_role(tenant_a, tenant_admin_user, "tenant_admin")


@pytest.fixture
def platform_support_membership(db, tenant_a, platform_support_user):
    return _membership_with_role(tenant_a, platform_support_user, "platform_support")


@pytest.fixture
def api_client_tenant_admin(tenant_admin_user, tenant_a, tenant_admin_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=tenant_admin_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_platform_support(platform_support_user, tenant_a, platform_support_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=platform_support_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def api_client_platform_actor(platform_actor_user, tenant_a):
    """A platform-authorized actor still needs *some* tenant context to
    pass through the tenant middleware/current_tenant() -- give them a
    Doer membership too, so the test proves platform authority is what
    grants platform_master creation, not the Doer role itself (which
    api_client_doer already proves is insufficient on its own)."""
    from rest_framework.test import APIClient

    _membership_with_role(tenant_a, platform_actor_user, "doer")
    client = APIClient()
    client.force_authenticate(user=platform_actor_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def tenant_definition(db, tenant_a, user_a):
    from iig_checklist.models import ChecklistDefinition

    return ChecklistDefinition.objects.create(
        code="IIG-ORAL-SOLID",
        title="IIG Oral Solid (synthetic)",
        scope_type="tenant",
        # OQ-8: every definition must carry a governed execution scope before an
        # execution can be created against it. This shared fixture is
        # formulation-version scoped because most suites here exercise the generic
        # checklist engine; the component-scoped fixture below is for IID/IIG.
        execution_scope="formulation_version",
        tenant=tenant_a,
        created_by=user_a,
    )


@pytest.fixture
def component_scoped_definition(db, tenant_a, user_a):
    """An IID/IIG definition: one execution is about one inactive ingredient."""
    from iig_checklist.models import ChecklistDefinition

    return ChecklistDefinition.objects.create(
        code="IIG-COMPONENT-SCOPED",
        title="IIG component-scoped (synthetic)",
        scope_type="tenant",
        execution_scope="formulation_component",
        tenant=tenant_a,
        created_by=user_a,
    )


@pytest.fixture
def unclassified_definition(db, tenant_a, user_a):
    """A definition with no governed execution scope -- must fail closed."""
    from iig_checklist.models import ChecklistDefinition

    return ChecklistDefinition.objects.create(
        code="IIG-UNCLASSIFIED",
        title="IIG unclassified (synthetic)",
        scope_type="tenant",
        tenant=tenant_a,
        created_by=user_a,
    )


@pytest.fixture
def draft_version(db, tenant_definition, user_a):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        created_by=user_a,
    )


@pytest.fixture
def platform_definition(db, platform_actor_user):
    from iig_checklist.models import ChecklistDefinition

    return ChecklistDefinition.objects.create(
        code="PLATFORM-ORAL-SOLID",
        title="Platform Oral Solid (synthetic)",
        scope_type="platform_master",
        execution_scope="formulation_version",
        tenant=None,
        created_by=platform_actor_user,
    )


@pytest.fixture
def platform_draft_version(db, platform_definition, platform_actor_user):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=platform_definition,
        version_number=1,
        created_by=platform_actor_user,
    )


@pytest.fixture
def platform_section(db, platform_draft_version):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=platform_draft_version,
        code="SEC-1",
        title="Section 1",
        display_order=1,
        criticality="medium",
    )


@pytest.fixture
def platform_question(db, platform_section):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=platform_section,
        code="Q-1",
        question_text="Is this synthetic?",
        display_order=1,
        answer_type="yes_no",
        data_source_classification="user_required",
        criticality="low",
    )


@pytest.fixture
def api_client_platform_actor_full(platform_actor_user, tenant_a):
    """The platform actor also holds Reviewer+VP roles in tenant_a, so
    the same actor can exercise the full lifecycle (submit/return/
    approve/activate/etc.) on platform-master content while proving the
    platform grant -- not an ordinary role -- is what makes platform
    mutation succeed."""
    from rest_framework.test import APIClient

    _membership_with_role(tenant_a, platform_actor_user, "doer")
    _membership_with_role(tenant_a, platform_actor_user, "reviewer")
    _membership_with_role(tenant_a, platform_actor_user, "vp")
    client = APIClient()
    client.force_authenticate(user=platform_actor_user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client
