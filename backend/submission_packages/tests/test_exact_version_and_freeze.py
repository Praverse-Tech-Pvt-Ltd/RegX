"""The exact-version guarantee, the manifest, and freeze.

**The core property of this milestone**: a package binds to exact bytes, and
uploading a new version of a cited document changes nothing about it. Everything
else here exists to make that guarantee mean something -- a manifest that is
deterministic, a freeze that is transactional, and a frozen package that cannot
be edited afterwards.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure, and nothing here
produces anything an agency ingests.
"""

import pytest

from submission_packages import services
from submission_packages.integrity import IntegrityIssue
from submission_packages.manifest import build_manifest, canonical_bytes, manifest_checksum
from submission_packages.models import PackageStatus, SubmissionPackage
from submission_packages.tests.conftest import (
    add_entry,
    freeze,
    make_case,
    make_document,
    make_package,
    make_version,
)

V1_BYTES = b"%PDF-1.4 synthetic version one payload"
V2_BYTES = b"%PDF-1.4 synthetic version two payload, completely different"


@pytest.fixture
def package_with_v1(tenant_a, admin_a):
    """A DRAFT package citing v1 of one document, with v2 not yet uploaded."""
    case = make_case(tenant_a, admin_a)
    document = make_document(tenant_a, admin_a)
    v1 = make_version(document, admin_a, content=V1_BYTES, version_number=1)
    package = make_package(case, tenant_a, admin_a)
    entry = add_entry(package, tenant_a, admin_a, v1, logical_path="01-cover")
    return {
        "case": case,
        "document": document,
        "v1": v1,
        "package": package,
        "entry": entry,
    }


