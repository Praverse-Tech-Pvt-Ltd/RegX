"""Second-layer coverage, and the migration counts.

Written after a mutation sweep: every guard here already had exactly one test,
which is thin for things this permanent. A guard proven only at the service
layer is a guard nobody has checked is actually wired to the API, and the two
can drift.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import io
import zipfile

import pytest

from submission_packages import services
from submission_packages.models import PackageStatus, SubmissionPackage
from submission_packages.tests.conftest import (
    PKG_API,
    add_entry,
    freeze,
    make_case,
    make_document,
    make_package,
    make_version,
)

CASE_API = "/api/regx/v1/regulatory-cases"
V1 = b"%PDF-1.4 first"
V2 = b"%PDF-1.4 second, entirely different"


# ---------------------------------------------------------------------------
# The exact-version guarantee, through the API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExactVersionThroughTheApi:
    def test_the_exported_archive_holds_the_cited_version_after_an_upload(
        self, client_admin_a, tenant_a, admin_a
    ):
        """The service-level test proved the bytes; this proves the endpoint
        serves them. Without the upload of v2 the two versions are the same
        object, and the test cannot tell a correct export from one that follows
        `document.current_version`."""
        case = make_case(tenant_a, admin_a)
        document = make_document(tenant_a, admin_a)
        v1 = make_version(document, admin_a, content=V1, version_number=1, filename="f.pdf")
        package = make_package(case, tenant_a, admin_a)
        add_entry(package, tenant_a, admin_a, v1, logical_path="01")
        package = freeze(package, tenant_a, admin_a)

        v2 = make_version(document, admin_a, content=V2, version_number=2, filename="f.pdf")
        document.refresh_from_db()
        assert document.current_version_id == v2.pk, "precondition: the document moved on"

        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/export/")
        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        assert archive.read("files/01/f.pdf") == V1
        assert archive.read("files/01/f.pdf") != V2

    def test_the_detail_endpoint_reports_the_cited_version_number(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        document = make_document(tenant_a, admin_a)
        v1 = make_version(document, admin_a, content=V1, version_number=1)
        package = make_package(case, tenant_a, admin_a)
        add_entry(package, tenant_a, admin_a, v1)

        make_version(document, admin_a, content=V2, version_number=2)

        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/")
        document_block = response.data["entries"][0]["document"]
        assert document_block["version_number"] == 1
        assert document_block["checksum_sha256"] == v1.sha256_checksum


# ---------------------------------------------------------------------------
# Tenant isolation, across every mutating service
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantGateBreadth:
    @pytest.fixture
    def b_package_and_entry(self, tenant_b, admin_b):
        case = make_case(tenant_b, admin_b)
        version = make_version(
            make_document(tenant_b, admin_b), admin_b, content=b"b", version_number=1
        )
        package = make_package(case, tenant_b, admin_b, name="B package")
        entry = add_entry(package, tenant_b, admin_b, version)
        return package, entry

    def test_every_package_service_refuses_a_foreign_package(
        self, tenant_a, admin_a, b_package_and_entry
    ):
        package, _ = b_package_and_entry
        for call in (
            services.submit_for_review,
            services.return_to_draft,
            services.cancel_package,
            services.freeze_package,
            services.clone_package,
        ):
            with pytest.raises(services.InvalidTarget):
                call(package=package, tenant=tenant_a, actor=admin_a)

        with pytest.raises(services.InvalidTarget):
            services.update_package(package=package, tenant=tenant_a, actor=admin_a, name="stolen")
        with pytest.raises(services.InvalidTarget):
            services.validate_package(package=package, tenant=tenant_a)

    def test_every_entry_service_refuses_a_foreign_entry(
        self, tenant_a, admin_a, b_package_and_entry
    ):
        package, entry = b_package_and_entry
        with pytest.raises(services.InvalidTarget):
            services.remove_entry(entry=entry, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.InvalidTarget):
            services.reorder_entry(entry=entry, tenant=tenant_a, actor=admin_a, sequence=3)

        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        with pytest.raises(services.InvalidTarget):
            add_entry(package, tenant_a, admin_a, version)

    def test_a_foreign_package_is_404_at_every_endpoint(self, client_admin_a, b_package_and_entry):
        package, entry = b_package_and_entry
        base = f"{PKG_API}/{package.public_id}"
        for url in (
            f"{base}/",
            f"{base}/validate/",
            f"{base}/manifest/",
            f"{base}/export/",
        ):
            assert client_admin_a.get(url).status_code == 404, url
        for url in (
            f"{base}/submit-for-review/",
            f"{base}/freeze/",
            f"{base}/cancel/",
            f"{base}/clone/",
            f"{base}/entries/",
            f"{base}/entries/{entry.public_id}/remove/",
        ):
            assert client_admin_a.post(url, {}, format="json").status_code == 404, url

    def test_a_foreign_case_package_list_is_404(self, client_admin_a, tenant_b, admin_b):
        case = make_case(tenant_b, admin_b, title="B case")
        response = client_admin_a.get(f"{CASE_API}/{case.public_id}/packages/")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Document permission, through the API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDocumentGateThroughTheApi:
    def test_adding_an_entry_is_refused_without_document_permission(
        self, client_support_a, support_a, tenant_a, admin_a
    ):
        from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
        from documents.permissions import has_document_permission
        from submission_packages.permissions import has_package_permission

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )

        assert not has_document_permission(support_a, tenant_a, DOCUMENTS_VIEW)
        response = client_support_a.post(
            f"{PKG_API}/{package.public_id}/entries/",
            {"document_version_public_id": str(version.public_id)},
            format="json",
        )
        # Either gate may answer first; what matters is that nothing is added.
        assert response.status_code in (400, 403)
        assert services.active_entries(package).count() == 0
        assert has_package_permission is not None


# ---------------------------------------------------------------------------
# Validate endpoint
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidateEndpoint:
    def test_a_clean_package_validates(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)

        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/validate/")
        assert response.status_code == 200
        assert response.data["valid"] is True
        assert response.data["issues"] == []
        assert response.data["semantics"] == "internal_package_integrity"

    def test_an_empty_package_reports_the_reason_as_a_code(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/validate/")
        assert response.data["valid"] is False
        assert response.data["issues"][0]["code"] == "no_active_entries"

    def test_the_endpoint_is_not_named_after_a_regulatory_activity(self):
        """`validate` here means "can this be exported", not "is this
        acceptable to anyone"."""
        from submission_packages import urls

        names = [getattr(p, "name", "") for p in urls.urlpatterns]
        patterns = [str(p.pattern) for p in urls.urlpatterns]
        for banned in ("regulatory-validate", "submission-validate", "compliance"):
            assert not any(banned in n for n in names)
            assert not any(banned in p for p in patterns)


