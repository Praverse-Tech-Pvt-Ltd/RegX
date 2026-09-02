"""Fixtures for external integrations.

Synthetic data only, and **no real external service is ever contacted**. The
remote endpoint is a `perform_request` double: transport is exercised directly
by its own tests, and everything above it is tested against a recorded call so a
test never depends on the internet being reachable or on somebody's staging
server behaving.

No production credential appears anywhere. Where a secret is needed, it is a
synthetic value put into the environment by a fixture and removed afterwards.

**Celery is eager under test.** `run_connector_execution.delay(...)` therefore
runs *inside* the POST that queues it. A test that sets up a condition after
the queueing request is describing an execution that has already finished, so
anything meant to be true before the worker starts has to be arranged first --
or the execution has to be created through the service, which does not
dispatch.
"""

import io
from dataclasses import dataclass, field

import pytest
from rest_framework.test import APIClient

INTEGRATIONS_API = "/api/regx/v1/external-integrations"
EXECUTIONS_API = "/api/regx/v1/external-integration-executions"
PKG_API = "/api/regx/v1/submission-packages"

#: A minimal, real PDF. The document platform sniffs content, so a fixture that
#: sent `b"hello"` labelled as a PDF would be testing the rejection path by
#: accident.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

BASE_CONFIG = {
    "base_url": "https://connector.test/",
    "allowed_path_prefix": "/regx/",
    "health_path": "health",
    "connect_timeout_seconds": 5,
    "read_timeout_seconds": 30,
    "verify_tls": True,
}


# ---------------------------------------------------------------------------
# Tenancy, users, clients
# ---------------------------------------------------------------------------
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
    return _make_tenant("Integration Tenant A", "int-tenant-a")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Integration Tenant B", "int-tenant-b")


