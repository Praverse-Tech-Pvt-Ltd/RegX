"""Immutability, tenant isolation, permission projection and path security.

Every guard here is tested at the layer that actually holds it. The service
layer is checked through the service; the database floor is checked by going
around the service entirely -- `objects.create()`, `governed.update()` and raw
SQL -- because a guard that only exists in Python is not a floor, and
`Model.save()` resolves through `_base_manager` rather than the restricted
manager anyway.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import pytest
from django.db import ProgrammingError, connection, transaction
from django.db.utils import InternalError

from submission_packages import services
from submission_packages.governance import PackageMutationForbidden
from submission_packages.models import (
    PackageStatus,
    SubmissionPackage,
    SubmissionPackageEntry,
    SubmissionPackageSnapshot,
)
from submission_packages.paths import InvalidLogicalPath, collision_key, normalize_logical_path
from submission_packages.tests.conftest import (
    PKG_API,
    add_entry,
    freeze,
    make_case,
    make_document,
    make_package,
    make_version,
)

DB_REFUSED = (InternalError, ProgrammingError)


@pytest.fixture
def frozen_package(tenant_a, admin_a):
    case = make_case(tenant_a, admin_a)
    document = make_document(tenant_a, admin_a)
    version = make_version(document, admin_a, content=b"frozen payload", version_number=1)
    package = make_package(case, tenant_a, admin_a)
    entry = add_entry(package, tenant_a, admin_a, version, logical_path="01-cover")
    package = freeze(package, tenant_a, admin_a)
    return {"package": package, "entry": entry, "version": version, "case": case}


# ---------------------------------------------------------------------------
# Frozen immutability
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFrozenImmutability:
    def test_the_service_refuses_every_structural_change(self, frozen_package, tenant_a, admin_a):
        package = frozen_package["package"]
        document = make_document(tenant_a, admin_a, title="Late")
        late = make_version(document, admin_a, content=b"late", version_number=1)

        with pytest.raises(services.PackageLocked):
            add_entry(package, tenant_a, admin_a, late)
        with pytest.raises(services.PackageLocked):
            services.remove_entry(entry=frozen_package["entry"], tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.PackageLocked):
            services.reorder_entry(
                entry=frozen_package["entry"], tenant=tenant_a, actor=admin_a, sequence=5
            )
        with pytest.raises(services.PackageLocked):
            services.update_package(package=package, tenant=tenant_a, actor=admin_a, name="New")

    def test_the_database_refuses_a_direct_orm_status_rewrite(self, frozen_package):
        """`governed.update()` is the service layer's own door. The trigger
        still polices it, which is the point of having a floor."""
        package = frozen_package["package"]
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackage.governed.filter(pk=package.pk).update(status=PackageStatus.DRAFT)
        package.refresh_from_db()
        assert package.status == PackageStatus.FROZEN

    def test_the_database_refuses_a_bare_save(self, frozen_package):
        """`Model.save()` resolves through `_base_manager`, not `objects`, so no
        manager restriction can cover it. Only the trigger can."""
        package = frozen_package["package"]
        package.name = "Renamed behind the service"
        with pytest.raises(DB_REFUSED), transaction.atomic():
            package.save()
        package.refresh_from_db()
        assert package.name != "Renamed behind the service"

    def test_the_database_refuses_repointing_an_entry_at_different_bytes(
        self, frozen_package, tenant_a, admin_a
    ):
        """The single most dangerous rewrite: a frozen manifest that says one
        thing while the entry points at another."""
        other = make_document(tenant_a, admin_a, title="Substitute")
        substitute = make_version(other, admin_a, content=b"substitute", version_number=1)

        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.governed.filter(pk=frozen_package["entry"].pk).update(
                document_version=substitute
            )
        frozen_package["entry"].refresh_from_db()
        assert frozen_package["entry"].document_version_id == frozen_package["version"].pk

    def test_the_database_refuses_rewriting_a_logical_path(self, frozen_package):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.governed.filter(pk=frozen_package["entry"].pk).update(
                logical_path="somewhere-else"
            )

    def test_the_database_refuses_deleting_an_entry(self, frozen_package):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.governed.filter(pk=frozen_package["entry"].pk).delete()

    def test_a_package_with_content_cannot_be_deleted(self, frozen_package):
        """`on_delete=PROTECT` on the entry and snapshot FKs answers first, which
        is a stronger guard than the trigger and arrives earlier."""
        from django.db.models.deletion import ProtectedError

        with pytest.raises(ProtectedError), transaction.atomic():
            SubmissionPackage.governed.filter(pk=frozen_package["package"].pk).delete()

    def test_an_empty_package_still_cannot_be_deleted(self, tenant_a, admin_a):
        """Nothing references it, so PROTECT has nothing to say. The trigger is
        what refuses, which is exactly what a floor is for."""
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackage.governed.filter(pk=package.pk).delete()
        assert SubmissionPackage.objects.filter(pk=package.pk).exists()

    def test_the_manager_refuses_delete_before_the_database_is_asked(self, frozen_package):
        with pytest.raises(PackageMutationForbidden):
            SubmissionPackage.objects.filter(pk=frozen_package["package"].pk).delete()
        with pytest.raises(PackageMutationForbidden):
            frozen_package["package"].delete()
        with pytest.raises(PackageMutationForbidden):
            frozen_package["entry"].delete()

    def test_a_frozen_manifest_refuses_update_and_delete(self, frozen_package):
        snapshot = frozen_package["package"].snapshot
        with pytest.raises(PackageMutationForbidden):
            SubmissionPackageSnapshot.objects.filter(pk=snapshot.pk).update(entry_count=99)
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageSnapshot.objects.filter(pk=snapshot.pk).using("default")._raw_delete(
                "default"
            )

    def test_raw_sql_cannot_rewrite_a_frozen_manifest(self, frozen_package):
        """Around the ORM entirely: a psql session, a migration, a cursor."""
        snapshot = frozen_package["package"].snapshot
        table = SubmissionPackageSnapshot._meta.db_table
        with pytest.raises(DB_REFUSED), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET manifest_checksum = %s WHERE id = %s",
                ["0" * 64, snapshot.pk],
            )
        snapshot.refresh_from_db()
        assert snapshot.manifest_checksum == frozen_package["package"].manifest_checksum

    def test_raw_sql_cannot_rewrite_a_frozen_package(self, frozen_package):
        package = frozen_package["package"]
        table = SubmissionPackage._meta.db_table
        with pytest.raises(DB_REFUSED), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET status = 'draft' WHERE id = %s",
                [package.pk],
            )

    def test_a_cited_document_version_cannot_be_deleted(self, frozen_package):
        """Two layers: the FK is PROTECT, and a `DeletionProtectionRegistry`
        checker is registered from `apps.py` -- the same pair `workflows` uses
        for evidence."""
        from documents.deletion_protection import DocumentVersionDeleteForbidden

        with pytest.raises(DocumentVersionDeleteForbidden):
            frozen_package["version"].delete()


# ---------------------------------------------------------------------------
# Insert coherence -- the M10 lesson
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInsertCoherence:
    def test_an_entry_cannot_be_inserted_with_a_foreign_tenant(
        self, tenant_a, admin_a, tenant_b, admin_b
    ):
        """Freezing a row that was never checked on the way in preserves
        whatever was written, not the truth."""
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        b_doc = make_document(tenant_b, admin_b)
        b_version = make_version(b_doc, admin_b, content=b"b", version_number=1)

        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.objects.create(
                tenant=tenant_a,
                package=package,
                document_version=b_version,
                logical_path="",
                export_filename="x.pdf",
                added_by=admin_a,
            )

    def test_an_entry_cannot_be_inserted_into_another_tenants_package(
        self, tenant_a, admin_a, tenant_b, admin_b
    ):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        doc = make_document(tenant_a, admin_a)
        version = make_version(doc, admin_a, content=b"a", version_number=1)

        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.objects.create(
                tenant=tenant_b,
                package=package,
                document_version=version,
                logical_path="",
                export_filename="x.pdf",
                added_by=admin_b,
            )

    def test_an_entry_cannot_link_a_section_from_another_case(self, tenant_a, admin_a):
        from submission_dossiers import services as ds

        case_one = make_case(tenant_a, admin_a, title="One")
        case_two = make_case(tenant_a, admin_a, title="Two")
        dossier = ds.create_dossier(
            case=case_two, tenant=tenant_a, actor=admin_a, title="Other case dossier"
        )
        section = ds.create_section(
            dossier=dossier, tenant=tenant_a, actor=admin_a, section_code="A", title="A"
        )

        package = make_package(case_one, tenant_a, admin_a)
        doc = make_document(tenant_a, admin_a)
        version = make_version(doc, admin_a, content=b"a", version_number=1)

        # The service refuses it...
        with pytest.raises(services.InvalidTarget):
            add_entry(
                package,
                tenant_a,
                admin_a,
                version,
                dossier_section_public_id=section.public_id,
            )
        # ...and so does the database, for anything that skips the service.
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.objects.create(
                tenant=tenant_a,
                package=package,
                document_version=version,
                dossier_section=section,
                logical_path="",
                export_filename="x.pdf",
                added_by=admin_a,
            )

    def test_an_entry_cannot_be_inserted_into_a_frozen_package(
        self, frozen_package, tenant_a, admin_a
    ):
        doc = make_document(tenant_a, admin_a, title="After the fact")
        version = make_version(doc, admin_a, content=b"late", version_number=1)
        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageEntry.objects.create(
                tenant=tenant_a,
                package=frozen_package["package"],
                document_version=version,
                logical_path="",
                export_filename="late.pdf",
                added_by=admin_a,
            )

    def test_a_snapshot_cannot_claim_a_count_the_package_does_not_have(self, tenant_a, admin_a):
        from django.utils import timezone

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        doc = make_document(tenant_a, admin_a)
        version = make_version(doc, admin_a, content=b"a", version_number=1)
        add_entry(package, tenant_a, admin_a, version)

        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageSnapshot.objects.create(
                tenant=tenant_a,
                package=package,
                manifest={"entries": []},
                manifest_checksum="a" * 64,
                entry_count=99,  # the package has one
                frozen_by=admin_a,
                frozen_at=timezone.now(),
            )

    def test_a_snapshot_checksum_must_look_like_sha256(self, tenant_a, admin_a):
        from django.utils import timezone

        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        doc = make_document(tenant_a, admin_a)
        version = make_version(doc, admin_a, content=b"a", version_number=1)
        add_entry(package, tenant_a, admin_a, version)

        with pytest.raises(DB_REFUSED), transaction.atomic():
            SubmissionPackageSnapshot.objects.create(
                tenant=tenant_a,
                package=package,
                manifest={"entries": []},
                manifest_checksum="not-a-digest",
                entry_count=1,
                frozen_by=admin_a,
                frozen_at=timezone.now(),
            )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    @pytest.fixture
    def loud_tenant_b(self, tenant_b, admin_b):
        """Tenant B, full of packages. If any reaches A, it is obvious."""
        case = make_case(tenant_b, admin_b, title="B case")
        for i in range(5):
            doc = make_document(tenant_b, admin_b, title=f"B doc {i}")
            version = make_version(doc, admin_b, content=f"b{i}".encode(), version_number=1)
            package = make_package(case, tenant_b, admin_b, name=f"B package {i}")
            add_entry(package, tenant_b, admin_b, version)
        return tenant_b

    def test_a_package_from_another_tenant_is_404(
        self, client_admin_a, tenant_b, admin_b, loud_tenant_b
    ):
        b_package = SubmissionPackage.objects.filter(tenant=tenant_b).first()
        response = client_admin_a.get(f"{PKG_API}/{b_package.public_id}/")
        assert response.status_code == 404

    def test_the_case_package_list_shows_only_this_tenant(
        self, client_admin_a, tenant_a, admin_a, loud_tenant_b
    ):
        case = make_case(tenant_a, admin_a, title="A case")
        make_package(case, tenant_a, admin_a, name="A only")
        response = client_admin_a.get(f"/api/regx/v1/regulatory-cases/{case.public_id}/packages/")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "A only"
        assert "B package" not in str(response.data)

    def test_the_service_refuses_a_foreign_package(
        self, tenant_a, admin_a, tenant_b, loud_tenant_b
    ):
        """The service gate, not merely the view's filter."""
        b_package = SubmissionPackage.objects.filter(tenant=tenant_b).first()
        with pytest.raises(services.InvalidTarget):
            services.validate_package(package=b_package, tenant=tenant_a)
        with pytest.raises(services.InvalidTarget):
            services.freeze_package(package=b_package, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.InvalidTarget):
            services.clone_package(package=b_package, tenant=tenant_a, actor=admin_a)

    def test_a_document_version_from_another_tenant_cannot_be_added(
        self, tenant_a, admin_a, tenant_b, admin_b
    ):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        b_doc = make_document(tenant_b, admin_b)
        b_version = make_version(b_doc, admin_b, content=b"b", version_number=1)

        with pytest.raises(services.InvalidTarget):
            add_entry(package, tenant_a, admin_a, b_version)