# ---------------------------------------------------------------------------
# Manifest endpoint
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestManifestEndpoint:
    def test_an_unfrozen_package_has_no_manifest(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        assert client_admin_a.get(f"{PKG_API}/{package.public_id}/manifest/").status_code == 404

    def test_the_manifest_endpoint_returns_the_stored_snapshot(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)
        package = freeze(package, tenant_a, admin_a)

        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/manifest/")
        assert response.status_code == 200
        assert response.data["manifest_checksum"] == package.manifest_checksum
        assert response.data["manifest"] == package.snapshot.manifest
        assert response.data["entry_count"] == 1


# ---------------------------------------------------------------------------
# Audit discipline
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuditDiscipline:
    def test_no_free_text_reaches_an_audit_row(self, tenant_a, admin_a):
        """A package name, a document title and a filename all describe what a
        tenant is preparing to submit, and an audit row has different retention
        from the package it describes."""
        from audit.models import AuditEvent

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a, name="Confidential Programme Alpha")
        version = make_version(
            make_document(tenant_a, admin_a, title="Secret Study Report"),
            admin_a,
            content=b"a",
            version_number=1,
            filename="secret-study.pdf",
        )
        add_entry(package, tenant_a, admin_a, version)
        freeze(package, tenant_a, admin_a)

        rows = AuditEvent.objects.filter(resource_type="submission_package")
        assert rows.exists()
        blob = str([r.payload for r in rows])
        for secret in ("Confidential Programme Alpha", "Secret Study Report", "secret-study.pdf"):
            assert secret not in blob

    def test_the_freeze_event_carries_the_checksum(self, tenant_a, admin_a):
        from audit.models import AuditEvent

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)
        package = freeze(package, tenant_a, admin_a)

        event = AuditEvent.objects.filter(
            event_type="submission_package.frozen", resource_id=str(package.public_id)
        ).first()
        assert event.payload["manifest_checksum"] == package.manifest_checksum
        assert event.payload["entry_count"] == 1


