"""Database-level governance: direct ORM and raw SQL cannot bypass the service.

The service layer produces clean 4xx answers and audit rows. It is not the
guarantee. `Model.save()` resolves through `_base_manager` -- a plain `Manager`
Django auto-creates, not `objects` -- so restricting the public manager cannot
cover it, and a raw cursor never runs a line of Python.

**There is no sanctioned window here, deliberately.** Milestone 9 needed one
because a dossier section is legitimately mutable by four operations with four
column sets. A blueprint version's own `status` is the discriminator instead:
DRAFT is editable, ACTIVE and RETIRED are frozen. The trigger reads that status
directly, which cannot be forgotten, cannot be left open, and needs no Python
cooperation. A window would add a mechanism without adding a guarantee.

Synthetic data only.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from dossier_blueprints import services
from dossier_blueprints.models import (
    MAX_BLUEPRINT_DEPTH,
    BlueprintMutationForbidden,
    BlueprintVersionStatus,
    DossierBlueprintSection,
    DossierBlueprintVersion,
)
from dossier_blueprints.tests.conftest import make_section

VERSION_TABLE = DossierBlueprintVersion._meta.db_table
SECTION_TABLE = DossierBlueprintSection._meta.db_table
DB_ERRORS = (InternalError, ProgrammingError)


def _sql(statement, params=()):
    """One statement in its own savepoint, so a refusal stays local and the
    assertions afterwards can still read."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def _reload(obj):
    obj.refresh_from_db()
    return obj


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGuardWiring:
    def test_python_and_sql_constants_agree(self):
        import importlib

        migration = importlib.import_module(
            "dossier_blueprints.migrations.0002_blueprint_db_governance"
        )
        assert migration.MAX_DEPTH == MAX_BLUEPRINT_DEPTH
        assert migration.VERSION_TABLE == VERSION_TABLE
        assert migration.SECTION_TABLE == SECTION_TABLE

    def test_triggers_are_installed(self):
        expected = {
            VERSION_TABLE: {
                ("guard_update_blueprint_version", "UPDATE"),
                ("no_delete_blueprint_version", "DELETE"),
            },
            SECTION_TABLE: {
                ("guard_update_blueprint_section", "UPDATE"),
                ("guard_insert_blueprint_section", "INSERT"),
                ("no_delete_blueprint_section", "DELETE"),
            },
        }
        with connection.cursor() as cur:
            for table, wanted in expected.items():
                cur.execute(
                    "SELECT trigger_name, event_manipulation FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                rows = set(cur.fetchall())
                assert wanted <= rows, f"{table}: missing {wanted - rows}"

    def test_guard_functions_exist(self):
        with connection.cursor() as cur:
            for fn in (
                "dossier_blueprints_guard_version_update",
                "dossier_blueprints_prevent_version_delete",
                "dossier_blueprints_guard_section_update",
                "dossier_blueprints_guard_section_insert",
                "dossier_blueprints_prevent_section_delete",
                "dossier_blueprints_prevent_provenance_change",
                "dossier_blueprints_check_section_parent",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_every_version_column_is_classified(self):
        """`0002` enumerates columns by name; the enumeration must stay complete
        or a column added later becomes quietly writable."""
        frozen = {
            "id",
            "public_id",
            "tenant_id",
            "blueprint_id",
            "version_number",
            "created_by_id",
            "created_at",
            "supersedes_id",
        }
        lifecycle = {
            "status",
            "activated_at",
            "activated_by_id",
            "retired_at",
            "retired_by_id",
            "updated_at",
        }
        draft_editable = {"notes"}

        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                [VERSION_TABLE],
            )
            actual = {row[0] for row in cur.fetchall()}
        accounted = frozen | lifecycle | draft_editable
        assert actual == accounted, (
            "dossier_blueprints/0002 lists version columns by name -- update the trigger "
            f"and this test together. Unaccounted: {actual - accounted}; "
            f"stale: {accounted - actual}"
        )

    def test_every_section_column_is_classified(self):
        frozen = {"id", "public_id", "tenant_id", "blueprint_version_id", "created_at"}
        draft_editable = {
            "parent_id",
            "section_code",
            "title",
            "description",
            "sequence",
            "required",
            "default_due_offset_days",
            "updated_at",
        }
        retirement = {"retired_at", "retired_by_id"}

        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                [SECTION_TABLE],
            )
            actual = {row[0] for row in cur.fetchall()}
        accounted = frozen | draft_editable | retirement
        assert actual == accounted, (
            "dossier_blueprints/0002 lists section columns by name -- update the trigger "
            f"and this test together. Unaccounted: {actual - accounted}; "
            f"stale: {accounted - actual}"
        )