# ---------------------------------------------------------------------------
# Permission projection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissionProjection:
    def test_package_permission_is_not_document_permission(
        self, client_support_a, support_a, tenant_a, frozen_package
    ):
        """PLATFORM_SUPPORT holds `submission_packages.view` and no
        `documents.view`. The entry exists because the package is theirs to see;
        the document does not, because it is not."""
        from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
        from documents.permissions import has_document_permission

        assert not has_document_permission(support_a, tenant_a, DOCUMENTS_VIEW)

        response = client_support_a.get(f"{PKG_API}/{frozen_package['package'].public_id}/")
        assert response.status_code == 200
        entries = response.data["entries"]
        assert len(entries) == 1, "the entry itself is visible"
        assert entries[0]["document"] is None, "the document is not"

        body = str(response.data)
        assert frozen_package["version"].sha256_checksum not in body
        assert "Synthetic document" not in body

    def test_an_admin_sees_the_document_block(self, client_admin_a, frozen_package):
        response = client_admin_a.get(f"{PKG_API}/{frozen_package['package'].public_id}/")
        document = response.data["entries"][0]["document"]
        assert document is not None
        assert document["checksum_sha256"] == frozen_package["version"].sha256_checksum
        assert document["version_number"] == 1

    def test_adding_an_entry_needs_document_permission_too(self, tenant_a, support_a, admin_a):
        """Two gates, checked independently. The service refuses even though the
        caller may manage entries, because it may not read documents."""
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        doc = make_document(tenant_a, admin_a)
        version = make_version(doc, admin_a, content=b"a", version_number=1)

        with pytest.raises(services.InvalidTarget):
            services.add_entry(
                package=package,
                tenant=tenant_a,
                actor=support_a,
                document_version_public_id=version.public_id,
            )

    def test_export_is_refused_entirely_without_document_permission(
        self, client_support_a, support_a, tenant_a, frozen_package, monkeypatch
    ):
        """Not a shorter archive. A ZIP silently missing files looks complete to
        whoever receives it, which makes a partial export worse than none.

        The caller is given `submission_packages.export` for this test and still
        denied `documents.view`. No shipped role has that shape -- DOER,
        REVIEWER, VP and TENANT_ADMIN all hold both, and PLATFORM_SUPPORT holds
        neither -- so without granting the first permission the request is
        refused by the export gate and the document gate is never reached.

        That is not hypothetical tidiness. The first version of this test
        asserted only `403 or 404`, and deleting the document gate entirely left
        it green: it was proving that PLATFORM_SUPPORT cannot export, which was
        never in question.
        """
        from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
        from documents.permissions import has_document_permission
        from submission_packages import permissions as pkg_permissions

        role = "platform_support"
        granted = dict(pkg_permissions.ROLE_PERMISSIONS)
        granted[role] = [*granted[role], pkg_permissions.PERM_EXPORT]
        monkeypatch.setattr(pkg_permissions, "ROLE_PERMISSIONS", granted)

        assert pkg_permissions.has_package_permission(
            support_a, tenant_a, pkg_permissions.PERM_EXPORT
        ), "precondition: the export gate now passes"
        assert not has_document_permission(support_a, tenant_a, DOCUMENTS_VIEW), (
            "precondition: the document gate must still be the one that refuses"
        )

        response = client_support_a.get(f"{PKG_API}/{frozen_package['package'].public_id}/export/")
        assert response.status_code == 403
        assert response.get("Content-Type") != "application/zip"
        assert "documents" in str(response.data).lower()

    def test_an_authorised_caller_does_get_the_archive(self, client_admin_a, frozen_package):
        """The control. Without it the test above could pass because export is
        broken for everyone."""
        response = client_admin_a.get(f"{PKG_API}/{frozen_package['package'].public_id}/export/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"

    def test_creating_a_package_needs_case_permission_too(self, tenant_a, admin_a, support_a):
        from regulatory_cases.permissions import PERM_VIEW as CASE_VIEW
        from regulatory_cases.permissions import has_case_permission

        case = make_case(tenant_a, admin_a)
        if has_case_permission(support_a, tenant_a, CASE_VIEW):
            pytest.skip("this role holds regulatory_cases.view in this repo")
        with pytest.raises(services.InvalidTarget):
            services.create_package(
                case_public_id=case.public_id, tenant=tenant_a, actor=support_a, name="X"
            )


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------
class TestLogicalPathSecurity:
    """No database needed: this is pure normalisation."""

    @pytest.mark.parametrize(
        "raw",
        [
            "../x",
            "a/../../x",
            "a/../x",
            "/x",
            "C:\\x",
            "c:/x",
            "\\\\server\\share",
            "a\\b",
            "x\x00y",
            "a/\x01b",
            "CON",
            "con.pdf",
            "NUL/x",
            "a/COM1/b",
            "trailing.",
            "a /b",
            "a./b",
            "a/b./c",
        ],
    )
    def test_dangerous_paths_are_refused(self, raw):
        with pytest.raises(InvalidLogicalPath):
            normalize_logical_path(raw)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("", ""),
            (None, ""),
            ("a/b", "a/b"),
            ("a//b", "a/b"),
            ("a/./b", "a/b"),
            ("a/b/", "a/b"),
            ("  a/b  ", "a/b"),
            # Whitespace around the WHOLE path is a typo and is stripped; a
            # trailing space inside a segment is what Windows would silently
            # rewrite, and that is refused above.
            ("trailing ", "trailing"),
            ("a/b ", "a/b"),
            ("01-cover/supporting", "01-cover/supporting"),
        ],
    )
    def test_safe_paths_normalise(self, raw, expected):
        assert normalize_logical_path(raw) == expected

    def test_depth_and_length_are_bounded(self):
        with pytest.raises(InvalidLogicalPath):
            normalize_logical_path("/".join(["a"] * 50))
        with pytest.raises(InvalidLogicalPath):
            normalize_logical_path("a" * 500)
        with pytest.raises(InvalidLogicalPath):
            normalize_logical_path("a" * 200 + "/b")

    def test_case_differences_collide(self):
        """macOS and Windows are case-insensitive, so `Docs/` and `docs/` are the
        same directory once extracted."""
        assert collision_key("Docs", "A.pdf") == collision_key("docs", "a.PDF")

    def test_unicode_spellings_collide(self):
        """NFC and NFD render identically and would overwrite each other."""
        composed = "caf\u00e9"  # café
        decomposed = "cafe\u0301"  # cafe + combining acute
        assert normalize_logical_path(decomposed) == composed
        assert collision_key(composed, "x.pdf") == collision_key(decomposed, "x.pdf")

    def test_sharp_s_folds(self):
        """`lower()` would leave these unequal; `casefold()` does not."""
        assert collision_key("STRASSE", "x.pdf") == collision_key("stra\u00dfe", "x.pdf")

    def test_the_reason_is_a_code_not_an_echo(self):
        """Echoing an attacker-supplied path into a message or a log is how a
        traversal attempt becomes a log-injection."""
        with pytest.raises(InvalidLogicalPath) as exc:
            normalize_logical_path("../../etc/passwd")
        assert exc.value.code == "path_traversal"
        assert "passwd" not in str(exc.value)


