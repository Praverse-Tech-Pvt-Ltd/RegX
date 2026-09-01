"""Direct-ORM mutation of `DossierSection` cannot bypass the service layer.

MAJOR finding from independent review of PR #37.

`0003` closed section DELETE and deliberately left UPDATE open, because
`reorder_section` needs `.update()` and `recalculate_dossier` needs
`.bulk_update()`. The same two doors let any caller rewrite `tenant_id`,
`dossier_id`, `parent_id`, `readiness` or the retirement stamps directly --
skipping hierarchy validation, tenant scoping, cycle prevention, derived
readiness, terminal-dossier gating and audit in a single call.

The fix is a **sanctioned window** (`submission_dossiers.governance`) rather than
a blanket ban, so the four legitimate operations keep working while everything
else is refused. See `0004`.

Two properties are tested here, and both matter:

  * every bypass is refused -- through the queryset, through `save()`, and
    through a raw cursor that never touches a line of Python;
  * every sanctioned operation still works -- a guard that breaks reorder or
    readiness would be a worse outcome than the hole it closed.

Synthetic data only.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from submission_dossiers import governance, services
from submission_dossiers.models import (
    MAX_SECTION_DEPTH,
    DossierMutationForbidden,
    DossierSection,
    Readiness,
    SectionStatus,
)
from submission_dossiers.tests.conftest import make_section

SECTION_TABLE = DossierSection._meta.db_table
DB_ERRORS = (InternalError, ProgrammingError)


def _sql(statement, params=()):
    """One statement in its own savepoint, so a refusal stays local and the
    assertions afterwards can still read."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def _reload(section):
    section.refresh_from_db()
    return section


# ---------------------------------------------------------------------------
# The two layers agree about what the guard is
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGuardWiring:
    def test_python_and_sql_constants_agree(self):
        """The trigger reads a parameter name that Python writes. If the two
        drift, the guard silently degrades to refusing everything -- or worse,
        to permitting everything -- so they are asserted equal here."""
        import importlib

        migration = importlib.import_module(
            "submission_dossiers.migrations.0004_section_update_governance"
        )
        assert migration.OP_SETTING == governance.SECTION_OP_SETTING
        assert migration.MAX_DEPTH == MAX_SECTION_DEPTH
        assert migration.SECTION_TABLE == SECTION_TABLE

    def test_triggers_and_functions_are_installed(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT trigger_name, event_manipulation FROM information_schema.triggers "
                "WHERE event_object_table = %s",
                [SECTION_TABLE],
            )
            rows = set(cur.fetchall())
        assert ("guard_update_dossier_section", "UPDATE") in rows
        assert ("guard_insert_dossier_section", "INSERT") in rows

        with connection.cursor() as cur:
            for fn in (
                "submission_dossiers_guard_section_update",
                "submission_dossiers_guard_section_insert",
                "submission_dossiers_check_section_parent",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_every_section_column_is_classified(self):
        """`0004` enumerates columns by name. An enumerate-by-name guard is
        sound only while the enumeration is complete, so a column added later
        without being classified fails the build here rather than becoming
        quietly writable."""
        frozen = {"id", "public_id", "tenant_id", "dossier_id", "created_by_id", "created_at"}
        by_update = {
            "parent_id",
            "section_code",
            "title",
            "description",
            "notes",
            "required",
            "status",
            "owner_id",
            "due_date",
        }
        by_reorder = {"sequence"}
        by_recalculate = {"readiness", "readiness_reason"}
        by_retire = {"retired_at", "retired_by_id"}
        always_allowed = {"updated_at"}

        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                [SECTION_TABLE],
            )
            actual = {row[0] for row in cur.fetchall()}

        accounted = frozen | by_update | by_reorder | by_recalculate | by_retire | always_allowed
        assert actual == accounted, (
            "submission_dossiers/0004 lists section columns by name -- update the trigger "
            f"and this test together. Unaccounted: {actual - accounted}; "
            f"stale: {accounted - actual}"
        )

    def test_the_window_is_closed_by_default(self):
        assert governance.current_operation() is None

    def test_windows_do_not_nest(self):
        with transaction.atomic():
            with governance.section_write(governance.OP_REORDER):
                with pytest.raises(governance.SectionWriteForbidden):
                    with governance.section_write(governance.OP_UPDATE):
                        pass

    def test_an_unknown_operation_is_refused(self):
        with transaction.atomic(), pytest.raises(ValueError):
            with governance.section_write("sudo"):
                pass

    def test_the_window_closes_even_when_the_body_raises(self):
        with transaction.atomic():
            with pytest.raises(RuntimeError):
                with governance.section_write(governance.OP_REORDER):
                    raise RuntimeError("boom")
            assert governance.current_operation() is None