# ---------------------------------------------------------------------------
# Version immutability
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestVersionImmutability:
    def test_public_queryset_writes_nothing(self, draft_a):
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintVersion.objects.filter(pk=draft_a.pk).update(notes="x")
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintVersion.objects.filter(pk=draft_a.pk).delete()
        assert _reload(draft_a).notes == ""

    def test_version_number_is_frozen(self, draft_a):
        """If this moved, the race guard in `create_version` could be undone
        after the fact."""
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {VERSION_TABLE} SET version_number = 99 WHERE id = %s", [draft_a.pk])
        assert "immutable" in str(exc.value).lower()
        assert _reload(draft_a).version_number == 1

    def test_tenant_and_blueprint_are_frozen(self, draft_a, tenant_b):
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {VERSION_TABLE} SET tenant_id = %s WHERE id = %s",
                [tenant_b.pk, draft_a.pk],
            )
        assert _reload(draft_a).tenant_id != tenant_b.pk

    def test_active_version_content_is_frozen(self, active_a):
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {VERSION_TABLE} SET notes = 'edited' WHERE id = %s", [active_a.pk])
        assert "immutable" in str(exc.value).lower()
        assert _reload(active_a).notes == ""

    def test_active_version_cannot_be_returned_to_draft(self, active_a):
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {VERSION_TABLE} SET status = 'draft', activated_at = NULL, "
                f"activated_by_id = NULL WHERE id = %s",
                [active_a.pk],
            )
        assert "only be retired" in str(exc.value).lower()
        assert _reload(active_a).status == BlueprintVersionStatus.ACTIVE

    def test_activation_stamps_cannot_be_rewritten(self, active_a, doer_a):
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {VERSION_TABLE} SET activated_by_id = %s, status = 'retired', "
                f"retired_at = NOW(), retired_by_id = %s WHERE id = %s",
                [doer_a.pk, doer_a.pk, active_a.pk],
            )
        assert _reload(active_a).activated_by_id != doer_a.pk

    def test_retired_version_refuses_every_update(self, active_a, tenant_a, admin_a):
        services.retire_version(version=active_a, tenant=tenant_a, actor=admin_a)
        for column, value in (("notes", "'x'"), ("status", "'active'")):
            with pytest.raises(DB_ERRORS) as exc:
                _sql(
                    f"UPDATE {VERSION_TABLE} SET {column} = {value} WHERE id = %s",
                    [active_a.pk],
                )
            assert "retired" in str(exc.value).lower()

    def test_partial_activation_stamp_refused(self, populated_draft_a):
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {VERSION_TABLE} SET status = 'active' WHERE id = %s",
                [populated_draft_a.pk],
            )
        assert "both activated_at and activated_by" in str(exc.value).lower()
        assert _reload(populated_draft_a).status == BlueprintVersionStatus.DRAFT

    def test_version_delete_is_refused(self, draft_a):
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {VERSION_TABLE} WHERE id = %s", [draft_a.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert DossierBlueprintVersion.objects.filter(pk=draft_a.pk).exists()

    def test_unqualified_delete_removes_nothing(self, draft_a, active_a):
        before = DossierBlueprintVersion.objects.count()
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {VERSION_TABLE}")
        assert DossierBlueprintVersion.objects.count() == before