@pytest.mark.django_db
class TestDuplicatePaths:
    def test_two_entries_cannot_export_to_the_same_path(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        one = make_version(
            make_document(tenant_a, admin_a, title="One"),
            admin_a,
            content=b"one",
            version_number=1,
            filename="same.pdf",
        )
        two = make_version(
            make_document(tenant_a, admin_a, title="Two"),
            admin_a,
            content=b"two",
            version_number=1,
            filename="same.pdf",
        )
        add_entry(package, tenant_a, admin_a, one, logical_path="docs")
        with pytest.raises(services.PackageIntegrityError):
            add_entry(package, tenant_a, admin_a, two, logical_path="docs")

    def test_a_case_only_difference_still_collides(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        one = make_version(
            make_document(tenant_a, admin_a, title="One"),
            admin_a,
            content=b"one",
            version_number=1,
            filename="same.pdf",
        )
        two = make_version(
            make_document(tenant_a, admin_a, title="Two"),
            admin_a,
            content=b"two",
            version_number=1,
            filename="SAME.pdf",
        )
        add_entry(package, tenant_a, admin_a, one, logical_path="Docs")
        with pytest.raises(services.PackageIntegrityError):
            add_entry(package, tenant_a, admin_a, two, logical_path="docs")

    def test_the_same_version_cannot_be_added_twice(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"one", version_number=1
        )
        add_entry(package, tenant_a, admin_a, version, logical_path="a")
        with pytest.raises((services.PackageIntegrityError, Exception)):
            add_entry(package, tenant_a, admin_a, version, logical_path="b")

    def test_a_removed_entry_frees_its_path(self, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        package = make_package(case, tenant_a, admin_a)
        version = make_version(
            make_document(tenant_a, admin_a), admin_a, content=b"one", version_number=1
        )
        entry = add_entry(package, tenant_a, admin_a, version, logical_path="a")
        services.remove_entry(entry=entry, tenant=tenant_a, actor=admin_a)
        again = add_entry(package, tenant_a, admin_a, version, logical_path="a")
        assert again.pk != entry.pk