# ---------------------------------------------------------------------------
# Identity and provenance: frozen under every window and none
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFrozenIdentityAndProvenance:
    def test_queryset_update_is_refused_outright(self, section_a):
        """The public manager writes nothing at all, so the obvious bypass never
        even reaches the database."""
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(title="Rewritten")
        assert _reload(section_a).title != "Rewritten"

    def test_queryset_bulk_update_is_refused_outright(self, section_a):
        section_a.title = "Rewritten"
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.bulk_update([section_a], ["title"])
        assert _reload(section_a).title != "Rewritten"

    def test_direct_orm_tenant_mutation_is_blocked(self, section_a, tenant_b):
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(tenant_id=tenant_b.pk)

        section_a.tenant = tenant_b
        with pytest.raises(DossierMutationForbidden):
            section_a.save()

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET tenant_id = %s WHERE id = %s",
                [tenant_b.pk, section_a.pk],
            )
        assert "immutable" in str(exc.value).lower()
        assert _reload(section_a).tenant_id != tenant_b.pk

    def test_direct_orm_dossier_mutation_is_blocked(self, section_a, dossier_b):
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(dossier_id=dossier_b.pk)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET dossier_id = %s WHERE id = %s",
                [dossier_b.pk, section_a.pk],
            )
        assert "immutable" in str(exc.value).lower()
        assert _reload(section_a).dossier_id != dossier_b.pk

    def test_direct_orm_public_id_mutation_is_blocked(self, section_a):
        original = section_a.public_id
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {SECTION_TABLE} SET public_id = gen_random_uuid() WHERE id = %s",
                [section_a.pk],
            )
        assert _reload(section_a).public_id == original

    def test_direct_orm_created_by_mutation_is_blocked(self, section_a, vp_a):
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {SECTION_TABLE} SET created_by_id = %s WHERE id = %s",
                [vp_a.pk, section_a.pk],
            )
        assert _reload(section_a).created_by_id != vp_a.pk

    def test_direct_orm_created_at_mutation_is_blocked(self, section_a):
        original = section_a.created_at
        with pytest.raises(DB_ERRORS):
            _sql(f"UPDATE {SECTION_TABLE} SET created_at = NOW() WHERE id = %s", [section_a.pk])
        assert _reload(section_a).created_at == original

    def test_frozen_columns_are_refused_even_inside_a_sanctioned_window(self, section_a, tenant_b):
        """The window is a declaration of intent, not an authorisation. Opening
        the widest one and then writing a frozen column is refused exactly as
        firmly as writing it with no window at all."""
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_UPDATE):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET tenant_id = %s WHERE id = %s",
                        [tenant_b.pk, section_a.pk],
                    )
        assert "immutable" in str(exc.value).lower()
        assert _reload(section_a).tenant_id != tenant_b.pk


# ---------------------------------------------------------------------------
# Derived readiness stays derived below the serializer layer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReadinessIsDerivedAtEveryLayer:
    def test_direct_orm_readiness_mutation_is_blocked(self, section_a):
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(readiness=Readiness.READY)

        section_a.readiness = Readiness.READY
        with pytest.raises(DossierMutationForbidden):
            section_a.save()

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET readiness = 'ready' WHERE id = %s",
                [section_a.pk],
            )
        assert "only be updated through" in str(exc.value).lower()
        assert _reload(section_a).readiness == Readiness.NOT_READY

    def test_direct_orm_readiness_reason_mutation_is_blocked(self, section_a):
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(readiness_reason="ready")
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {SECTION_TABLE} SET readiness_reason = 'ready' WHERE id = %s",
                [section_a.pk],
            )
        assert _reload(section_a).readiness_reason != "ready"

    def test_readiness_cannot_ride_along_with_a_metadata_update(self, section_a):
        """A legal `update` window must not smuggle a readiness claim."""
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_UPDATE):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET title = 'Edited', readiness = 'ready' "
                        f"WHERE id = %s",
                        [section_a.pk],
                    )
        assert "readiness" in str(exc.value).lower()
        assert _reload(section_a).readiness == Readiness.NOT_READY

    def test_readiness_cannot_ride_along_with_a_reorder(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_REORDER):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET sequence = 5, readiness = 'ready' "
                        f"WHERE id = %s",
                        [section_a.pk],
                    )
        assert "only sequence" in str(exc.value).lower()
        assert _reload(section_a).readiness == Readiness.NOT_READY

    def test_a_recalculation_window_may_not_touch_anything_else(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_RECALCULATE):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET readiness = 'ready', title = 'Edited' "
                        f"WHERE id = %s",
                        [section_a.pk],
                    )
        assert "readiness and readiness_reason" in str(exc.value).lower()
        assert _reload(section_a).title != "Edited"


