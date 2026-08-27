"""The whole lifecycle over HTTP, plus the branches the service tests skip.

Written after a coverage pass showed the endpoints at 69%: every lifecycle
transition was proved at the service layer and several were never called through
a URL. A service that works and a route that is wired to it are two different
facts, and only one of them was being checked.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import pytest

from submission_packages import services
from submission_packages.integrity import IntegrityIssue, check_package
from submission_packages.paths import MAX_SEGMENT_LENGTH, sanitize_export_filename
from submission_packages.tests.conftest import (
    PKG_API,
    make_case,
    make_document,
    make_version,
)

CASE_API = "/api/regx/v1/regulatory-cases"


@pytest.mark.django_db
class TestApiLifecycle:
    def test_a_package_can_be_built_reviewed_frozen_and_cloned_over_http(
        self, client_admin_a, tenant_a, admin_a
    ):
        """One round trip through every endpoint the UI actually calls."""
        case = make_case(tenant_a, admin_a)
        v1 = make_version(
            make_document(tenant_a, admin_a, title="First"),
            admin_a,
            content=b"first payload",
            version_number=1,
            filename="first.pdf",
        )
        v2 = make_version(
            make_document(tenant_a, admin_a, title="Second"),
            admin_a,
            content=b"second payload",
            version_number=1,
            filename="second.pdf",
        )

        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/",
            {"name": "Round trip", "description": "Synthetic"},
            format="json",
        )
        assert created.status_code == 201, created.data
        pkg_id = created.data["public_id"]
        assert created.data["status"] == "draft"
        assert created.data["revision_number"] == 1

        listed = client_admin_a.get(f"{CASE_API}/{case.public_id}/packages/")
        assert listed.status_code == 200
        assert listed.data["count"] == 1
        assert listed.data["results"][0]["entry_count"] == 0

        renamed = client_admin_a.patch(
            f"{PKG_API}/{pkg_id}/", {"name": "Round trip renamed"}, format="json"
        )
        assert renamed.status_code == 200
        assert renamed.data["name"] == "Round trip renamed"

        for version, path in ((v1, "01-cover"), (v2, "02-supporting")):
            added = client_admin_a.post(
                f"{PKG_API}/{pkg_id}/entries/",
                {
                    "document_version_public_id": str(version.public_id),
                    "logical_path": path,
                },
                format="json",
            )
            assert added.status_code == 201, added.data
            assert added.data["document"]["version_number"] == 1

        detail = client_admin_a.get(f"{PKG_API}/{pkg_id}/")
        assert detail.data["entry_count"] == 2
        first_entry, second_entry = detail.data["entries"]

        reordered = client_admin_a.post(
            f"{PKG_API}/{pkg_id}/entries/{second_entry['public_id']}/reorder/",
            {"sequence": 0},
            format="json",
        )
        assert reordered.status_code == 200
        assert reordered.data["sequence"] == 0

        removed = client_admin_a.post(
            f"{PKG_API}/{pkg_id}/entries/{first_entry['public_id']}/remove/", {}, format="json"
        )
        assert removed.status_code == 200
        assert removed.data["is_active"] is False

        submitted = client_admin_a.post(f"{PKG_API}/{pkg_id}/submit-for-review/", {}, format="json")
        assert submitted.data["status"] == "in_review"

        returned = client_admin_a.post(f"{PKG_API}/{pkg_id}/return-to-draft/", {}, format="json")
        assert returned.data["status"] == "draft"

        client_admin_a.post(f"{PKG_API}/{pkg_id}/submit-for-review/", {}, format="json")
        frozen = client_admin_a.post(f"{PKG_API}/{pkg_id}/freeze/", {}, format="json")
        assert frozen.status_code == 200, frozen.data
        assert frozen.data["status"] == "frozen"
        assert len(frozen.data["manifest_checksum"]) == 64

        manifest = client_admin_a.get(f"{PKG_API}/{pkg_id}/manifest/")
        assert manifest.status_code == 200
        assert manifest.data["entry_count"] == 1
        assert manifest.data["manifest"]["semantics"] == "internal_package_manifest"

        cloned = client_admin_a.post(f"{PKG_API}/{pkg_id}/clone/", {}, format="json")
        assert cloned.status_code == 201
        assert cloned.data["status"] == "draft"
        assert cloned.data["revision_number"] == 2
        assert cloned.data["source_package_public_id"] == pkg_id

        # The original is untouched by any of that.
        after = client_admin_a.get(f"{PKG_API}/{pkg_id}/")
        assert after.data["status"] == "frozen"
        assert after.data["manifest_checksum"] == frozen.data["manifest_checksum"]

    def test_a_cancelled_package_is_reported_over_http(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "To cancel"}, format="json"
        )
        pkg_id = created.data["public_id"]
        cancelled = client_admin_a.post(f"{PKG_API}/{pkg_id}/cancel/", {}, format="json")
        assert cancelled.data["status"] == "cancelled"
        assert cancelled.data["cancelled_at"] is not None

    def test_the_detail_response_carries_an_advisory_permissions_block(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "Perms"}, format="json"
        )
        detail = client_admin_a.get(f"{PKG_API}/{created.data['public_id']}/")
        perms = detail.data["permissions"]
        assert set(perms) == {
            "can_view",
            "can_create",
            "can_edit",
            "can_manage_entries",
            "can_review",
            "can_freeze",
            "can_cancel",
            "can_export",
        }

    def test_a_freeze_refusal_returns_the_enumerated_issues(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "Empty"}, format="json"
        )
        pkg_id = created.data["public_id"]
        client_admin_a.post(f"{PKG_API}/{pkg_id}/submit-for-review/", {}, format="json")

        refused = client_admin_a.post(f"{PKG_API}/{pkg_id}/freeze/", {}, format="json")
        assert refused.status_code == 409
        assert refused.data["issues"][0]["code"] == IntegrityIssue.NO_ACTIVE_ENTRIES

    def test_a_bad_logical_path_is_refused_with_a_code(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "Paths"}, format="json"
        )
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        refused = client_admin_a.post(
            f"{PKG_API}/{created.data['public_id']}/entries/",
            {
                "document_version_public_id": str(version.public_id),
                "logical_path": "../escape",
            },
            format="json",
        )
        assert refused.status_code == 409
        assert refused.data["issues"][0]["code"] == "path_traversal"
        # The rejected path is never echoed back: that is how a traversal
        # attempt becomes a log-injection or an XSS.
        assert "escape" not in str(refused.data["issues"])

    def test_a_patch_with_no_changes_is_rejected(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        created = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "Nothing"}, format="json"
        )
        response = client_admin_a.patch(
            f"{PKG_API}/{created.data['public_id']}/", {}, format="json"
        )
        assert response.status_code == 400

    def test_a_terminal_case_accepts_no_new_package(self, client_admin_a, tenant_a, admin_a):
        from regulatory_cases import services as cases

        case = make_case(tenant_a, admin_a)
        cases.complete_case(case=case, tenant=tenant_a, actor=admin_a)
        response = client_admin_a.post(
            f"{CASE_API}/{case.public_id}/packages/", {"name": "Too late"}, format="json"
        )
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------
class TestExportFilename:
    """Unsafe characters are replaced rather than refused: a package must not
    become un-exportable over a character in a filename somebody uploaded a year
    ago."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("report.pdf", "report.pdf"),
            ("a/b/report.pdf", "report.pdf"),
            ("a\\b\\report.pdf", "report.pdf"),
            ("we;ird|name?.pdf", "we_ird_name_.pdf"),
            ("trailing. ", "trailing"),
        ],
    )
    def test_names_are_made_safe(self, raw, expected):
        assert sanitize_export_filename(raw, fallback="f.bin") == expected

    def test_an_empty_name_falls_back(self):
        assert sanitize_export_filename("", fallback="f.bin") == "f.bin"
        assert sanitize_export_filename("   ", fallback="f.bin") == "f.bin"
        assert sanitize_export_filename("///", fallback="f.bin") == "f.bin"

    def test_a_reserved_device_name_is_prefixed_not_refused(self):
        assert sanitize_export_filename("CON.pdf", fallback="f.bin") == "_CON.pdf"
        assert sanitize_export_filename("nul", fallback="f.bin") == "_nul"

    def test_a_long_name_is_truncated_but_keeps_its_extension(self):
        raw = "x" * 400 + ".pdf"
        out = sanitize_export_filename(raw, fallback="f.bin")
        assert len(out) <= MAX_SEGMENT_LENGTH
        assert out.endswith(".pdf")

    def test_a_long_extensionless_name_is_simply_truncated(self):
        out = sanitize_export_filename("y" * 400, fallback="f.bin")
        assert len(out) == MAX_SEGMENT_LENGTH

    def test_control_characters_are_stripped(self):
        assert "\x01" not in sanitize_export_filename("a\x01b.pdf", fallback="f.bin")


