"""Export, clone/revision, concurrency and query cost.

The export tests open the produced archive and read the bytes back out, because
the only convincing proof that a package exports *exact* versions is comparing
the extracted content against the version that was cited -- not against the
version the document happens to be on now.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure, and the ZIP is
an internal container, not an agency format.
"""

import io
import zipfile

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from submission_packages import services
from submission_packages.export import ExportError, write_package_zip
from submission_packages.models import PackageStatus
from submission_packages.tests.conftest import (
    PKG_API,
    add_entry,
    freeze,
    make_case,
    make_document,
    make_package,
    make_version,
)

V1_BYTES = b"%PDF-1.4 exact version one bytes"
V2_BYTES = b"%PDF-1.4 completely different version two bytes"


@pytest.fixture
def frozen_with_two(tenant_a, admin_a):
    case = make_case(tenant_a, admin_a)
    doc_a = make_document(tenant_a, admin_a, title="Doc A")
    doc_b = make_document(tenant_a, admin_a, title="Doc B")
    v_a = make_version(doc_a, admin_a, content=V1_BYTES, version_number=1, filename="a.pdf")
    v_b = make_version(doc_b, admin_a, content=b"second file", version_number=1, filename="b.pdf")
    package = make_package(case, tenant_a, admin_a)
    add_entry(package, tenant_a, admin_a, v_a, logical_path="01-cover")
    add_entry(package, tenant_a, admin_a, v_b, logical_path="02-supporting")
    package = freeze(package, tenant_a, admin_a)
    return {"package": package, "case": case, "doc_a": doc_a, "v_a": v_a, "v_b": v_b}


