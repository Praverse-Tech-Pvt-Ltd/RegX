"""The three defects found in review, and the guards that now close them.

1. The manifest is document-bearing information and was served under package
   permission alone, which routed around the projection the detail endpoint
   maintains.
2. Export compared streamed bytes against *today's* `DocumentVersion` metadata
   rather than against the frozen snapshot.
3. Revision numbers were claimed under the source package's lock, which
   serialises nothing between two clones of two different revisions of the same
   family -- and were keyed on the package name, which a user may edit.

Synthetic data throughout. No CTD, CEP, DMF or ANDA structure; the ZIP is an
internal container and FROZEN is an internal state.
"""

import hashlib
import importlib
import io
import json
import threading
import uuid
import zipfile

import pytest
from django.db import IntegrityError, connection, connections, migrations, transaction
from django.db.utils import InternalError, ProgrammingError

from submission_packages import services
from submission_packages.export import ExportError, write_package_zip
from submission_packages.models import SubmissionPackage
from submission_packages.tests.conftest import (
    PKG_API,
    add_entry,
    freeze,
    make_case,
    make_document,
    make_package,
    make_version,
)

FROZEN_BYTES = b"%PDF-1.4 the bytes that were frozen"
OTHER_BYTES = b"%PDF-1.4 entirely different bytes, and a different length too"

#: plpgsql `RAISE EXCEPTION` surfaces as one of these depending on driver and
#: whether the statement was prepared. Catching the union keeps the test about
#: the refusal rather than about psycopg internals.
DB_REFUSAL = (InternalError, ProgrammingError, IntegrityError)


@pytest.fixture
def frozen_package(tenant_a, admin_a):
    """One frozen package citing one exact version, with real stored bytes."""
    case = make_case(tenant_a, admin_a)
    document = make_document(tenant_a, admin_a, title="Cited document")
    version = make_version(
        document, admin_a, content=FROZEN_BYTES, version_number=1, filename="cited.pdf"
    )
    package = make_package(case, tenant_a, admin_a, name="Frozen package")
    add_entry(package, tenant_a, admin_a, version, logical_path="01-cover")
    package = freeze(package, tenant_a, admin_a)
    return {"package": package, "case": case, "document": document, "version": version}


def _export(package, entries=None):
    buffer = io.BytesIO()
    write_package_zip(
        snapshot=package.snapshot,
        entries=list(services.active_entries(package)) if entries is None else entries,
        destination=buffer,
    )
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