# ---------------------------------------------------------------------------
# Hierarchy: the trigger re-checks what Python checks
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHierarchyAtTheDatabase:
    def _force_parent(self, section, parent_id):
        """Write parent_id under the one window that permits it, so the
        hierarchy rules are exercised rather than the allow-list."""
        with transaction.atomic(), governance.section_write(governance.OP_UPDATE):
            with connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {SECTION_TABLE} SET parent_id = %s WHERE id = %s",
                    [parent_id, section.pk],
                )

    def test_direct_orm_parent_mutation_without_a_window_is_blocked(
        self, dossier_a, tenant_a, doer_a, section_a
    ):
        other = make_section(dossier_a, tenant_a, doer_a, "2")
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=other.pk).update(parent_id=section_a.pk)

        other.parent = section_a
        with pytest.raises(DossierMutationForbidden):
            other.save()

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET parent_id = %s WHERE id = %s",
                [section_a.pk, other.pk],
            )
        assert "only be updated through" in str(exc.value).lower()
        assert _reload(other).parent_id is None

    def test_self_parent_is_blocked_at_the_database(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section_a, section_a.pk)
        assert "its own parent" in str(exc.value).lower()
        assert _reload(section_a).parent_id is None

    def test_cross_dossier_parent_is_blocked_at_the_database(
        self, section_a, dossier_b, tenant_b, doer_b
    ):
        foreign = make_section(dossier_b, tenant_b, doer_b, "X")
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section_a, foreign.pk)
        assert "different dossier" in str(exc.value).lower()
        assert _reload(section_a).parent_id is None

    def test_cross_tenant_parent_is_blocked_at_the_database(
        self, section_a, dossier_b, tenant_b, doer_b
    ):
        """Cross-tenant is also cross-dossier here, so the message proves which
        rule fired: the tenant check must not be dead code hidden behind it."""
        foreign = make_section(dossier_b, tenant_b, doer_b, "X")
        with connection.cursor() as cur:
            # Ask the hierarchy function directly with a matching dossier id, so
            # only the tenant differs and only the tenant rule can refuse.
            with pytest.raises(DB_ERRORS) as exc:
                with transaction.atomic():
                    cur.execute(
                        "SELECT submission_dossiers_check_section_parent(%s, %s, %s, %s)",
                        [section_a.pk, foreign.pk, foreign.dossier_id, section_a.tenant_id],
                    )
        assert "different tenant" in str(exc.value).lower()

    def test_cycle_is_blocked_at_the_database(self, dossier_a, tenant_a, doer_a, section_a):
        """The classic corruption: reparent an ancestor under its own
        descendant. Python refuses it; so must the database, because Python is
        not in the path of a raw cursor."""
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        grandchild = make_section(dossier_a, tenant_a, doer_a, "1.1.1", parent=child)

        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section_a, grandchild.pk)
        assert "cycle" in str(exc.value).lower()
        assert _reload(section_a).parent_id is None

    def test_retired_parent_is_blocked_at_the_database(
        self, dossier_a, tenant_a, doer_a, section_a
    ):
        retired = make_section(dossier_a, tenant_a, doer_a, "2")
        services.retire_section(section=retired, tenant=tenant_a, actor=doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section_a, retired.pk)
        assert "retired" in str(exc.value).lower()

    def test_nonexistent_parent_is_blocked_at_the_database(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            self._force_parent(section_a, 2_000_000_000)
        assert "does not exist" in str(exc.value).lower()

    def test_insert_with_a_cross_tenant_parent_is_blocked(
        self, dossier_a, tenant_a, doer_a, dossier_b, tenant_b, doer_b
    ):
        """The symmetric hole: a raw INSERT planting a section under a parent
        in another tenant."""
        foreign = make_section(dossier_b, tenant_b, doer_b, "X")
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"INSERT INTO {SECTION_TABLE} "
                f"(public_id, created_at, updated_at, tenant_id, dossier_id, parent_id, "
                f" section_code, title, description, notes, sequence, required, status, "
                f" readiness, readiness_reason, created_by_id) "
                f"VALUES (gen_random_uuid(), NOW(), NOW(), %s, %s, %s, "
                f" 'smuggled', 'Smuggled', '', '', 99, true, 'not_started', "
                f" 'not_ready', 'no_supporting_work', %s)",
                [tenant_a.pk, dossier_a.pk, foreign.pk, doer_a.pk],
            )
        assert "different dossier" in str(exc.value).lower()
        assert not DossierSection.objects.filter(section_code="smuggled").exists()


