"""Fixtures for the regulatory cases domain. Synthetic data only.

Mirrors `workflows/tests/conftest.py` so the two suites read the same way.
Distinct tenant slugs, because both suites can run in the same session.
"""

import pytest
from rest_framework.test import APIClient

from authorization.models import Role


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=full_name
    )


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(tenant=None, name=role_name, defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


# --- tenants ---------------------------------------------------------------
@pytest.fixture
def tenant_a(db):
    return _make_tenant("Dossier Tenant Alpha", "sd-tenant-alpha")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Dossier Tenant Beta", "sd-tenant-beta")


# --- users -----------------------------------------------------------------
@pytest.fixture
def doer_a(db, tenant_a):
    user = _make_user("sd-doer-a@example.com", "Dossier Doer A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def vp_a(db, tenant_a):
    """Holds complete AND cancel; DOER holds neither."""
    user = _make_user("sd-vp-a@example.com", "Dossier VP A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.VP)
    return user


@pytest.fixture
def admin_a(db, tenant_a):
    user = _make_user("sd-admin-a@example.com", "Dossier Admin A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.TENANT_ADMIN)
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """PLATFORM_SUPPORT: holds regulatory_cases.view and NO document,
    workflow or checklist permission anywhere. This is the live configuration
    the projection tests drive."""
    user = _make_user("sd-support-a@example.com", "Dossier Support A")
    _membership_with_role(tenant_a, user, Role.BuiltIn.PLATFORM_SUPPORT)
    return user


@pytest.fixture
def doer_b(db, tenant_b):
    user = _make_user("sd-doer-b@example.com", "Dossier Doer B")
    _membership_with_role(tenant_b, user, Role.BuiltIn.DOER)
    return user


@pytest.fixture
def outsider(db):
    """Authenticated but a member of no tenant."""
    return _make_user("sd-outsider@example.com", "Dossier Outsider")


# --- clients ---------------------------------------------------------------
@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_vp_a(vp_a, tenant_a):
    return _client(vp_a, tenant_a)


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


@pytest.fixture
def client_doer_b(doer_b, tenant_b):
    return _client(doer_b, tenant_b)


# --- domain objects --------------------------------------------------------
CASE_FIELDS = {
    "title": "Stability data package",
    "product_name": "Synthetic Product X",
    "market": "Synthetic Market",
    "submission_type": "Synthetic Submission Type",
}


@pytest.fixture
def case_a(db, tenant_a, doer_a):
    from regulatory_cases import services

    return services.create_case(tenant=tenant_a, actor=doer_a, **CASE_FIELDS)


@pytest.fixture
def case_b(db, tenant_b, doer_b):
    from regulatory_cases import services

    return services.create_case(tenant=tenant_b, actor=doer_b, **CASE_FIELDS)


@pytest.fixture
def workflow_a(db, tenant_a, doer_a):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(
        tenant=tenant_a, title="Synthetic workflow A", created_by=doer_a
    )


@pytest.fixture
def workflow_b(db, tenant_b, doer_b):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.create(
        tenant=tenant_b, title="Synthetic workflow B", created_by=doer_b
    )


def _make_document(tenant, title="Synthetic document"):
    from documents.models import Document

    return Document.objects.create(tenant=tenant, title=title, document_type="other")


@pytest.fixture
def document_a(db, tenant_a):
    return _make_document(tenant_a, "Tenant A document")


@pytest.fixture
def document_b(db, tenant_b):
    return _make_document(tenant_b, "Tenant B document")


def _checklist_execution(tenant, user):
    """A minimal real ChecklistExecution.

    Built rather than stubbed: the checklist auth-separation test must exercise
    the same projection path the API uses, and a stub would prove only that the
    stub behaves.
    """
    import uuid as _uuid
    from decimal import Decimal

    from formulations.models import FormulationVersion, ProductDevelopmentRecord
    from iig_checklist.models import (
        ChecklistDefinition,
        ChecklistExecution,
        ChecklistVersion,
    )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=f"RC-PROD-{_uuid.uuid4().hex[:10]}",
        proposed_product_name="Synthetic Product",
        active_ingredient="Synthetic Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )
    formulation = FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal("1.000000"),
        total_dosage_unit_weight_unit="gram",
        created_by=user,
    )
    definition = ChecklistDefinition.objects.create(
        code=f"RC-CHK-{_uuid.uuid4().hex[:10]}",
        title="Synthetic checklist",
        scope_type="tenant",
        execution_scope="formulation_version",
        tenant=tenant,
        created_by=user,
    )
    version = ChecklistVersion.objects.create(
        definition=definition, version_number=1, status="active", created_by=user
    )
    return ChecklistExecution.objects.create(
        tenant=tenant,
        checklist_version=version,
        formulation_version=formulation,
        status="draft",
        created_by=user,
    )


@pytest.fixture
def checklist_a(db, tenant_a, doer_a):
    return _checklist_execution(tenant_a, doer_a)


@pytest.fixture
def checklist_b(db, tenant_b, doer_b):
    return _checklist_execution(tenant_b, doer_b)


# --- dossier fixtures ------------------------------------------------------
DOSSIER_FIELDS = {"title": "Initial submission package"}


@pytest.fixture
def dossier_a(db, case_a, tenant_a, doer_a):
    from submission_dossiers import services

    return services.create_dossier(case=case_a, tenant=tenant_a, actor=doer_a, **DOSSIER_FIELDS)


@pytest.fixture
def dossier_b(db, case_b, tenant_b, doer_b):
    from submission_dossiers import services

    return services.create_dossier(case=case_b, tenant=tenant_b, actor=doer_b, **DOSSIER_FIELDS)


def make_section(dossier, tenant, actor, code, *, parent=None, required=True, **kw):
    from submission_dossiers import services

    return services.create_section(
        dossier=dossier,
        tenant=tenant,
        actor=actor,
        parent=parent,
        section_code=code,
        title=f"Section {code}",
        required=required,
        **kw,
    )


@pytest.fixture
def section_a(db, dossier_a, tenant_a, doer_a):
    return make_section(dossier_a, tenant_a, doer_a, "1")


@pytest.fixture
def section_b(db, dossier_b, tenant_b, doer_b):
    return make_section(dossier_b, tenant_b, doer_b, "1")