# ---------------------------------------------------------------------------
# MAJOR 1 -- the manifest is document-bearing information
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestManifestDocumentGate:
    """Two gates: `submission_packages.view` AND `documents.view`.

    The manifest names every cited document, its exact version, its SHA-256 and
    its size -- the same fields package detail returns as `null` to a caller
    without document permission. One endpoint may not undo another's projection.
    """

    def test_a_caller_with_both_permissions_reads_the_manifest(
        self, client_admin_a, frozen_package
    ):
        package = frozen_package["package"]
        response = client_admin_a.get(f"{PKG_API}/{package.public_id}/manifest/")
        assert response.status_code == 200
        assert response.data["manifest"] == package.snapshot.manifest
        assert response.data["manifest_checksum"] == package.snapshot.manifest_checksum
        # The gate is worth having only if the payload really carries this.
        row = response.data["manifest"]["entries"][0]
        assert row["document_version_public_id"]
        assert row["document_checksum_sha256"]

    def test_package_view_without_document_view_is_refused(self, client_support_a, frozen_package):
        """PLATFORM_SUPPORT holds `submission_packages.view` and not
        `documents.view` -- the exact shape the projection exists for."""
        package = frozen_package["package"]
        response = client_support_a.get(f"{PKG_API}/{package.public_id}/manifest/")
        assert response.status_code == 403

    def test_the_same_caller_still_reads_package_detail_with_documents_hidden(
        self, client_support_a, frozen_package
    ):
        """Proof the refusal is about the manifest and not about the package.

        Detail stays readable; it just answers `document: null`. If this went
        403 too, the manifest gate would be a blunt instrument rather than the
        projection being consistent.
        """
        package = frozen_package["package"]
        response = client_support_a.get(f"{PKG_API}/{package.public_id}/")
        assert response.status_code == 200
        assert response.data["entries"][0]["document"] is None

    def test_the_refusal_exposes_no_document_identity(self, client_support_a, frozen_package):
        package = frozen_package["package"]
        version = frozen_package["version"]
        document = frozen_package["document"]

        response = client_support_a.get(f"{PKG_API}/{package.public_id}/manifest/")
        assert response.status_code == 403
        body = json.dumps(response.data, default=str)

        for secret in (
            str(document.public_id),
            str(version.public_id),
            version.sha256_checksum,
            version.original_filename,
            version.detected_mime_type,
            str(version.size_bytes),
        ):
            assert secret not in body, f"the refusal leaked {secret!r}"

    def test_a_foreign_package_is_indistinguishable_from_a_missing_one(
        self, client_support_a, client_admin_b, tenant_b, admin_b
    ):
        """404 for both, for a caller with document permission and without.

        The document gate is checked *after* the tenant-scoped lookup on
        purpose. Checking it first would answer 403 for a package in another
        tenant and confirm the package exists.
        """
        case = make_case(tenant_b, admin_b, title="B case")
        document = make_document(tenant_b, admin_b)
        version = make_version(document, admin_b, content=b"b bytes", version_number=1)
        package = make_package(case, tenant_b, admin_b, name="B package")
        add_entry(package, tenant_b, admin_b, version)
        package = freeze(package, tenant_b, admin_b)

        url = f"{PKG_API}/{package.public_id}/manifest/"
        absent = f"{PKG_API}/{uuid.uuid4()}/manifest/"

        # The caller who cannot see documents at all: both 404, same shape.
        foreign = client_support_a.get(url)
        missing = client_support_a.get(absent)
        assert foreign.status_code == 404
        assert missing.status_code == 404
        assert json.dumps(foreign.data, default=str) == json.dumps(missing.data, default=str)

        # And the owning tenant still reads it, so the 404 above is scoping.
        assert client_admin_b.get(url).status_code == 200

    def test_the_stored_snapshot_is_never_altered_for_a_caller(
        self, client_support_a, client_admin_a, frozen_package
    ):
        """No redacted manifest. A manifest with fields removed is a second,
        differently-hashed document claiming to be the manifest."""
        package = frozen_package["package"]
        before = package.snapshot.manifest_checksum

        assert client_support_a.get(f"{PKG_API}/{package.public_id}/manifest/").status_code == 403

        package.snapshot.refresh_from_db()
        assert package.snapshot.manifest_checksum == before
        served = client_admin_a.get(f"{PKG_API}/{package.public_id}/manifest/").data["manifest"]
        raw = json.dumps(served, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == before

    def test_the_export_document_gate_is_unchanged(
        self, client_support_a, client_admin_a, frozen_package
    ):
        package = frozen_package["package"]
        assert client_support_a.get(f"{PKG_API}/{package.public_id}/export/").status_code in (
            403,
            404,
        )
        allowed = client_admin_a.get(f"{PKG_API}/{package.public_id}/export/")
        assert allowed.status_code == 200
        assert allowed["Content-Type"] == "application/zip"


# ---------------------------------------------------------------------------
# MAJOR 2 -- the frozen snapshot is the authority at export
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSnapshotIsTheExportAuthority:
    """Expected checksums and sizes come from the snapshot, never from the live
    `DocumentVersion` row.

    This is not a claim that `DocumentVersion` is immutable -- the database does
    not prove that, which is exactly why the snapshot has to be the authority.
    The rewrites below use the same plain `objects.update()` any bug, migration
    or raw cursor could.
    """

    def _repoint(self, version, content):
        """Store `content` and rewrite the live row to describe it. No trigger
        stops this today, which is the whole point."""
        from documents.models import DocumentVersion
        from documents.storage import get_storage_backend

        checksum = hashlib.sha256(content).hexdigest()
        key = get_storage_backend().store(
            tenant_id=version.document.tenant_id,
            file_obj=io.BytesIO(content),
            expected_sha256=checksum,
            content_type="application/pdf",
            original_filename="swapped.pdf",
        )
        DocumentVersion.objects.filter(pk=version.pk).update(
            storage_key=key, sha256_checksum=checksum, size_bytes=len(content)
        )
        return checksum

    def test_export_fails_when_live_metadata_is_rewritten_to_match_new_bytes(self, frozen_package):
        """THE regression test.

        Storage key, checksum and size are rewritten *together*, so an exporter
        that compares streamed bytes against today's metadata finds perfect
        agreement and ships an archive whose files contradict the manifest.json
        beside them. Against the frozen snapshot it cannot.
        """
        package = frozen_package["package"]
        frozen_row = package.snapshot.manifest["entries"][0]

        new_checksum = self._repoint(frozen_package["version"], OTHER_BYTES)
        assert new_checksum != frozen_row["document_checksum_sha256"]
        assert len(OTHER_BYTES) != int(frozen_row["file_size_bytes"])

        with pytest.raises(ExportError) as excinfo:
            _export(package)
        assert "frozen manifest" in str(excinfo.value)

        # And the snapshot itself was never touched.
        package.snapshot.refresh_from_db()
        assert package.snapshot.manifest["entries"][0] == frozen_row

    def test_export_fails_when_only_the_storage_key_is_repointed(self, frozen_package):
        from documents.models import DocumentVersion
        from documents.storage import get_storage_backend

        version = frozen_package["version"]
        key = get_storage_backend().store(
            tenant_id=version.document.tenant_id,
            file_obj=io.BytesIO(OTHER_BYTES),
            expected_sha256=hashlib.sha256(OTHER_BYTES).hexdigest(),
            content_type="application/pdf",
            original_filename="swapped.pdf",
        )
        DocumentVersion.objects.filter(pk=version.pk).update(storage_key=key)

        with pytest.raises(ExportError):
            _export(frozen_package["package"])

    def test_export_succeeds_when_only_the_live_checksum_is_corrupted(self, frozen_package):
        """The mirror image, and the sharper proof.

        The stored bytes are still the frozen bytes; only the live metadata now
        lies about them. The export must succeed -- because it never asks the
        live row anything. An exporter that consulted it would fail here.
        """
        from documents.models import DocumentVersion

        DocumentVersion.objects.filter(pk=frozen_package["version"].pk).update(
            sha256_checksum="0" * 64, size_bytes=999999
        )

        archive = _export(frozen_package["package"])
        assert archive.read("files/01-cover/cited.pdf") == FROZEN_BYTES

    def test_the_exact_frozen_version_still_exports(self, frozen_package):
        """Control. The guard must not have made the ordinary path fail."""
        package = frozen_package["package"]
        archive = _export(package)
        assert archive.read("files/01-cover/cited.pdf") == FROZEN_BYTES
        assert json.loads(archive.read("manifest.json")) == package.snapshot.manifest

    def test_export_refuses_a_live_entry_set_smaller_than_the_manifest(self, frozen_package):
        with pytest.raises(ExportError) as excinfo:
            _export(frozen_package["package"], entries=[])
        assert "no longer matches" in str(excinfo.value)

    def test_export_refuses_a_live_entry_the_manifest_does_not_name(
        self, frozen_package, tenant_a, admin_a
    ):
        """An extra entry is refused even though its own bytes are fine. An
        archive containing more than its manifest describes is still wrong."""
        package = frozen_package["package"]
        other = make_package(frozen_package["case"], tenant_a, admin_a, name="Another package")
        stranger = add_entry(
            other,
            tenant_a,
            admin_a,
            make_version(
                make_document(tenant_a, admin_a, title="Other doc"),
                admin_a,
                content=b"stranger",
                version_number=1,
            ),
        )
        entries = [*services.active_entries(package), stranger]

        with pytest.raises(ExportError) as excinfo:
            _export(package, entries=entries)
        assert "no longer matches" in str(excinfo.value)

    def test_export_refuses_an_entry_whose_path_drifted_from_the_manifest(self, frozen_package):
        entries = list(services.active_entries(frozen_package["package"]))
        entries[0].logical_path = "99-somewhere-else"
        with pytest.raises(ExportError) as excinfo:
            _export(frozen_package["package"], entries=entries)
        assert "path" in str(excinfo.value)

    def test_export_refuses_an_entry_whose_filename_drifted_from_the_manifest(self, frozen_package):
        entries = list(services.active_entries(frozen_package["package"]))
        entries[0].export_filename = "renamed.pdf"
        with pytest.raises(ExportError) as excinfo:
            _export(frozen_package["package"], entries=entries)
        assert "filename" in str(excinfo.value)

    def test_export_refuses_an_entry_citing_a_version_the_manifest_does_not(
        self, frozen_package, admin_a
    ):
        v2 = make_version(
            frozen_package["document"], admin_a, content=OTHER_BYTES, version_number=2
        )
        entries = list(services.active_entries(frozen_package["package"]))
        entries[0].document_version = v2
        with pytest.raises(ExportError) as excinfo:
            _export(frozen_package["package"], entries=entries)
        assert "different version" in str(excinfo.value)


# ---------------------------------------------------------------------------
# MAJOR 3 -- revision families
# ---------------------------------------------------------------------------
def _family_of(package):
    return package.family_root_id or package.pk


@pytest.mark.django_db
class TestRevisionFamily:
    def test_a_clone_records_the_family_and_the_root_does_not(
        self, frozen_package, tenant_a, admin_a
    ):
        package = frozen_package["package"]
        clone = services.clone_package(package=package, tenant=tenant_a, actor=admin_a)

        assert package.family_root_id is None, "a founder is its own family"
        assert clone.family_root_id == package.pk
        assert clone.source_package_id == package.pk
        assert clone.revision_number == 2

    def test_the_family_root_stays_the_founder_down_a_chain(
        self, frozen_package, tenant_a, admin_a
    ):
        first = frozen_package["package"]
        second = freeze(
            services.clone_package(package=first, tenant=tenant_a, actor=admin_a),
            tenant_a,
            admin_a,
        )
        third = services.clone_package(package=second, tenant=tenant_a, actor=admin_a)

        assert [first.revision_number, second.revision_number, third.revision_number] == [1, 2, 3]
        assert second.family_root_id == first.pk
        assert third.family_root_id == first.pk, "the root is the founder, not the immediate source"
        assert third.source_package_id == second.pk

    def test_a_renamed_clone_stays_in_the_same_family(self, frozen_package, tenant_a, admin_a):
        """The reason family identity is not the name.

        Under the old `tenant + case + name` key this clone started a second
        family at revision 2 and the next clone of the original collided with
        it. Changing display text must not fork or corrupt a revision family.
        """
        first = frozen_package["package"]
        renamed = services.clone_package(
            package=first, tenant=tenant_a, actor=admin_a, name="A completely different name"
        )
        assert renamed.name == "A completely different name"
        assert renamed.family_root_id == first.pk
        assert renamed.revision_number == 2

        frozen_renamed = freeze(renamed, tenant_a, admin_a)
        onward = services.clone_package(package=frozen_renamed, tenant=tenant_a, actor=admin_a)
        assert onward.family_root_id == first.pk
        assert onward.revision_number == 3

    def test_two_clones_of_one_revision_both_survive_and_take_different_numbers(
        self, frozen_package, tenant_a, admin_a
    ):
        """`source_package` is a tree, not a chain.

        Two alternatives cut from one baseline are both legitimate, and nothing
        in the schema forbids it -- so the model no longer claims otherwise.
        What is linear is the revision number inside the family.
        """
        first = frozen_package["package"]
        left = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)
        right = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)

        assert left.source_package_id == right.source_package_id == first.pk
        assert {left.revision_number, right.revision_number} == {2, 3}
        assert left.family_root_id == right.family_root_id == first.pk

    def test_two_families_number_independently(self, tenant_a, admin_a):
        """Uniqueness is per family, not per tenant."""
        case = make_case(tenant_a, admin_a)
        roots = []
        for label in ("One", "Two"):
            package = make_package(case, tenant_a, admin_a, name=f"Package {label}")
            add_entry(
                package,
                tenant_a,
                admin_a,
                make_version(
                    make_document(tenant_a, admin_a, title=f"Doc {label}"),
                    admin_a,
                    content=f"bytes {label}".encode(),
                    version_number=1,
                ),
            )
            roots.append(freeze(package, tenant_a, admin_a))

        clones = [services.clone_package(package=r, tenant=tenant_a, actor=admin_a) for r in roots]
        assert [c.revision_number for c in clones] == [2, 2]
        assert clones[0].family_root_id != clones[1].family_root_id