# ---------------------------------------------------------------------------
# Migration symmetry
# ---------------------------------------------------------------------------
class TestMigrationSymmetry:
    """Docstring counts drift silently; SQL does not.

    Milestone 10 shipped a docstring claiming five functions and eight triggers
    where the SQL had seven of each, and Milestone 11 claimed a symmetry test
    covered its counts when the test lived in another app entirely. This one
    ships with the migration it describes.
    """

    CASES = [("0002_package_db_governance", 7, 7)]

    def _module(self, name):
        import importlib

        return importlib.import_module(f"submission_packages.migrations.{name}")

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_create_and_drop_are_symmetric(self, name, functions, triggers):
        m = self._module(name)
        assert m.CREATE_SQL.count("CREATE OR REPLACE FUNCTION") == functions
        assert m.CREATE_SQL.count("CREATE TRIGGER") == triggers
        assert m.DROP_SQL.count("DROP FUNCTION") == functions
        assert m.DROP_SQL.count("DROP TRIGGER") == triggers

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_the_docstring_states_the_real_counts(self, name, functions, triggers):
        m = self._module(name)
        doc = " ".join((m.__doc__ or "").split())
        assert f"{functions} plpgsql functions" in doc, doc[:300]
        assert f"{triggers} triggers" in doc, doc[:300]

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_every_created_trigger_is_dropped_by_name(self, name, functions, triggers):
        m = self._module(name)
        created = {
            line.split()[2]
            for line in m.CREATE_SQL.splitlines()
            if line.startswith("CREATE TRIGGER")
        }
        dropped = {
            line.split()[4] for line in m.DROP_SQL.splitlines() if line.startswith("DROP TRIGGER")
        }
        assert created == dropped, f"{name}: created {created}, dropped {dropped}"

    def test_the_initial_migration_declares_its_rollback_class(self):
        m = self._module("0001_initial")
        doc = " ".join((m.__doc__ or "").split())
        assert "CLASS C -- DATA RESTORE REQUIRED" in doc
        assert "frozen manifest" in doc

    def test_the_governance_migration_does_not_claim_to_verify_the_hash(self):
        """It checks the checksum's shape and the entry count. Claiming it
        verifies SHA-256 over the JSON would be claiming a guarantee that is not
        there."""
        m = self._module("0002_package_db_governance")
        doc = " ".join((m.__doc__ or "").split())
        assert "does **not** recompute SHA-256" in doc or "not** recompute SHA-256" in doc
        assert "would be claiming a guarantee that is not there" in doc


# ---------------------------------------------------------------------------
# State machine, asserted against the database rather than the service
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStateMachineAtTheDatabase:
    @pytest.mark.parametrize(
        "start,target",
        [
            (PackageStatus.DRAFT, PackageStatus.FROZEN),
            (PackageStatus.FROZEN, PackageStatus.DRAFT),
            (PackageStatus.CANCELLED, PackageStatus.DRAFT),
        ],
    )
    def test_forbidden_transitions_are_refused_below_the_service(
        self, tenant_a, admin_a, start, target
    ):
        from django.db import ProgrammingError, transaction
        from django.db.utils import InternalError

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)

        if start == PackageStatus.FROZEN:
            package = freeze(package, tenant_a, admin_a)
        elif start == PackageStatus.CANCELLED:
            package = services.cancel_package(package=package, tenant=tenant_a, actor=admin_a)

        with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
            SubmissionPackage.governed.filter(pk=package.pk).update(status=target)