@pytest.fixture
def admin_a(db, tenant_a):
    from authorization.models import Role

    user = _make_user("int-admin-a@example.test", "Int Admin A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def admin_b(db, tenant_b):
    from authorization.models import Role

    user = _make_user("int-admin-b@example.test", "Int Admin B")
    _membership_with_roles(tenant_b, user, [Role.BuiltIn.TENANT_ADMIN])
    return user


@pytest.fixture
def doer_a(db, tenant_a):
    """Can run a connector and create documents; cannot configure a connector.

    The role that shows connector permission and configuration permission are
    different things.
    """
    from authorization.models import Role

    user = _make_user("int-doer-a@example.test", "Int Doer A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.DOER])
    return user


@pytest.fixture
def support_a(db, tenant_a):
    """PLATFORM_SUPPORT: can see connectors, holds no `documents.view`."""
    from authorization.models import Role

    user = _make_user("int-support-a@example.test", "Int Support A")
    _membership_with_roles(tenant_a, user, [Role.BuiltIn.PLATFORM_SUPPORT])
    return user


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_admin_b(admin_b, tenant_b):
    return _client(admin_b, tenant_b)


@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------
def make_connector(tenant, actor, *, name="Test connector", config=None, credential=True):
    from external_integrations import services

    return services.create_connector(
        tenant=tenant,
        actor=actor,
        name=name,
        connector_type="generic_https",
        configuration={**BASE_CONFIG, **(config or {})},
        credential={"credential_type": "bearer_token"} if credential else None,
    )


def enable(connector, tenant, actor):
    from external_integrations import services
    from external_integrations.models import ConnectorStatus

    return services.set_connector_status(
        connector=connector, tenant=tenant, actor=actor, status=ConnectorStatus.ACTIVE
    )


@pytest.fixture
def active_connector(tenant_a, admin_a):
    connector = make_connector(tenant_a, admin_a)
    return enable(connector, tenant_a, admin_a)


@pytest.fixture
def connector_secret(active_connector, monkeypatch):
    """A synthetic secret in the environment, for the duration of one test."""
    from external_integrations.secrets import environment_variable_name

    reference = active_connector.credential_reference
    name = environment_variable_name(active_connector, reference)
    monkeypatch.setenv(name, "synthetic-token-value-not-a-real-credential")
    return name


# ---------------------------------------------------------------------------
# The remote endpoint double
# ---------------------------------------------------------------------------
@dataclass
class RecordedCall:
    method: str
    url: str
    headers: dict
    body_length: int | None


@dataclass
class FakeRemote:
    """Stands in for `transport.perform_request`.

    Records what would have gone out -- which is what the secret-leak and
    exact-snapshot tests inspect -- and returns a canned reply. It deliberately
    does **not** stand in for `netpolicy`: destination policy is tested against
    the real functions, because a double that always said "fine" would make
    every SSRF test vacuous.
    """

    status: int = 200
    body: bytes = b""
    external_reference: str = "remote-object-1"
    remote_checksum: str = ""
    raises: Exception | None = None
    calls: list = field(default_factory=list)

    def __call__(self, **kwargs):
        from external_integrations.transport import Response

        sink = kwargs.get("sink")
        self.calls.append(
            RecordedCall(
                method=kwargs.get("method", ""),
                url=kwargs.get("url", ""),
                headers=dict(kwargs.get("headers") or {}),
                body_length=kwargs.get("body_length"),
            )
        )
        if self.raises is not None:
            raise self.raises
        if sink is not None and self.body:
            sink.write(self.body)
        return Response(
            status=self.status,
            body=b"" if sink is not None else self.body,
            latency_ms=12,
            external_reference=self.external_reference,
            remote_checksum=self.remote_checksum,
        )


@pytest.fixture
def fake_remote(monkeypatch):
    """Install the double everywhere the code reaches for the transport."""
    remote = FakeRemote()
    monkeypatch.setattr("external_integrations.transport.perform_request", remote)
    monkeypatch.setattr("external_integrations.operations.perform_request", remote)
    return remote


# ---------------------------------------------------------------------------
# Documents and packages, for the two operations
# ---------------------------------------------------------------------------
def make_document_version(tenant, actor, *, content=PDF_BYTES, filename="cited.pdf"):
    """A real stored object with a real checksum, through the document models."""
    import hashlib

    from documents.models import Document, DocumentVersion, ProcessingStatus, ScanStatus
    from documents.storage import get_storage_backend

    document = Document.objects.create(
        tenant=tenant, title="Synthetic document", document_type="pdf", created_by=actor
    )
    checksum = hashlib.sha256(content).hexdigest()
    storage_key = get_storage_backend().store(
        tenant_id=tenant.pk,
        file_obj=io.BytesIO(content),
        expected_sha256=checksum,
        content_type="application/pdf",
        original_filename=filename,
    )
    version = DocumentVersion.objects.create(
        document=document,
        version_number=1,
        original_filename=filename,
        normalized_filename=filename,
        extension="pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        size_bytes=len(content),
        sha256_checksum=checksum,
        storage_key=storage_key,
        scan_status=ScanStatus.CLEAN,
        processing_status=ProcessingStatus.COMPLETE,
        uploaded_by=actor,
    )
    document.current_version = version
    document.save(update_fields=["current_version"])
    return version


def make_frozen_package(tenant, actor, *, name="Transfer package"):
    """A Milestone 13 frozen package with one exact version in it."""
    from regulatory_cases import services as case_services
    from submission_packages import services as package_services

    case = case_services.create_case(tenant=tenant, actor=actor, title="Integration case")
    version = make_document_version(tenant, actor)
    package = package_services.create_package(
        case_public_id=case.public_id, tenant=tenant, actor=actor, name=name
    )
    package_services.add_entry(
        package=package,
        tenant=tenant,
        actor=actor,
        document_version_public_id=version.public_id,
        logical_path="01-cover",
    )
    package = package_services.submit_for_review(package=package, tenant=tenant, actor=actor)
    return package_services.freeze_package(package=package, tenant=tenant, actor=actor)