@pytest.mark.django_db
class TestRevisionFamilyDatabaseFloor:
    """The service takes a family-root lock. The database does not rely on it."""

    def test_the_database_refuses_a_duplicate_revision_in_a_family(
        self, frozen_package, tenant_a, admin_a
    ):
        first = frozen_package["package"]
        second = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)

        with pytest.raises(IntegrityError), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=first.regulatory_case,
                name="A duplicate revision",
                revision_number=second.revision_number,
                source_package=first,
                family_root=first,
                created_by=admin_a,
            )

    def test_a_raw_cursor_cannot_duplicate_a_revision_either(
        self, frozen_package, tenant_a, admin_a
    ):
        """No manager, no `save()`, no Python. Copies the row `0002` already
        accepted and changes only its identity, so the only thing that can
        refuse it is the index."""
        first = frozen_package["package"]
        second = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)
        table = SubmissionPackage._meta.db_table

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s "
                "AND column_name <> 'id' ORDER BY ordinal_position",
                [table],
            )
            columns = [row[0] for row in cursor.fetchall()]
            assert "family_root_id" in columns

            selected = ", ".join("%s" if c == "public_id" else c for c in columns)
            statement = (
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"SELECT {selected} FROM {table} WHERE id = %s"
            )
            with pytest.raises(IntegrityError), transaction.atomic():
                cursor.execute(statement, [uuid.uuid4(), second.pk])

    def test_the_database_refuses_a_family_root_in_another_tenant(
        self, frozen_package, tenant_a, admin_a, tenant_b, admin_b
    ):
        foreign = make_package(
            make_case(tenant_b, admin_b, title="B case"), tenant_b, admin_b, name="B package"
        )
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=frozen_package["case"],
                name="Cross-tenant family",
                revision_number=2,
                source_package=frozen_package["package"],
                family_root=foreign,
                created_by=admin_a,
            )

    def test_the_database_refuses_a_family_root_on_another_case(
        self, frozen_package, tenant_a, admin_a
    ):
        other_case = make_case(tenant_a, admin_a, title="Another case")
        stranger = make_package(other_case, tenant_a, admin_a, name="Stranger")
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=other_case,
                name="Cross-case family",
                revision_number=2,
                source_package=stranger,
                family_root=frozen_package["package"],
                created_by=admin_a,
            )

    def test_the_database_refuses_a_source_from_a_different_family(
        self, frozen_package, tenant_a, admin_a
    ):
        stranger = make_package(frozen_package["case"], tenant_a, admin_a, name="Unrelated founder")
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=frozen_package["case"],
                name="Mismatched provenance",
                revision_number=2,
                source_package=stranger,
                family_root=frozen_package["package"],
                created_by=admin_a,
            )

    def test_the_database_refuses_provenance_without_a_family(
        self, frozen_package, tenant_a, admin_a
    ):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=frozen_package["case"],
                name="Orphaned copy",
                revision_number=2,
                source_package=frozen_package["package"],
                created_by=admin_a,
            )

    def test_the_database_refuses_a_family_member_without_provenance(
        self, frozen_package, tenant_a, admin_a
    ):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=frozen_package["case"],
                name="Sourceless member",
                revision_number=2,
                family_root=frozen_package["package"],
                created_by=admin_a,
            )

    def test_the_database_refuses_a_founder_that_is_not_revision_one(self, tenant_a, admin_a):
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=make_case(tenant_a, admin_a, title="Fresh case"),
                name="Pretend revision",
                revision_number=7,
                created_by=admin_a,
            )

    def test_the_database_refuses_a_family_root_that_belongs_to_another_family(
        self, frozen_package, tenant_a, admin_a
    ):
        """Families are one level deep by construction: every member names the
        founder, so a member may never be named as a root."""
        first = frozen_package["package"]
        second = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.create(
                tenant=tenant_a,
                regulatory_case=first.regulatory_case,
                name="Nested family",
                revision_number=9,
                source_package=second,
                family_root=second,
                created_by=admin_a,
            )

    def test_the_database_refuses_moving_a_package_between_families(
        self, frozen_package, tenant_a, admin_a
    ):
        """Family membership is provenance, and provenance never moves. A row
        that could change families could change which numbers it collides with,
        and the index would be policing a grouping that shifts underneath it."""
        first = frozen_package["package"]
        second = services.clone_package(package=first, tenant=tenant_a, actor=admin_a)
        other = make_package(frozen_package["case"], tenant_a, admin_a, name="Elsewhere")

        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.filter(pk=second.pk).update(family_root_id=other.pk)