# ---------------------------------------------------------------------------
# Section immutability
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSectionImmutability:
    def test_public_queryset_writes_nothing(self, draft_a, tenant_a, admin_a):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintSection.objects.filter(pk=section.pk).update(title="Edited")
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintSection.objects.bulk_update([section], ["title"])
        assert _reload(section).title != "Edited"

    def test_active_version_sections_refuse_orm_save(self, active_a):
        """`save()` bypasses the manager entirely -- the path only the trigger
        can see."""
        section = active_a.sections.first()
        section.title = "Edited after activation"
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                section.save()
        assert "immutable" in str(exc.value).lower()
        assert _reload(section).title != "Edited after activation"

    def test_active_version_sections_refuse_raw_sql(self, active_a):
        section = active_a.sections.first()
        for column, value in (
            ("title", "'Edited'"),
            ("section_code", "'ZZ'"),
            ("sequence", "999"),
            ("required", "false"),
            ("description", "'Edited'"),
        ):
            with pytest.raises(DB_ERRORS) as exc:
                _sql(
                    f"UPDATE {SECTION_TABLE} SET {column} = {value} WHERE id = %s",
                    [section.pk],
                )
            assert "immutable" in str(exc.value).lower(), column

    def test_retired_version_sections_refuse_raw_sql(self, active_a, tenant_a, admin_a):
        services.retire_version(version=active_a, tenant=tenant_a, actor=admin_a)
        section = active_a.sections.first()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {SECTION_TABLE} SET title = 'Edited' WHERE id = %s", [section.pk])
        assert "immutable" in str(exc.value).lower()

    def test_no_inserting_into_a_published_version(self, active_a, tenant_a, doer_a):
        """The bypass that matters: adding a section after activation would
        change what every future dossier gets, with no version bump."""
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"INSERT INTO {SECTION_TABLE} "
                f"(public_id, created_at, updated_at, tenant_id, blueprint_version_id, "
                f" parent_id, section_code, title, description, sequence, required) "
                f"VALUES (gen_random_uuid(), NOW(), NOW(), %s, %s, NULL, 'SMUGGLED', "
                f" 'Smuggled', '', 900, true)",
                [tenant_a.pk, active_a.pk],
            )
        assert "cannot add a section" in str(exc.value).lower()
        assert not DossierBlueprintSection.objects.filter(section_code="SMUGGLED").exists()

    def test_section_identity_is_frozen_even_in_a_draft(self, draft_a, tenant_a, admin_a, draft_b):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET blueprint_version_id = %s WHERE id = %s",
                [draft_b.pk, section.pk],
            )
        assert "identity is immutable" in str(exc.value).lower()
        assert _reload(section).blueprint_version_id == draft_a.pk

    def test_section_delete_is_refused(self, draft_a, tenant_a, admin_a):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {SECTION_TABLE} WHERE id = %s", [section.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert DossierBlueprintSection.objects.filter(pk=section.pk).exists()

    def test_retired_section_is_frozen(self, draft_a, tenant_a, admin_a):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        services.retire_section(section=section, tenant=tenant_a, actor=admin_a)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {SECTION_TABLE} SET title = 'Edited' WHERE id = %s", [section.pk])
        assert "retired" in str(exc.value).lower()

    def test_draft_sections_remain_editable(self, draft_a, tenant_a, admin_a):
        """The guard must not have made the intended path impossible."""
        section = make_section(draft_a, tenant_a, admin_a, "A")
        services.update_section(
            section=section, tenant=tenant_a, actor=admin_a, title="Edited in draft"
        )
        assert _reload(section).title == "Edited in draft"


# ---------------------------------------------------------------------------
# Hierarchy at the database
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHierarchyAtTheDatabase:
    def _force_parent(self, section, parent_id):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                f"UPDATE {SECTION_TABLE} SET parent_id = %s WHERE id = %s",
                [parent_id, section.pk],
            )

    def test_self_parent_blocked(self, draft_a, tenant_a, admin_a):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section, section.pk)
        assert "its own parent" in str(exc.value).lower()

    def test_cycle_blocked(self, draft_a, tenant_a, admin_a):
        a = make_section(draft_a, tenant_a, admin_a, "A")
        b = make_section(draft_a, tenant_a, admin_a, "A.1", parent=a)
        c = make_section(draft_a, tenant_a, admin_a, "A.1.1", parent=b)
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(a, c.pk)
        assert "cycle" in str(exc.value).lower()
        assert _reload(a).parent_id is None

    def test_cross_version_parent_blocked(self, blueprint_a, draft_a, tenant_a, admin_a):
        other = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        foreign = make_section(other, tenant_a, admin_a, "X")
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section, foreign.pk)
        assert "different version" in str(exc.value).lower()

    def test_cross_tenant_parent_blocked(
        self, draft_a, tenant_a, admin_a, draft_b, tenant_b, admin_b
    ):
        """Cross-tenant is also cross-version here, so the hierarchy function is
        called directly with a matching version id: only the tenant differs, so
        only the tenant rule can refuse. Otherwise the check would be dead code
        hidden behind the version check."""
        foreign = make_section(draft_b, tenant_b, admin_b, "X")
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    "SELECT dossier_blueprints_check_section_parent(%s, %s, %s, %s)",
                    [section.pk, foreign.pk, foreign.blueprint_version_id, section.tenant_id],
                )
        assert "different tenant" in str(exc.value).lower()

    def test_retired_parent_blocked(self, draft_a, tenant_a, admin_a):
        parent = make_section(draft_a, tenant_a, admin_a, "A")
        section = make_section(draft_a, tenant_a, admin_a, "B")
        services.retire_section(section=parent, tenant=tenant_a, actor=admin_a)
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section, parent.pk)
        assert "retired" in str(exc.value).lower()

    def test_insert_with_a_cross_version_parent_blocked(
        self, blueprint_a, draft_a, tenant_a, admin_a
    ):
        other = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        foreign = make_section(other, tenant_a, admin_a, "X")
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"INSERT INTO {SECTION_TABLE} "
                f"(public_id, created_at, updated_at, tenant_id, blueprint_version_id, "
                f" parent_id, section_code, title, description, sequence, required) "
                f"VALUES (gen_random_uuid(), NOW(), NOW(), %s, %s, %s, 'SMUGGLED', "
                f" 'Smuggled', '', 900, true)",
                [tenant_a.pk, draft_a.pk, foreign.pk],
            )
        assert "different version" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    def test_concurrent_version_creation_cannot_duplicate_a_number(
        self, blueprint_a, tenant_a, admin_a
    ):
        """Two threads racing on `max(version_number) + 1`.

        The blueprint row lock serialises them. The unique constraint is the
        floor underneath: even if the lock were removed, one side would fail
        rather than both succeed with the same number.
        """
        import threading

        from django.db import connections

        results, errors = [], []

        def worker():
            try:
                results.append(
                    services.create_version(
                        blueprint=blueprint_a, tenant=tenant_a, actor=admin_a
                    ).version_number
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        assert sorted(results) == [1, 2, 3, 4]
        numbers = list(
            DossierBlueprintVersion.objects.filter(blueprint=blueprint_a).values_list(
                "version_number", flat=True
            )
        )
        assert sorted(numbers) == [1, 2, 3, 4]
        assert len(numbers) == len(set(numbers))

    def test_concurrent_activation_leaves_exactly_one_active(self, blueprint_a, tenant_a, admin_a):
        import threading

        from django.db import connections

        versions = []
        for index in range(3):
            version = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
            make_section(version, tenant_a, admin_a, f"S{index}")
            versions.append(version)

        errors = []

        def worker(version):
            try:
                services.activate_version(version=version, tenant=tenant_a, actor=admin_a)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(v,)) for v in versions]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        active = DossierBlueprintVersion.objects.filter(
            blueprint=blueprint_a, status=BlueprintVersionStatus.ACTIVE
        )
        assert active.count() == 1, f"expected exactly one ACTIVE, got {active.count()}"

    def test_a_section_cannot_be_added_while_activation_is_in_flight(
        self, populated_draft_a, tenant_a, admin_a
    ):
        """Activation locks the version; a section write takes the same lock,
        so it either lands before the publish or meets a frozen version."""
        services.activate_version(version=populated_draft_a, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.BlueprintLocked):
            make_section(populated_draft_a, tenant_a, admin_a, "LATE")
        assert not DossierBlueprintSection.objects.filter(section_code="LATE").exists()