# ---------------------------------------------------------------------------
# Retirement is one-way
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRetirementIsOneWay:
    def test_direct_orm_unretire_is_blocked(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        section_a.refresh_from_db()
        stamped_at, stamped_by = section_a.retired_at, section_a.retired_by_id

        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(retired_at=None, retired_by=None)

        section_a.retired_at = None
        section_a.retired_by = None
        with pytest.raises(DossierMutationForbidden):
            section_a.save()

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {SECTION_TABLE} SET retired_at = NULL, retired_by_id = NULL WHERE id = %s",
                [section_a.pk],
            )
        assert "retired" in str(exc.value).lower()

        section_a.refresh_from_db()
        assert section_a.retired_at == stamped_at
        assert section_a.retired_by_id == stamped_by

    def test_a_retired_section_is_frozen_entirely(self, section_a, tenant_a, doer_a):
        """One rule covers unretire, re-retire and post-retirement edits."""
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        for column, value in (("title", "'Edited'"), ("status", "'complete'"), ("sequence", "7")):
            with pytest.raises(DB_ERRORS) as exc:
                with transaction.atomic(), governance.section_write(governance.OP_UPDATE):
                    with connection.cursor() as cur:
                        cur.execute(
                            f"UPDATE {SECTION_TABLE} SET {column} = {value} WHERE id = %s",
                            [section_a.pk],
                        )
            assert "retired" in str(exc.value).lower()

    def test_partial_retirement_stamp_is_refused(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_RETIRE):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET retired_at = NOW() WHERE id = %s",
                        [section_a.pk],
                    )
        assert "both retired_at and retired_by" in str(exc.value).lower()
        assert _reload(section_a).retired_at is None

    def test_a_retirement_window_may_not_edit_content(self, section_a, doer_a):
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic(), governance.section_write(governance.OP_RETIRE):
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE {SECTION_TABLE} SET retired_at = NOW(), retired_by_id = %s, "
                        f"title = 'Smuggled' WHERE id = %s",
                        [doer_a.pk, section_a.pk],
                    )
        assert "only the retirement stamps" in str(exc.value).lower()
        assert _reload(section_a).retired_at is None


