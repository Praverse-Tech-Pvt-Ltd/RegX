"""Fixtures for submission packages.

Synthetic data only. Section codes are generic -- A, A.1, B -- and encode no
CTD, CEP, DMF or ANDA structure: none ships in this milestone and none is
implied by a test. Nothing here is an agency format.

Document versions are built through the document platform's own models with
real bytes in the configured storage backend, because the whole milestone is
about exact bytes: a fixture that faked a checksum would let every
exact-version test pass while proving nothing.
"""

import hashlib
import io

import pytest
from rest_framework.test import APIClient

CASE_API = "/api/regx/v1/regulatory-cases"
PKG_API = "/api/regx/v1/submission-packages"


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from identity.models import User

    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


def _membership_with_roles(tenant, user, role_names):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    for role_name in role_names:
        role, _ = Role.objects.get_or_create(name=role_name, defaults={"description": role_name})
        MembershipRole.objects.create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def tenant_a(db):
    return _make_tenant("Package Tenant A", "pkg-tenant-a")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Package Tenant B", "pkg-tenant-b")


@pytest.fixture
def admin_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("pkg-admin-a@example.test", "Pkg Admin A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def admin_b(db, tenant_b):
    from authorization.models import Role

    user = _make_user("pkg-admin-b@example.test", "Pkg Admin B")
    _membership_with_roles(tenant_b, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """PLATFORM_SUPPORT: holds package view and NOT `documents.view`.

    The only built-in role with that shape, which makes it the honest way to
    test the document projection end to end.
    """
    from authorization.models import Role

    user = _make_user("pkg-support-a@example.test", "Pkg Support A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.PLATFORM_SUPPORT])
    return user


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_admin_b(admin_b, tenant_b):
    return _client(admin_b, tenant_b)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


# ---------------------------------------------------------------------------
# Domain builders
# ---------------------------------------------------------------------------
def make_case(tenant, actor, title="Synthetic case"):
    from regulatory_cases import services as cases

    return cases.create_case(tenant=tenant, actor=actor, title=title)


def make_document(tenant, actor, title="Synthetic document"):
    from documents.models import Document

    return Document.objects.create(
        tenant=tenant, title=title, document_type="other", created_by=actor
    )


def make_version(document, actor, *, content: bytes, version_number=1, clean=True, filename=None):
    """A real stored object with a real checksum.

    The bytes go into the configured storage backend and the checksum is
    computed from them, so an export that streams and re-hashes is exercising
    the real path rather than agreeing with a fixture.
    """
    from documents.models import DocumentVersion, ProcessingStatus, ScanStatus
    from documents.storage import get_storage_backend

    checksum = hashlib.sha256(content).hexdigest()
    backend = get_storage_backend()
    storage_key = backend.store(
        tenant_id=document.tenant_id,
        file_obj=io.BytesIO(content),
        expected_sha256=checksum,
        content_type="application/pdf",
        original_filename=filename or f"synthetic-v{version_number}.pdf",
    )
    version = DocumentVersion.objects.create(
        document=document,
        version_number=version_number,
        original_filename=filename or f"synthetic-v{version_number}.pdf",
        normalized_filename=filename or f"synthetic-v{version_number}.pdf",
        extension="pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        size_bytes=len(content),
        sha256_checksum=checksum,
        storage_key=storage_key,
        scan_status=ScanStatus.CLEAN if clean else ScanStatus.QUARANTINED,
        processing_status=ProcessingStatus.COMPLETE,
        uploaded_by=actor,
    )
    document.current_version = version
    document.save(update_fields=["current_version"])
    return version


def make_package(case, tenant, actor, name="Synthetic package"):
    from submission_packages import services

    return services.create_package(
        case_public_id=case.public_id, tenant=tenant, actor=actor, name=name
    )


def add_entry(package, tenant, actor, version, **kw):
    from submission_packages import services

    return services.add_entry(
        package=package,
        tenant=tenant,
        actor=actor,
        document_version_public_id=version.public_id,
        **kw,
    )


def freeze(package, tenant, actor):
    """Submit for review, then freeze -- the only route the state machine allows.

    Freezing is permanent, so it is deliberately a second act. A helper that hid
    that would let a test pass against a service that had quietly stopped
    requiring review.
    """
    from submission_packages import services
    from submission_packages.models import PackageStatus

    if package.status == PackageStatus.DRAFT:
        package = services.submit_for_review(package=package, tenant=tenant, actor=actor)
    return services.freeze_package(package=package, tenant=tenant, actor=actor)