@pytest.mark.django_db(transaction=True)
class TestRevisionFamilyConcurrency:
    """The lock is on the family root, so it holds between clones that share no
    source row."""

    @staticmethod
    def _race(targets, tenant, actor):
        results, errors = [], []
        barrier = threading.Barrier(len(targets))

        def worker(target):
            try:
                barrier.wait(timeout=20)
                results.append(services.clone_package(package=target, tenant=tenant, actor=actor))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(t,)) for t in targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        return results, errors

    def _frozen_root(self, tenant, actor, name="Race package"):
        case = make_case(tenant, actor)
        package = make_package(case, tenant, actor, name=name)
        add_entry(
            package,
            tenant,
            actor,
            make_version(
                make_document(tenant, actor, title=f"{name} doc"),
                actor,
                content=f"{name} bytes".encode(),
                version_number=1,
            ),
        )
        return freeze(package, tenant, actor)

    def test_clones_of_two_different_revisions_cannot_take_the_same_number(self, tenant_a, admin_a):
        """THE regression test for the family race.

        r1 and r2 are different rows, so a lock on the source serialises
        nothing between a clone of r1 and a clone of r2 -- both read the same
        highest revision and both claim it. The family root is the same row for
        both, which is why the lock is taken there.
        """
        first = self._frozen_root(tenant_a, admin_a)
        second = freeze(
            services.clone_package(package=first, tenant=tenant_a, actor=admin_a),
            tenant_a,
            admin_a,
        )
        assert second.revision_number == 2

        results, errors = self._race([first, second], tenant_a, admin_a)

        assert not errors, f"a clone failed outright: {errors}"
        assert len(results) == 2
        revisions = sorted(c.revision_number for c in results)
        assert revisions == [3, 4], f"two clones collided: {revisions}"
        assert {c.family_root_id for c in results} == {first.pk}

    def test_clones_of_the_same_revision_cannot_take_the_same_number(self, tenant_a, admin_a):
        first = self._frozen_root(tenant_a, admin_a, name="Same-source race")
        results, errors = self._race([first, first], tenant_a, admin_a)

        assert not errors, f"a clone failed outright: {errors}"
        revisions = sorted(c.revision_number for c in results)
        assert revisions == [2, 3], f"two clones collided: {revisions}"

    def test_clones_in_different_families_do_not_block_each_other(self, tenant_a, admin_a):
        """The lock is per family, not per tenant: unrelated families both get
        revision 2 and neither waits on the other."""
        left = self._frozen_root(tenant_a, admin_a, name="Left family")
        right = self._frozen_root(tenant_a, admin_a, name="Right family")

        results, errors = self._race([left, right], tenant_a, admin_a)

        assert not errors, f"a clone failed outright: {errors}"
        assert sorted(c.revision_number for c in results) == [2, 2]
        assert {c.family_root_id for c in results} == {left.pk, right.pk}