# ---------------------------------------------------------------------------
# Query cost
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestQueryCost:
    """Invariance, not an absolute. An absolute encodes today's fixed overhead
    and breaks on unrelated changes; what must never change is the shape."""

    def _count(self, client, url):
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
            assert response.status_code == 200
        return len(ctx.captured_queries)

    def test_blueprint_list_is_flat_in_the_number_of_blueprints(
        self, client_admin_a, tenant_a, admin_a
    ):
        from dossier_blueprints.tests.conftest import BLUEPRINT_API

        counts = {}
        made = 0
        for target in (1, 20, 100):
            while made < target:
                made += 1
                services.create_blueprint(
                    tenant=tenant_a, actor=admin_a, name=f"Outline {made:04d}"
                )
            counts[target] = self._count(client_admin_a, f"{BLUEPRINT_API}/")

        assert counts[1] == counts[20] == counts[100], counts

    def test_version_detail_is_flat_in_the_number_of_sections(
        self, client_admin_a, blueprint_a, tenant_a, admin_a
    ):
        from dossier_blueprints.tests.conftest import VERSION_API

        counts = {}
        for target in (1, 20, 100, 500):
            version = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
            rows = [
                DossierBlueprintSection(
                    tenant=tenant_a,
                    blueprint_version=version,
                    section_code=f"S{i:04d}",
                    title=f"Section {i}",
                    sequence=i * 10,
                )
                for i in range(target)
            ]
            DossierBlueprintSection.objects.bulk_create(rows)
            counts[target] = self._count(client_admin_a, f"{VERSION_API}/{version.public_id}/")

        assert counts[1] == counts[20] == counts[100] == counts[500], counts

    def test_instantiation_cost_grows_linearly_not_quadratically(
        self, blueprint_a, tenant_a, admin_a, case_a
    ):
        """`create_section` from the dossier service recalculates readiness on
        every call, which would be quadratic here. Instantiation creates rows
        directly and recalculates once, so doubling the sections must not
        quadruple the queries."""
        from django.test.utils import CaptureQueriesContext

        measured = {}
        for size in (10, 20):
            version = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
            for i in range(size):
                make_section(version, tenant_a, admin_a, f"S{i:03d}")
            services.activate_version(version=version, tenant=tenant_a, actor=admin_a)

            with CaptureQueriesContext(connection) as ctx:
                services.instantiate_version(
                    version=version,
                    tenant=tenant_a,
                    actor=admin_a,
                    case_public_id=case_a.public_id,
                    title=f"From {size}",
                )
            measured[size] = len(ctx.captured_queries)

        ratio = measured[20] / measured[10]
        assert ratio < 2.6, f"instantiation looks super-linear: {measured}"
