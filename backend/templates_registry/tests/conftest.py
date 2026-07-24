"""
Fixtures for template registry domain tests.

All fixtures use synthetic, non-confidential data modeled on the
structural shape of legacy ANDA/DMF checklist tables identified during
source inventory (docs/TEMPLATE_SOURCE_INVENTORY.md) -- no real client
templates are embedded here.
"""

import pytest


@pytest.fixture
def tenant_a(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")


@pytest.fixture
def tenant_b(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-a@example.com", password="TestPass1234!", full_name="User A"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-b@example.com", password="TestPass1234!", full_name="User B"
    )


@pytest.fixture
def reviewer_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="reviewer@example.com", password="TestPass1234!", full_name="Reviewer"
    )


@pytest.fixture
def vp_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="vp@example.com", password="TestPass1234!", full_name="VP"
    )


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
def tenant_admin_membership(db, tenant_a, user_b):
    return _membership_with_role(tenant_a, user_b, "tenant_admin")


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
def anda_like_rows():
    """Synthetic rows shaped like the legacy RATools.ANDAReportQuestions
    table (see docs/TEMPLATE_SOURCE_INVENTORY.md)."""
    return [
        {
            "id": 1,
            "report_name": "Solid Oral Dosage",
            "module_name": "3.2.P.2",
            "chapter_name": "Pharmaceutical Development",
            "category_name": "Formulation",
            "question": "<p>1. Describe the formulation development approach.</p>",
        },
        {
            "id": 2,
            "report_name": "Solid Oral Dosage",
            "module_name": "3.2.P.2",
            "chapter_name": "Pharmaceutical Development",
            "category_name": "Formulation",
            "question": "<p>2. Provide comparative dissolution data across strengths.</p>",
        },
    ]


@pytest.fixture
def dmf_like_rows():
    """Synthetic rows shaped like the legacy
    RATools.DMFReviewTableQuestion table, including the embedded-numbering
    pattern found during source inventory."""
    return [
        {
            "id": 1,
            "module": "3.2.S.1",
            "category": "General Information",
            "question": "<p>1. United States Adopted Name (USAN)</p>",
        },
        {
            "id": 2,
            "module": "3.2.S.1",
            "category": "General Information",
            "question": "<p>2. Chemical Name/IUPAC Name/ Compendial name (If Applicable)</p>",
        },
    ]


@pytest.fixture
def mojibake_row():
    """A single row carrying the exact mojibake artifact found in the
    legacy CCBestPractice.category column during source inventory."""
    return {
        "id": 99,
        "module": "General",
        "category": "DO�S",
        "question": "<p>Always confirm the RLD reference before submission.</p>",
    }


@pytest.fixture
def html_and_numbering_row():
    return {
        "id": 100,
        "module": "General",
        "category": "Formatting",
        "question": "<p>1.&nbsp;Subject of the DMF is a single API produced by one manufacturing process.<br />\r\nSecond line.</p>",
    }


@pytest.fixture
def duplicate_rows():
    """Two rows with identical question text -- exercises duplicate
    detection without being an actual data error (legitimate reuse across
    report types, per source inventory's VPReportQuestions finding)."""
    return [
        {
            "id": 201,
            "report_name": "VP - Solid Oral Report",
            "module_name": "General",
            "chapter_name": "General",
            "category_name": "General",
            "question": "<p>Evaluation of isomerism and polymorphism.</p>",
        },
        {
            "id": 202,
            "report_name": "VP - Topical Report",
            "module_name": "General",
            "chapter_name": "General",
            "category_name": "General",
            "question": "<p>Evaluation of isomerism and polymorphism.</p>",
        },
    ]


@pytest.fixture
def excluded_483_row():
    return {
        "id": 300,
        "report_name": "Form483 Export",
        "module_name": "Inspection",
        "chapter_name": "Observations",
        "category_name": "Observations",
        "question": "<p>483 observation regarding cleaning validation.</p>",
    }


@pytest.fixture
def excluded_aidatabase_row():
    return {
        "id": "AID-4471",
        "report_name": "AIDatabase export",
        "module_name": "General",
        "chapter_name": "General",
        "category_name": "General",
        "question": "<p>AIDatabase-sourced content must never enter REGX.</p>",
    }


@pytest.fixture
def missing_locator_row():
    return {
        "id": 400,
        "report_name": "Malformed",
        "module_name": "",
        "chapter_name": "",
        "category_name": "",
        "question": "<p>A row with no useful module/category context.</p>",
    }