# ---------------------------------------------------------------------------
# The migration that carries the family
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRevisionFamilyMigration:
    """`0003` is deliberately NOT symmetric the way `0002` is.

    It *replaces* a function `0002` created. A symmetric reverse would drop
    `submission_packages_guard_package_update` and take `0002`'s protection with
    it, so the reverse restores `0002`'s body instead -- and takes that body
    from `0002` rather than retyping it.
    """

    def _module(self):
        import importlib

        return importlib.import_module(
            "submission_packages.migrations.0003_package_revision_family"
        )

    def test_the_reverse_restores_the_original_guard_rather_than_dropping_it(self):
        m = self._module()
        original = importlib.import_module(
            "submission_packages.migrations.0002_package_db_governance"
        ).PACKAGE_UPDATE_FN

        assert m.GOVERNANCE_REVERSE_SQL.endswith(original)
        assert "DROP FUNCTION IF EXISTS submission_packages_guard_package_update" not in (
            m.GOVERNANCE_REVERSE_SQL
        )
        assert "family_root_id" not in original, "0002 must be left untouched"
        assert "family_root_id" in m.PACKAGE_UPDATE_FN_V2

    def test_the_reverse_drops_exactly_what_the_forward_created(self):
        m = self._module()
        created_triggers = {
            line.split()[2]
            for line in m.GOVERNANCE_SQL.splitlines()
            if line.startswith("CREATE TRIGGER")
        }
        dropped_triggers = {
            line.split()[4]
            for line in m.GOVERNANCE_REVERSE_SQL.splitlines()
            if line.startswith("DROP TRIGGER")
        }
        assert created_triggers == dropped_triggers == {"guard_insert_package"}
        assert m.GOVERNANCE_REVERSE_SQL.count("DROP FUNCTION") == 1
        assert "submission_packages_guard_package_insert" in m.GOVERNANCE_REVERSE_SQL

    def test_every_raw_sql_step_declares_a_reverse(self):
        """A `RunSQL` without `reverse_sql` is irreversible by definition, and
        the runbook classifies it C or D on sight."""
        m = self._module()
        raw = [op for op in m.Migration.operations if isinstance(op, migrations.RunSQL)]
        assert len(raw) == 2
        for op in raw:
            assert op.reverse_sql, op.sql[:80]

    def test_the_docstring_states_a_classification_and_its_data_condition(self):
        m = self._module()
        doc = " ".join((m.__doc__ or "").split())
        assert "FORWARD: Class A, **conditional on the data**." in doc
        assert "ROLLBACK: Class A." in doc
        assert "unique_revision_per_package_family" in doc
        # And it does not quietly relax 0001.
        assert "CLASS C -- DATA RESTORE REQUIRED" in doc

    def test_the_constraints_exist_in_the_database(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND conname = %s",
                [SubmissionPackage._meta.db_table, "package_is_not_its_own_family_root"],
            )
            assert cursor.fetchone(), "the check constraint is missing"
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                [SubmissionPackage._meta.db_table, "unique_revision_per_package_family"],
            )
            assert cursor.fetchone(), "the unique index is missing"

    def test_the_backfill_rearms_every_guard_it_disables(self):
        """The derivation cannot run under `guard_update_package` -- a frozen
        package refuses every UPDATE, including one that only completes a column
        that did not exist when it was frozen. It is disabled by name and put
        back, in both directions."""
        m = self._module()
        for sql in (m.BACKFILL_SQL, m.BACKFILL_REVERSE_SQL):
            assert sql.count("DISABLE TRIGGER guard_update_package") == 1
            assert sql.count("ENABLE TRIGGER guard_update_package") == 1
            assert sql.index("DISABLE TRIGGER") < sql.index("UPDATE ")
            assert sql.rindex("ENABLE TRIGGER") > sql.rindex("UPDATE ")
        # Nothing else is ever disarmed.
        assert m.BACKFILL_SQL.count("DISABLE TRIGGER") == 1

    def test_the_guard_is_armed_after_the_migration_has_run(self):
        """Proof the window really closed, read from the catalogue rather than
        from the SQL that claims to close it."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s",
                [SubmissionPackage._meta.db_table, "guard_update_package"],
            )
            row = cursor.fetchone()
        assert row, "guard_update_package is missing entirely"
        assert row[0] == "O", f"guard_update_package is not armed (tgenabled={row[0]!r})"

    def test_a_frozen_package_still_refuses_an_update_after_the_backfill(self, frozen_package):
        """The end-to-end version of the same question."""
        with pytest.raises(DB_REFUSAL), transaction.atomic():
            SubmissionPackage.objects.filter(pk=frozen_package["package"].pk).update(
                name="Renamed after freezing"
            )


@pytest.mark.django_db(transaction=True)
class TestRevisionFamilyBackfill:
    """Runs the migration's own derivation SQL for real.

    Committed rather than wrapped, because the backfill disarms a trigger with
    `ALTER TABLE`, and PostgreSQL refuses that inside a transaction that has
    already fired trigger events on the same table. A real migration has not
    written to the table before this point; a test that builds its fixtures in
    the same transaction has.
    """

    def test_the_backfill_derives_the_same_families_the_service_writes(
        self, frozen_package, tenant_a, admin_a
    ):
        """It must be a no-op over rows the service built -- which is what makes
        rerunning it safe and the reverse lossless."""
        import importlib

        first = frozen_package["package"]
        second = freeze(
            services.clone_package(package=first, tenant=tenant_a, actor=admin_a),
            tenant_a,
            admin_a,
        )
        third = services.clone_package(package=second, tenant=tenant_a, actor=admin_a)
        before = dict(SubmissionPackage.objects.values_list("pk", "family_root_id").order_by("pk"))
        assert before[third.pk] == first.pk

        module = importlib.import_module(
            "submission_packages.migrations.0003_package_revision_family"
        )
        with connection.cursor() as cursor:
            cursor.execute(module.BACKFILL_SQL)

        after = dict(SubmissionPackage.objects.values_list("pk", "family_root_id").order_by("pk"))
        assert after == before

    def test_the_backfill_recomputes_families_it_has_lost(self, frozen_package, tenant_a, admin_a):
        """The claim the rollback classification rests on: `family_root` is
        derived, so wiping it costs nothing a rerun cannot restore. The reverse
        SQL wipes it here and the forward SQL puts it back."""
        import importlib

        first = frozen_package["package"]
        second = freeze(
            services.clone_package(package=first, tenant=tenant_a, actor=admin_a),
            tenant_a,
            admin_a,
        )
        third = services.clone_package(package=second, tenant=tenant_a, actor=admin_a)
        before = dict(SubmissionPackage.objects.values_list("pk", "family_root_id").order_by("pk"))

        module = importlib.import_module(
            "submission_packages.migrations.0003_package_revision_family"
        )
        with connection.cursor() as cursor:
            cursor.execute(module.BACKFILL_REVERSE_SQL)
            assert not SubmissionPackage.objects.filter(family_root__isnull=False).exists()
            cursor.execute(module.BACKFILL_SQL)

        after = dict(SubmissionPackage.objects.values_list("pk", "family_root_id").order_by("pk"))
        assert after == before
        assert after[second.pk] == after[third.pk] == first.pk