def _build_zip(package):
    buffer = io.BytesIO()
    write_package_zip(
        snapshot=package.snapshot,
        entries=list(services.active_entries(package)),
        destination=buffer,
    )
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExport:
    def test_the_archive_holds_the_manifest_and_every_file(self, frozen_with_two):
        archive = _build_zip(frozen_with_two["package"])
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "files/01-cover/a.pdf" in names
        assert "files/02-supporting/b.pdf" in names
        assert len(names) == 3

    def test_the_archived_manifest_is_the_stored_snapshot(self, frozen_with_two):
        """Not one recomputed now. A recomputed manifest would make the archive
        a function of today's database, which is what a snapshot exists to
        avoid."""
        import hashlib
        import json

        package = frozen_with_two["package"]
        archive = _build_zip(package)
        raw = archive.read("manifest.json")
        assert json.loads(raw) == package.snapshot.manifest
        # And the bytes hash to the stored checksum, so the archive carries a
        # manifest that matches what the package claims.
        assert hashlib.sha256(raw).hexdigest() == package.snapshot.manifest_checksum

    def test_the_exported_bytes_are_the_cited_version_not_the_latest(
        self, frozen_with_two, tenant_a, admin_a
    ):
        """THE export test. A new version arrives; the archive is unchanged."""
        v2 = make_version(frozen_with_two["doc_a"], admin_a, content=V2_BYTES, version_number=2)
        frozen_with_two["doc_a"].refresh_from_db()
        assert frozen_with_two["doc_a"].current_version_id == v2.pk

        archive = _build_zip(frozen_with_two["package"])
        assert archive.read("files/01-cover/a.pdf") == V1_BYTES
        assert archive.read("files/01-cover/a.pdf") != V2_BYTES

    def test_every_file_matches_its_recorded_checksum(self, frozen_with_two):
        import hashlib

        package = frozen_with_two["package"]
        archive = _build_zip(package)
        by_version = {row["export_filename"]: row for row in package.snapshot.manifest["entries"]}
        for name in archive.namelist():
            if name == "manifest.json":
                continue
            row = by_version[name.rsplit("/", 1)[-1]]
            content = archive.read(name)
            assert hashlib.sha256(content).hexdigest() == row["document_checksum_sha256"]
            assert len(content) == row["file_size_bytes"]

    def test_a_changed_stored_file_fails_the_export(self, frozen_with_two, tenant_a, admin_a):
        """The trust boundary, verified rather than assumed. If storage no longer
        matches the manifest, the archive would ship a manifest that is a lie
        about its own contents."""
        from documents.storage import get_storage_backend

        version = frozen_with_two["v_a"]
        backend = get_storage_backend()
        backend.delete(version.storage_key)
        backend.store(
            tenant_id=version.document.tenant_id,
            file_obj=io.BytesIO(b"tampered content"),
            expected_sha256=__import__("hashlib").sha256(b"tampered content").hexdigest(),
            content_type="application/pdf",
            original_filename="a.pdf",
        )
        # Point the version at the tampered object without touching its checksum.
        from documents.models import DocumentVersion

        tampered_key = backend.store(
            tenant_id=version.document.tenant_id,
            file_obj=io.BytesIO(b"tampered content"),
            expected_sha256=__import__("hashlib").sha256(b"tampered content").hexdigest(),
            content_type="application/pdf",
            original_filename="a.pdf",
        )
        DocumentVersion.objects.filter(pk=version.pk).update(storage_key=tampered_key)

        with pytest.raises(ExportError) as exc:
            _build_zip(frozen_with_two["package"])
        assert "checksum" in str(exc.value).lower()

    def test_a_missing_stored_file_fails_the_export(self, frozen_with_two):
        """Never silently skipped. An archive missing one of two files looks
        complete to whoever receives it."""
        from documents.storage import get_storage_backend

        get_storage_backend().delete(frozen_with_two["v_a"].storage_key)
        with pytest.raises(ExportError):
            _build_zip(frozen_with_two["package"])

    def test_no_archive_name_can_escape_the_extraction_root(self, frozen_with_two):
        from submission_packages.export import _assert_safe

        for name in (
            "/etc/passwd",
            "files/../../etc/passwd",
            "C:/windows/system32",
            "files/\x00x",
            "\\\\server\\share",
        ):
            with pytest.raises(ExportError):
                _assert_safe(name)

    def test_every_archived_name_lives_under_files(self, frozen_with_two):
        """So a `manifest.json` at the root can never be shadowed by an entry
        that happens to be called that."""
        archive = _build_zip(frozen_with_two["package"])
        for name in archive.namelist():
            if name != "manifest.json":
                assert name.startswith("files/")

    def test_the_archive_contains_no_symlink_or_absolute_entry(self, frozen_with_two):
        archive = _build_zip(frozen_with_two["package"])
        for info in archive.infolist():
            assert not info.filename.startswith("/")
            assert ".." not in info.filename.split("/")
            # Unix mode is stored in the high 16 bits of external_attr; S_IFLNK
            # is 0xA000. Nothing this module writes is a link.
            assert (info.external_attr >> 16) & 0xF000 != 0xA000

    def test_only_a_frozen_package_can_be_exported(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"x", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version)
        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/export/")
        assert response.status_code == 409

    def test_the_export_endpoint_streams_a_zip_and_audits_it(self, client_admin_a, frozen_with_two):
        from audit.models import AuditEvent

        package = frozen_with_two["package"]
        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/export/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"

        content = b"".join(response.streaming_content)
        archive = zipfile.ZipFile(io.BytesIO(content))
        assert "manifest.json" in archive.namelist()
        assert archive.read("files/01-cover/a.pdf") == V1_BYTES

        event = AuditEvent.objects.filter(
            event_type="submission_package.exported", resource_id=str(package.public_id)
        ).first()
        assert event is not None
        assert event.payload["manifest_checksum"] == package.snapshot.manifest_checksum
        assert event.payload["export_format"] == "zip"
        # Filenames are content and never travel to the audit row.
        assert "a.pdf" not in str(event.payload)