# ---------------------------------------------------------------------------
# The sanctioned operations still work
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSanctionedOperationsStillWork:
    """A guard that broke reorder or readiness would be worse than the hole."""

    def test_sanctioned_update_section(self, section_a, tenant_a, doer_a):
        services.update_section(
            section=section_a,
            tenant=tenant_a,
            actor=doer_a,
            title="Renamed through the service",
            notes="Some notes",
        )
        section_a.refresh_from_db()
        assert section_a.title == "Renamed through the service"
        assert section_a.notes == "Some notes"

    def test_sanctioned_parent_change(self, dossier_a, tenant_a, doer_a, section_a):
        child = make_section(dossier_a, tenant_a, doer_a, "2")
        services.update_section(section=child, tenant=tenant_a, actor=doer_a, parent=section_a)
        assert _reload(child).parent_id == section_a.pk

    def test_sanctioned_reorder(self, dossier_a, tenant_a, doer_a, section_a):
        second = make_section(dossier_a, tenant_a, doer_a, "2")
        third = make_section(dossier_a, tenant_a, doer_a, "3")
        services.reorder_section(section=third, tenant=tenant_a, actor=doer_a, sequence=0)

        order = list(
            DossierSection.objects.filter(dossier=dossier_a)
            .order_by("sequence", "id")
            .values_list("section_code", flat=True)
        )
        assert order[0] == "3"
        assert set(order) == {"1", "2", "3"}
        assert _reload(section_a).title  # untouched by the renumber
        assert _reload(second).section_code == "2"

    def test_sanctioned_readiness_recalculation(self, section_a, tenant_a, doer_a):
        assert section_a.readiness == Readiness.NOT_READY
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _reload(section_a).readiness == Readiness.READY

    def test_sanctioned_retire(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        section_a.refresh_from_db()
        assert section_a.retired_at is not None
        assert section_a.retired_by_id == doer_a.pk

    def test_sanctioned_create_section(self, dossier_a, tenant_a, doer_a, section_a):
        """INSERT is untouched by the window: creation is not the bypass."""
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        assert child.pk is not None
        assert child.parent_id == section_a.pk

    def test_the_api_path_end_to_end_still_works(self, client_doer_a, section_a):
        r = client_doer_a.patch(
            f"/api/regx/v1/dossier-sections/{section_a.public_id}/",
            {"title": "Renamed through the API"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert _reload(section_a).title == "Renamed through the API"

    def test_terminal_dossier_still_refuses_structural_change(
        self, dossier_a, tenant_a, doer_a, section_a
    ):
        """The window must not have become a silent bypass of the terminal
        gate: that check lives above it and still fires first."""
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        services.complete_dossier(dossier=dossier_a, tenant=tenant_a, actor=doer_a)

        with pytest.raises(services.DossierLocked):
            services.update_section(
                section=section_a, tenant=tenant_a, actor=doer_a, title="After completion"
            )
        with pytest.raises(services.DossierLocked):
            services.reorder_section(section=section_a, tenant=tenant_a, actor=doer_a, sequence=0)
        with pytest.raises(services.DossierLocked):
            services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        assert _reload(section_a).title != "After completion"


# ---------------------------------------------------------------------------
# The window does not leak
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestWindowDoesNotLeak:
    def test_a_window_cannot_be_opened_outside_a_transaction(self):
        """`SET LOCAL` outside a transaction applies to a single implicit
        transaction and is gone before the next statement, so the trigger would
        not see it where it is needed. Opening a window there is refused rather
        than becoming a silently useless no-op.

        This needs `transaction=True`: an ordinary `django_db` test body is
        itself wrapped in an atomic block, so the assertion would be vacuous.
        """
        assert not transaction.get_connection().in_atomic_block
        with pytest.raises(governance.SectionWriteForbidden) as exc:
            with governance.section_write(governance.OP_REORDER):
                pass
        assert "inside a transaction" in str(exc.value)
        assert governance.current_operation() is None

    def test_the_declaration_does_not_survive_the_transaction(self, section_a):
        """`SET LOCAL` is transaction-scoped. If it leaked, one sanctioned
        service call would leave the door open for every later statement on a
        pooled connection."""
        with transaction.atomic():
            with governance.section_write(governance.OP_REORDER):
                with connection.cursor() as cur:
                    cur.execute("SELECT current_setting(%s, true)", [governance.SECTION_OP_SETTING])
                    assert cur.fetchone()[0] == governance.OP_REORDER

        with connection.cursor() as cur:
            cur.execute("SELECT current_setting(%s, true)", [governance.SECTION_OP_SETTING])
            assert cur.fetchone()[0] in (None, "")

        # And the guard is live again straight away.
        with pytest.raises(DB_ERRORS):
            with connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {SECTION_TABLE} SET sequence = 42 WHERE id = %s", [section_a.pk]
                )

    def test_a_service_call_leaves_no_open_window(self, section_a, tenant_a, doer_a):
        services.update_section(section=section_a, tenant=tenant_a, actor=doer_a, title="Renamed")
        assert governance.current_operation() is None
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).update(title="After the call")
        assert _reload(section_a).title == "Renamed"