# ---------------------------------------------------------------------------
# The core guarantee
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExactDocumentVersion:
    def test_an_entry_binds_to_a_version_not_a_document(self, package_with_v1):
        entry = package_with_v1["entry"]
        assert entry.document_version_id == package_with_v1["v1"].pk
        # The FK is to DocumentVersion. There is no `document` field to follow.
        assert not hasattr(entry, "document_id")

    def test_a_new_version_does_not_move_the_package(self, package_with_v1, tenant_a, admin_a):
        """THE test. Upload v2; the package still cites v1, byte for byte."""
        document = package_with_v1["document"]
        v1 = package_with_v1["v1"]
        entry = package_with_v1["entry"]

        v2 = make_version(document, admin_a, content=V2_BYTES, version_number=2)
        document.refresh_from_db()
        assert document.current_version_id == v2.pk, "precondition: the document moved on"

        entry.refresh_from_db()
        assert entry.document_version_id == v1.pk
        assert entry.document_version.sha256_checksum == v1.sha256_checksum
        assert entry.document_version.sha256_checksum != v2.sha256_checksum

    def test_a_frozen_manifest_still_names_the_old_version_after_an_upload(
        self, package_with_v1, tenant_a, admin_a
    ):
        package = freeze(package_with_v1["package"], tenant_a, admin_a)
        checksum_at_freeze = package.manifest_checksum

        make_version(package_with_v1["document"], admin_a, content=V2_BYTES, version_number=2)

        package.refresh_from_db()
        snapshot = package.snapshot
        assert package.manifest_checksum == checksum_at_freeze
        row = snapshot.manifest["entries"][0]
        assert row["document_version_public_id"] == str(package_with_v1["v1"].public_id)
        assert row["document_checksum_sha256"] == package_with_v1["v1"].sha256_checksum
        assert row["document_version_number"] == 1

    def test_a_quarantined_version_cannot_be_added(self, tenant_a, admin_a):
        """The document platform's own status, read not reinterpreted."""
        case = make_case(tenant_a, admin_a)
        document = make_document(tenant_a, admin_a)
        bad = make_version(document, admin_a, content=b"x", version_number=1, clean=False)
        package = make_package(case, tenant_a, admin_a)

        with pytest.raises(services.InvalidTarget):
            add_entry(package, tenant_a, admin_a, bad)

    def test_the_refusal_message_does_not_reveal_why(self, tenant_a, admin_a, tenant_b, admin_b):
        """Absent, cross-tenant and not-cleared are one outcome.

        Distinct messages would let a caller probe for documents outside their
        tenant, and would disclose the scan state of one they cannot see.
        """
        import uuid

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)

        b_document = make_document(tenant_b, admin_b)
        b_version = make_version(b_document, admin_b, content=b"b", version_number=1)

        quarantined = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"q", version_number=1, clean=False
        )

        messages = set()
        for target in (uuid.uuid4(), b_version.public_id, quarantined.public_id):
            with pytest.raises(services.InvalidTarget) as exc:
                services.add_entry(
                    package=package,
                    tenant=tenant_a,
                    actor=admin_a,
                    document_version_public_id=target,
                )
            messages.add(str(exc.value))
        assert len(messages) == 1, messages


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestManifestCanonicalization:
    def test_the_same_composition_hashes_the_same_twice(self, tenant_a, admin_a):
        """Three entries, because reversing a list of one proves nothing.

        The first version of this test used a single-entry fixture, and a
        mutation that removed the canonical sort entirely turned no test red.
        """
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        for i in range(3):
            version = make_version(
                make_document(tenant_a, admin_a, title=f"Doc {i}"),
                admin_a,
                content=f"payload {i}".encode(),
                version_number=1,
                filename=f"doc-{i}.pdf",
            )
            add_entry(package, tenant_a, admin_a, version, logical_path=f"p{i}")

        entries = list(services.active_entries(package))
        assert len(entries) == 3, "precondition: order has to be able to differ"

        first = build_manifest(package=package, entries=entries)
        second = build_manifest(package=package, entries=list(reversed(entries)))
        assert canonical_bytes(first) == canonical_bytes(second), (
            "entry order in the input must not change the canonical output"
        )
        assert manifest_checksum(first) == manifest_checksum(second)

        # And the rows really are in the canonical order, not merely equal.
        sequences = [row["sequence"] for row in first["entries"]]
        assert sequences == sorted(sequences)

    def test_a_shuffled_input_still_produces_the_documented_order(self, tenant_a, admin_a):
        """Direct assertion on the ordering rule: sequence, then public id."""
        import random

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        for i in range(5):
            version = make_version(
                make_document(tenant_a, admin_a, title=f"Doc {i}"),
                admin_a,
                content=f"payload {i}".encode(),
                version_number=1,
                filename=f"doc-{i}.pdf",
            )
            add_entry(package, tenant_a, admin_a, version, logical_path=f"p{i}")

        entries = list(services.active_entries(package))
        shuffled = entries[:]
        random.Random(7).shuffle(shuffled)

        manifest = build_manifest(package=package, entries=shuffled)
        keys = [(row["sequence"], row["entry_public_id"]) for row in manifest["entries"]]
        assert keys == sorted(keys), keys

    def test_no_timestamp_leaks_into_the_hashed_bytes(self, package_with_v1):
        """A manifest containing `frozen_at` could never hash the same twice,
        which would defeat every test above. The timestamp lives on the snapshot
        row beside the checksum, not inside the bytes it covers."""
        manifest = build_manifest(
            package=package_with_v1["package"],
            entries=list(services.active_entries(package_with_v1["package"])),
        )
        text = canonical_bytes(manifest).decode()
        assert "frozen_at" not in text
        assert "generated_at" not in text

    def test_no_database_primary_key_appears(self, package_with_v1):
        manifest = build_manifest(
            package=package_with_v1["package"],
            entries=list(services.active_entries(package_with_v1["package"])),
        )
        text = canonical_bytes(manifest).decode()
        for pk in (
            package_with_v1["package"].pk,
            package_with_v1["entry"].pk,
            package_with_v1["v1"].pk,
        ):
            assert f'"{pk}"' not in text
        assert '"id"' not in text

    def test_the_bytes_are_compact_and_key_sorted(self, package_with_v1):
        manifest = build_manifest(
            package=package_with_v1["package"],
            entries=list(services.active_entries(package_with_v1["package"])),
        )
        raw = canonical_bytes(manifest)
        assert b", " not in raw and b": " not in raw, "no pretty-printing in the hashed source"
        assert raw.startswith(b'{"case_public_id"'), "keys must be sorted"

    @pytest.mark.parametrize("mutation", ["order", "path", "version"])
    def test_changing_the_composition_changes_the_checksum(self, tenant_a, admin_a, mutation):
        case = make_case(tenant_a, admin_a)
        document = make_document(tenant_a, admin_a)
        v1 = make_version(document, admin_a, content=V1_BYTES, version_number=1)
        other = make_document(tenant_a, admin_a, title="Second")
        o1 = make_version(other, admin_a, content=b"other", version_number=1)

        package = make_package(case, tenant_a, admin_a)
        e1 = add_entry(package, tenant_a, admin_a, v1, logical_path="a")
        e2 = add_entry(package, tenant_a, admin_a, o1, logical_path="b")

        before = manifest_checksum(
            build_manifest(package=package, entries=list(services.active_entries(package)))
        )

        if mutation == "order":
            services.reorder_entry(entry=e1, tenant=tenant_a, actor=admin_a, sequence=99)
        elif mutation == "path":
            services.remove_entry(entry=e2, tenant=tenant_a, actor=admin_a)
            add_entry(package, tenant_a, admin_a, o1, logical_path="different")
        else:
            v2 = make_version(document, admin_a, content=V2_BYTES, version_number=2)
            services.remove_entry(entry=e1, tenant=tenant_a, actor=admin_a)
            add_entry(package, tenant_a, admin_a, v2, logical_path="a")

        after = manifest_checksum(
            build_manifest(package=package, entries=list(services.active_entries(package)))
        )
        assert after != before, mutation

    def test_unrelated_activity_does_not_change_a_frozen_manifest(
        self, package_with_v1, tenant_a, admin_a
    ):
        package = freeze(package_with_v1["package"], tenant_a, admin_a)
        stored = package.snapshot.manifest
        checksum = package.snapshot.manifest_checksum

        # Another case, another document, another package entirely.
        other_case = make_case(tenant_a, admin_a, title="Unrelated")
        other_doc = make_document(tenant_a, admin_a, title="Unrelated doc")
        other_v = make_version(other_doc, admin_a, content=b"unrelated", version_number=1)
        other_pkg = make_package(other_case, tenant_a, admin_a, name="Unrelated package")
        add_entry(other_pkg, tenant_a, admin_a, other_v)

        package.snapshot.refresh_from_db()
        assert package.snapshot.manifest == stored
        assert package.snapshot.manifest_checksum == checksum


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFreeze:
    def test_freezing_records_a_snapshot_and_a_checksum(self, package_with_v1, tenant_a, admin_a):
        package = freeze(package_with_v1["package"], tenant_a, admin_a)
        assert package.status == PackageStatus.FROZEN
        assert package.frozen_at is not None
        assert len(package.manifest_checksum) == 64

        snapshot = package.snapshot
        assert snapshot.entry_count == 1
        assert snapshot.manifest_checksum == package.manifest_checksum
        assert snapshot.total_bytes == len(V1_BYTES)

    def test_an_empty_package_cannot_be_frozen(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        with pytest.raises(services.PackageIntegrityError) as exc:
            freeze(package, tenant_a, admin_a)
        assert IntegrityIssue.NO_ACTIVE_ENTRIES in [i["code"] for i in exc.value.issues]

    def test_a_frozen_package_cannot_be_frozen_again(self, package_with_v1, tenant_a, admin_a):
        freeze(package_with_v1["package"], tenant_a, admin_a)
        with pytest.raises(services.PackageLocked):
            freeze(package_with_v1["package"], tenant_a, admin_a)

    def test_a_version_quarantined_after_review_refuses_the_freeze(
        self, package_with_v1, tenant_a, admin_a
    ):
        """The window between assembling and freezing is the dangerous one.

        A version can be quarantined after it was added, and after freeze the
        manifest is permanent -- so this is the last moment the claim can be
        checked at all.
        """
        from documents.models import DocumentVersion, ScanStatus

        DocumentVersion.objects.filter(pk=package_with_v1["v1"].pk).update(
            scan_status=ScanStatus.QUARANTINED
        )
        with pytest.raises(services.PackageIntegrityError) as exc:
            freeze(package_with_v1["package"], tenant_a, admin_a)
        assert IntegrityIssue.SCAN_NOT_CLEARED in [i["code"] for i in exc.value.issues]

        package_with_v1["package"].refresh_from_db()
        assert package_with_v1["package"].status == PackageStatus.IN_REVIEW, (
            "the refused freeze left the package exactly where it was"
        )

    def test_a_missing_stored_file_refuses_the_freeze(self, package_with_v1, tenant_a, admin_a):
        from documents.storage import get_storage_backend

        get_storage_backend().delete(package_with_v1["v1"].storage_key)
        with pytest.raises(services.PackageIntegrityError) as exc:
            freeze(package_with_v1["package"], tenant_a, admin_a)
        assert IntegrityIssue.STORAGE_UNAVAILABLE in [i["code"] for i in exc.value.issues]

    def test_a_failed_freeze_leaves_nothing_behind(self, package_with_v1, tenant_a, admin_a):
        """No frozen status, no snapshot, no checksum, no success audit."""
        from audit.models import AuditEvent
        from documents.models import DocumentVersion, ScanStatus
        from submission_packages.models import SubmissionPackageSnapshot

        DocumentVersion.objects.filter(pk=package_with_v1["v1"].pk).update(
            scan_status=ScanStatus.QUARANTINED
        )
        with pytest.raises(services.PackageIntegrityError):
            freeze(package_with_v1["package"], tenant_a, admin_a)

        package = package_with_v1["package"]
        package.refresh_from_db()
        assert package.status == PackageStatus.IN_REVIEW
        assert package.manifest_checksum == ""
        assert package.frozen_at is None
        assert not SubmissionPackageSnapshot.objects.filter(package=package).exists()
        assert not AuditEvent.objects.filter(
            event_type="submission_package.frozen", resource_id=str(package.public_id)
        ).exists()

    def test_a_rollback_mid_freeze_leaves_no_half_frozen_package(
        self, package_with_v1, tenant_a, admin_a, monkeypatch
    ):
        """Injected failure after the manifest is computed."""
        from submission_packages import services as svc
        from submission_packages.models import SubmissionPackageSnapshot

        def boom(*args, **kwargs):
            raise RuntimeError("injected failure during snapshot creation")

        package = svc.submit_for_review(
            package=package_with_v1["package"], tenant=tenant_a, actor=admin_a
        )
        monkeypatch.setattr(SubmissionPackageSnapshot.objects, "create", boom)
        with pytest.raises(RuntimeError):
            svc.freeze_package(package=package, tenant=tenant_a, actor=admin_a)

        package = package_with_v1["package"]
        package.refresh_from_db()
        assert package.status == PackageStatus.IN_REVIEW
        assert package.manifest_checksum == ""
        assert not SubmissionPackageSnapshot.objects.filter(package=package).exists()

    def test_freeze_is_reachable_from_in_review(self, package_with_v1, tenant_a, admin_a):
        package = services.submit_for_review(
            package=package_with_v1["package"], tenant=tenant_a, actor=admin_a
        )
        assert package.status == PackageStatus.IN_REVIEW
        package = freeze(package, tenant_a, admin_a)
        assert package.status == PackageStatus.FROZEN


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLifecycle:
    def test_the_documented_state_machine_holds(self, package_with_v1, tenant_a, admin_a):
        package = package_with_v1["package"]
        assert package.status == PackageStatus.DRAFT

        package = services.submit_for_review(package=package, tenant=tenant_a, actor=admin_a)
        assert package.status == PackageStatus.IN_REVIEW

        package = services.return_to_draft(package=package, tenant=tenant_a, actor=admin_a)
        assert package.status == PackageStatus.DRAFT

        package = services.cancel_package(package=package, tenant=tenant_a, actor=admin_a)
        assert package.status == PackageStatus.CANCELLED

    def test_a_cancelled_package_is_terminal(self, package_with_v1, tenant_a, admin_a):
        package = services.cancel_package(
            package=package_with_v1["package"], tenant=tenant_a, actor=admin_a
        )
        for call in (services.return_to_draft, services.submit_for_review, services.freeze_package):
            with pytest.raises(services.PackageLocked):
                call(package=package, tenant=tenant_a, actor=admin_a)

    def test_there_is_no_unfreeze(self, package_with_v1, tenant_a, admin_a):
        """A manifest that can be reopened is not a manifest."""
        package = freeze(package_with_v1["package"], tenant_a, admin_a)
        for call in (services.return_to_draft, services.submit_for_review, services.cancel_package):
            with pytest.raises(services.PackageLocked):
                call(package=package, tenant=tenant_a, actor=admin_a)
        assert not hasattr(services, "unfreeze_package")

    def test_entries_cannot_be_changed_once_the_package_leaves_draft(
        self, package_with_v1, tenant_a, admin_a
    ):
        package = services.submit_for_review(
            package=package_with_v1["package"], tenant=tenant_a, actor=admin_a
        )
        document = make_document(tenant_a, admin_a, title="Late arrival")
        late = make_version(document, admin_a, content=b"late", version_number=1)

        with pytest.raises(services.PackageLocked):
            add_entry(package, tenant_a, admin_a, late)
        with pytest.raises(services.PackageLocked):
            services.remove_entry(entry=package_with_v1["entry"], tenant=tenant_a, actor=admin_a)

    def test_a_removed_entry_is_retired_not_deleted(self, package_with_v1, tenant_a, admin_a):
        entry = services.remove_entry(
            entry=package_with_v1["entry"], tenant=tenant_a, actor=admin_a
        )
        assert entry.removed_at is not None
        assert entry.removed_by_id is not None
        # Still there, still readable: a DRAFT is governed history too.
        entry.refresh_from_db()
        assert entry.pk is not None
        assert services.active_entries(package_with_v1["package"]).count() == 0

    def test_the_status_vocabulary_avoids_approval_language(self):
        values = set(PackageStatus.values)
        assert values == {"draft", "in_review", "frozen", "cancelled"}
        for banned in ("approved", "accepted", "released", "published", "submitted"):
            assert banned not in values


# ---------------------------------------------------------------------------
# Regulatory boundary
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegulatoryBoundary:
    def test_no_module_claims_agency_readiness(self):
        """Pinned. Every match must be inside an explicit disclaimer."""
        import pathlib

        banned = [
            "agency ready",
            "fda ready",
            "ema ready",
            "submission accepted",
            "regulatory approved",
            "regulatory compliant",
            "part 11 compliant",
            "validated system",
            "approved submission",
        ]
        root = pathlib.Path("submission_packages")
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == pathlib.Path(__file__).name:
                # This file owns the banned list, so every phrase appears in it
                # by construction. Skipping it is not a loophole: nothing here
                # ships, and the phrases live inside a literal that exists only
                # to keep them out of everything that does.
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for phrase in banned:
                if phrase in text:
                    # Allowed only where the surrounding line denies it.
                    for line in text.splitlines():
                        if phrase in line and not any(
                            marker in line for marker in ("not ", "never", "no ", "banned")
                        ):
                            offenders.append(f"{path}: {phrase}")
        assert offenders == [], offenders

    def test_the_manifest_declares_itself_internal(self, package_with_v1):
        manifest = build_manifest(
            package=package_with_v1["package"],
            entries=list(services.active_entries(package_with_v1["package"])),
        )
        assert manifest["semantics"] == "internal_package_manifest"

    def test_the_integrity_result_declares_itself_internal(self, package_with_v1, tenant_a):
        result = services.validate_package(package=package_with_v1["package"], tenant=tenant_a)
        assert result["semantics"] == "internal_package_integrity"

    def test_no_agency_folder_name_is_ever_inserted(self, package_with_v1):
        """The export path is exactly what the tenant typed, under `files/`."""
        from submission_packages.export import archive_name

        entry = package_with_v1["entry"]
        assert archive_name(entry) == f"files/01-cover/{entry.export_filename}"

    def test_revision_number_is_not_called_a_sequence(self):
        field_names = {f.name for f in SubmissionPackage._meta.get_fields()}
        assert "revision_number" in field_names
        for banned in ("submission_sequence", "sequence_number", "ectd_sequence"):
            assert banned not in field_names