# ---------------------------------------------------------------------------
# Clone / revision
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestClone:
    def test_a_clone_is_a_new_draft_that_copies_the_exact_references(
        self, frozen_with_two, tenant_a, admin_a
    ):
        source = frozen_with_two["package"]
        clone = services.clone_package(package=source, tenant=tenant_a, actor=admin_a)

        assert clone.status == PackageStatus.DRAFT
        assert clone.public_id != source.public_id
        assert clone.revision_number == source.revision_number + 1
        assert clone.source_package_id == source.pk

        source_versions = {e.document_version_id for e in services.active_entries(source)}
        clone_versions = {e.document_version_id for e in services.active_entries(clone)}
        assert clone_versions == source_versions

    def test_changing_the_clone_leaves_the_original_alone(self, frozen_with_two, tenant_a, admin_a):
        source = frozen_with_two["package"]
        before_checksum = source.manifest_checksum
        before_count = services.active_entries(source).count()

        clone = services.clone_package(package=source, tenant=tenant_a, actor=admin_a)
        first = services.active_entries(clone).first()
        services.remove_entry(entry=first, tenant=tenant_a, actor=admin_a)

        source.refresh_from_db()
        assert source.status == PackageStatus.FROZEN
        assert source.manifest_checksum == before_checksum
        assert services.active_entries(source).count() == before_count
        assert services.active_entries(clone).count() == before_count - 1

    def test_both_revisions_survive_as_separate_history(self, frozen_with_two, tenant_a, admin_a):
        source = frozen_with_two["package"]
        clone = services.clone_package(package=source, tenant=tenant_a, actor=admin_a)
        frozen_clone = freeze(clone, tenant_a, admin_a)

        source.refresh_from_db()
        assert source.status == PackageStatus.FROZEN
        assert frozen_clone.status == PackageStatus.FROZEN
        assert source.snapshot.pk != frozen_clone.snapshot.pk
        # Same composition, so the manifests differ only by package identity --
        # which is enough to make the checksums differ, and should.
        assert source.snapshot.manifest_checksum != frozen_clone.snapshot.manifest_checksum

    def test_only_a_frozen_package_can_be_cloned(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        with pytest.raises(services.PackageLocked):
            services.clone_package(package=package, tenant=tenant_a, actor=admin_a)

    def test_a_clone_carrying_an_ineligible_version_refuses_to_freeze(
        self, frozen_with_two, tenant_a, admin_a
    ):
        """The clone keeps the reference so the user can see what has to be
        replaced; the refusal belongs at the moment something permanent is
        written, not at the moment someone asked to look."""
        from documents.models import DocumentVersion, ScanStatus

        clone = services.clone_package(
            package=frozen_with_two["package"], tenant=tenant_a, actor=admin_a
        )
        assert services.active_entries(clone).count() == 2

        DocumentVersion.objects.filter(pk=frozen_with_two["v_a"].pk).update(
            scan_status=ScanStatus.QUARANTINED
        )
        with pytest.raises(services.PackageIntegrityError):
            freeze(clone, tenant_a, admin_a)

    def test_revision_number_climbs_across_a_chain(self, frozen_with_two, tenant_a, admin_a):
        source = frozen_with_two["package"]
        second = services.clone_package(package=source, tenant=tenant_a, actor=admin_a)
        second = freeze(second, tenant_a, admin_a)
        third = services.clone_package(package=second, tenant=tenant_a, actor=admin_a)

        assert [source.revision_number, second.revision_number, third.revision_number] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Concurrency -- real threads, real PostgreSQL
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    def test_only_one_of_two_simultaneous_freezes_wins(self, tenant_a, admin_a):
        import threading

        from django.db import connections

        case = make_case(tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"x", version_number=1
        )
        package = make_package(case, tenant_a, admin_a)
        add_entry(package, tenant_a, admin_a, version)
        package = services.submit_for_review(package=package, tenant=tenant_a, actor=admin_a)

        wins, errors = [], []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=15)
                wins.append(
                    services.freeze_package(package=package, tenant=tenant_a, actor=admin_a)
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(wins) == 1, f"expected exactly one winner: {errors}"
        from submission_packages.models import SubmissionPackageSnapshot

        assert SubmissionPackageSnapshot.objects.filter(package=package).count() == 1

    def test_an_entry_cannot_be_added_into_a_package_being_frozen(self, tenant_a, admin_a):
        """The package row is the serialization point, so an add either lands
        before the freeze or is refused by it -- never lands inside it."""
        import threading

        from django.db import connections

        case = make_case(tenant_a, admin_a)
        first = make_version(
            make_document(tenant_a, admin_a, title="First"),
            admin_a,
            content=b"first",
            version_number=1,
        )
        second = make_version(
            make_document(tenant_a, admin_a, title="Second"),
            admin_a,
            content=b"second",
            version_number=1,
        )
        package = make_package(case, tenant_a, admin_a)
        add_entry(package, tenant_a, admin_a, first)
        package = services.submit_for_review(package=package, tenant=tenant_a, actor=admin_a)

        outcomes = {"frozen": [], "added": [], "errors": []}
        barrier = threading.Barrier(2)

        def freezer():
            try:
                barrier.wait(timeout=15)
                outcomes["frozen"].append(
                    services.freeze_package(package=package, tenant=tenant_a, actor=admin_a)
                )
            except Exception as exc:
                outcomes["errors"].append(exc)
            finally:
                connections.close_all()

        def adder():
            try:
                barrier.wait(timeout=15)
                outcomes["added"].append(add_entry(package, tenant_a, admin_a, second))
            except Exception as exc:
                outcomes["errors"].append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=freezer), threading.Thread(target=adder)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        package.refresh_from_db()
        if outcomes["frozen"]:
            # The freeze won: the manifest must describe exactly what it locked,
            # and the add must have been refused.
            assert package.status == PackageStatus.FROZEN
            assert package.snapshot.entry_count == len(package.snapshot.manifest["entries"])
            assert not outcomes["added"], "an entry landed inside a freeze"
        else:
            # The add won, so the package never left review.
            assert package.status == PackageStatus.IN_REVIEW

    def test_two_simultaneous_clones_take_different_revision_numbers(self, tenant_a, admin_a):
        import threading

        from django.db import connections

        case = make_case(tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"x", version_number=1
        )
        package = make_package(case, tenant_a, admin_a)
        add_entry(package, tenant_a, admin_a, version)
        package = freeze(package, tenant_a, admin_a)

        clones, errors = [], []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=15)
                clones.append(
                    services.clone_package(package=package, tenant=tenant_a, actor=admin_a)
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        revisions = [c.revision_number for c in clones]
        assert len(revisions) == len(set(revisions)), (
            f"two clones took the same revision number: {revisions}"
        )


# ---------------------------------------------------------------------------
# Query cost
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestQueryCost:
    """Bounded, not tiny. Compared across sizes rather than pinned, because an
    absolute number breaks on every harmless refactor and still would not catch
    the thing that matters."""

    def _grow(self, package, tenant, actor, n, start=0):
        for i in range(start, n):
            version = make_version(
                make_document(tenant, actor, title=f"Doc {i}"),
                actor,
                content=f"payload {i}".encode(),
                version_number=1,
                filename=f"doc-{i}.pdf",
            )
            add_entry(package, tenant, actor, version, logical_path=f"p{i % 5}")

    def test_package_detail_is_flat_across_entry_count(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        counts = {}
        built = 0
        for target in (10, 50, 120):
            self._grow(package, tenant_a, admin_a, target, start=built)
            built = target
            with CaptureQueriesContext(connection) as ctx:
                response = client_admin_a.get(f"{PKG_API}/{package.public_id}/")
                assert response.status_code == 200
            counts[target] = len(ctx.captured_queries)
        assert counts[10] == counts[50] == counts[120], counts

    def test_manifest_generation_is_flat_across_entry_count(self, tenant_a, admin_a):
        from submission_packages.manifest import build_manifest

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        counts = {}
        built = 0
        for target in (10, 50, 120):
            self._grow(package, tenant_a, admin_a, target, start=built)
            built = target
            with CaptureQueriesContext(connection) as ctx:
                entries = list(services.active_entries(package))
                manifest = build_manifest(package=package, entries=entries)
                assert manifest["entry_count"] == target
            counts[target] = len(ctx.captured_queries)
        assert counts[10] == counts[50] == counts[120], counts

    def test_the_case_package_list_is_flat_across_package_count(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        counts = {}
        built = 0
        for target in (5, 25, 60):
            for i in range(built, target):
                package = make_package(case, tenant_a, admin_a, name=f"Package {i}")
                version = make_version(
                    make_document(tenant_a, admin_a, title=f"D{i}"),
                    admin_a,
                    content=f"c{i}".encode(),
                    version_number=1,
                )
                add_entry(package, tenant_a, admin_a, version)
            built = target
            with CaptureQueriesContext(connection) as ctx:
                response = client_admin_a.get(
                    f"/api/regx/v1/regulatory-cases/{case.public_id}/packages/",
                    {"page_size": 100},
                )
                assert response.status_code == 200
            counts[target] = len(ctx.captured_queries)
        assert counts[5] == counts[25] == counts[60], counts

    def test_freezing_does_not_query_per_entry(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        small = make_package(case, tenant_a, admin_a, name="Small")
        self._grow(small, tenant_a, admin_a, 5)
        small = services.submit_for_review(package=small, tenant=tenant_a, actor=admin_a)

        large = make_package(case, tenant_a, admin_a, name="Large")
        self._grow(large, tenant_a, admin_a, 60)
        large = services.submit_for_review(package=large, tenant=tenant_a, actor=admin_a)

        with CaptureQueriesContext(connection) as ctx:
            services.freeze_package(package=small, tenant=tenant_a, actor=admin_a)
        small_count = len(ctx.captured_queries)

        with CaptureQueriesContext(connection) as ctx:
            services.freeze_package(package=large, tenant=tenant_a, actor=admin_a)
        large_count = len(ctx.captured_queries)

        assert large_count == small_count, (
            f"freeze grew with entry count: {small_count} -> {large_count}"
        )