# ---------------------------------------------------------------------------
# Integrity branches the happy path never reaches
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestIntegrityBranches:
    def test_a_missing_checksum_is_reported(self, tenant_a, admin_a):
        from documents.models import DocumentVersion
        from submission_packages.tests.conftest import add_entry, make_package

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)
        DocumentVersion.objects.filter(pk=version.pk).update(sha256_checksum="")

        issues = check_package(package=package, entries=list(services.active_entries(package)))
        assert IntegrityIssue.CHECKSUM_MISSING in [i["code"] for i in issues]

    def test_a_retired_section_is_reported(self, tenant_a, admin_a):
        from submission_dossiers import services as ds
        from submission_packages.tests.conftest import add_entry, make_package

        case = make_case(tenant_a, admin_a)
        dossier = ds.create_dossier(
            case=case, tenant=tenant_a, actor=admin_a, title="Synthetic dossier"
        )
        section = ds.create_section(
            dossier=dossier, tenant=tenant_a, actor=admin_a, section_code="A", title="A"
        )
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(
            package,
            tenant_a,
            admin_a,
            version,
            dossier_section_public_id=section.public_id,
        )

        ds.retire_section(section=section, tenant=tenant_a, actor=admin_a)
        issues = check_package(package=package, entries=list(services.active_entries(package)))
        assert IntegrityIssue.SECTION_RETIRED in [i["code"] for i in issues]

    def test_the_entry_limit_is_reported(self, tenant_a, admin_a, settings):
        from submission_packages.tests.conftest import add_entry, make_package

        settings.SUBMISSION_PACKAGE_MAX_ENTRIES = 1
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        for i in range(2):
            version = make_version(
                make_document(tenant_a, admin_a, title=f"D{i}"),
                admin_a,
                content=f"c{i}".encode(),
                version_number=1,
                filename=f"d{i}.pdf",
            )
            add_entry(package, tenant_a, admin_a, version)

        issues = check_package(package=package, entries=list(services.active_entries(package)))
        assert IntegrityIssue.TOO_MANY_ENTRIES in [i["code"] for i in issues]

    def test_the_size_limit_is_reported(self, tenant_a, admin_a, settings):
        from submission_packages.tests.conftest import add_entry, make_package

        settings.SUBMISSION_PACKAGE_MAX_TOTAL_BYTES = 1
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a),
            admin_a,
            content=b"more than one byte",
            version_number=1,
        )
        add_entry(package, tenant_a, admin_a, version)

        issues = check_package(package=package, entries=list(services.active_entries(package)))
        assert IntegrityIssue.TOO_LARGE in [i["code"] for i in issues]

    def test_a_storage_backend_that_cannot_answer_fails_closed(
        self, tenant_a, admin_a, monkeypatch
    ):
        """A backend that raises is not the same as one that answered yes."""
        from submission_packages.tests.conftest import add_entry, make_package

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"a", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)

        from documents import storage

        class Broken:
            def exists(self, key):
                raise RuntimeError("storage is unreachable")

        monkeypatch.setattr(storage, "get_storage_backend", lambda: Broken())
        issues = check_package(
            package=package,
            entries=list(services.active_entries(package)),
            verify_storage=True,
        )
        assert IntegrityIssue.STORAGE_UNAVAILABLE in [i["code"] for i in issues]
