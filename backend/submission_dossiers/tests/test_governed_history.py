"""Section deletion protection and blocker history governance.

Both were MAJOR findings against Milestone 9 from independent review.

**Finding 1.** The app chose governed retirement as the only removal path, but
only enforced it in services. `on_delete=PROTECT` covered a section that already
held a governed relationship; a section with no children, no blockers and no
links had nothing protecting it and could be removed by ORM or by SQL.

**Finding 2.** `DossierSectionBlocker` had a CHECK constraint keeping the two
resolution halves consistent, and nothing else. A CHECK constraint sees one row
at one instant and cannot see the row's previous version, so a resolved blocker
could be reopened, re-resolved, or have its content and provenance rewritten
with no audit row -- and blockers gate readiness directly.

Each guard is proven three ways where all three are reachable: through the
model, through the queryset, and through a raw cursor. Only the last one speaks
for a cascade, a psql session or a migration written by someone in a hurry.

Synthetic data only.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction
from django.utils import timezone

from submission_dossiers import services
from submission_dossiers.models import (
    BlockerSeverity,
    BlockerStatus,
    DossierMutationForbidden,
    DossierSection,
    DossierSectionBlocker,
    Readiness,
    SectionStatus,
)
from submission_dossiers.tests.conftest import make_section

SECTION_TABLE = DossierSection._meta.db_table
BLOCKER_TABLE = DossierSectionBlocker._meta.db_table

DB_ERRORS = (InternalError, ProgrammingError)


def _sql(statement, params=()):
    """Run one statement in its own savepoint.

    A trigger exception poisons the surrounding transaction, and every test here
    asserts on state afterwards. The savepoint keeps the refusal local so the
    assertions that follow can still read.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def _blocker(section, tenant, actor, **kw):
    fields = {"title": "Synthetic blocker", "severity": BlockerSeverity.MEDIUM}
    fields.update(kw)
    return services.create_blocker(section=section, tenant=tenant, actor=actor, **fields)


# ---------------------------------------------------------------------------
# MAJOR 1 -- dossier sections cannot be hard-deleted
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSectionDeletion:
    """Retirement is the only removal path, for every shape of section."""

    def test_bare_active_section_model_delete_is_blocked(self, section_a):
        """The case FK PROTECT never covered: nothing points at this row."""
        assert not section_a.children.exists()
        assert not section_a.blockers.exists()

        with pytest.raises(DossierMutationForbidden) as exc:
            section_a.delete()
        assert "retire" in str(exc.value).lower()
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_bare_active_section_queryset_delete_is_blocked(self, section_a):
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).delete()
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_bare_active_section_sql_delete_is_blocked(self, section_a):
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {SECTION_TABLE} WHERE id = %s", [section_a.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_retired_section_model_delete_is_blocked(self, section_a, tenant_a, doer_a):
        """Retirement is not a staging area for deletion."""
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        section_a.refresh_from_db()
        assert section_a.is_retired

        with pytest.raises(DossierMutationForbidden):
            section_a.delete()
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_retired_section_queryset_delete_is_blocked(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(retired_at__isnull=False).delete()
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_retired_section_sql_delete_is_blocked(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {SECTION_TABLE} WHERE id = %s", [section_a.pk])
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_section_with_blocker_history_cannot_be_deleted(self, section_a, tenant_a, doer_a):
        _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DossierMutationForbidden):
            section_a.delete()
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {SECTION_TABLE} WHERE id = %s", [section_a.pk])
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_child_section_delete_via_related_manager_is_blocked(
        self, dossier_a, tenant_a, doer_a, section_a
    ):
        """`section.children.all().delete()` is a queryset on the same manager."""
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        with pytest.raises(DossierMutationForbidden):
            section_a.children.all().delete()
        assert DossierSection.objects.filter(pk=child.pk).exists()

    def test_unqualified_sql_delete_removes_nothing(self, dossier_a, tenant_a, doer_a, section_a):
        """The blast radius of the obvious mistake is zero rows, not all rows."""
        make_section(dossier_a, tenant_a, doer_a, "2")
        before = DossierSection.objects.count()
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {SECTION_TABLE}")
        assert DossierSection.objects.count() == before

    def test_retirement_remains_the_supported_removal_path(self, section_a, tenant_a, doer_a):
        """The guard must not have made the intended path impossible."""
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        section_a.refresh_from_db()
        assert section_a.retired_at is not None
        assert section_a.retired_by_id == doer_a.pk
        assert DossierSection.objects.filter(pk=section_a.pk).exists()

    def test_section_update_paths_still_work(self, dossier_a, tenant_a, doer_a, section_a):
        """`update()` and `bulk_update()` are deliberately NOT blocked.

        `reorder_section` renumbers a sibling group with `.update()` and
        `recalculate_dossier` writes derived readiness with `.bulk_update()`.
        A blanket queryset ban would have broken the two operations that exist
        to keep the outline consistent -- so only DELETE is closed.
        """
        second = make_section(dossier_a, tenant_a, doer_a, "2")
        services.reorder_section(section=second, tenant=tenant_a, actor=doer_a, sequence=0)
        second.refresh_from_db()
        assert second.sequence == 0

        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, title="Renamed section"
        )
        section_a.refresh_from_db()
        assert section_a.title == "Renamed section"


# ---------------------------------------------------------------------------
# MAJOR 2 -- blocker history is governed
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBlockerDeletion:
    def test_open_blocker_model_delete_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DossierMutationForbidden):
            blocker.delete()
        assert DossierSectionBlocker.objects.filter(pk=blocker.pk).exists()

    def test_open_blocker_queryset_delete_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DossierMutationForbidden):
            DossierSectionBlocker.objects.filter(pk=blocker.pk).delete()
        assert DossierSectionBlocker.objects.filter(pk=blocker.pk).exists()

    def test_open_blocker_sql_delete_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {BLOCKER_TABLE} WHERE id = %s", [blocker.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert DossierSectionBlocker.objects.filter(pk=blocker.pk).exists()

    def test_resolved_blocker_delete_is_blocked(self, section_a, tenant_a, doer_a):
        """Resolution must not become a route to erasure."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        blocker.refresh_from_db()

        with pytest.raises(DossierMutationForbidden):
            blocker.delete()
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {BLOCKER_TABLE} WHERE id = %s", [blocker.pk])
        assert DossierSectionBlocker.objects.filter(pk=blocker.pk).exists()

    def test_unqualified_sql_delete_removes_nothing(self, section_a, tenant_a, doer_a):
        _blocker(section_a, tenant_a, doer_a, title="One")
        _blocker(section_a, tenant_a, doer_a, title="Two")
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {BLOCKER_TABLE}")
        assert DossierSectionBlocker.objects.count() == 2


@pytest.mark.django_db
class TestBlockerContentImmutability:
    """Content and provenance are frozen at creation, in both states."""

    @pytest.mark.parametrize(
        "column,value",
        [
            ("title", "'Rewritten title'"),
            ("description", "'Rewritten description'"),
            ("severity", "'low'"),
            ("public_id", "gen_random_uuid()"),
            ("created_at", "NOW()"),
        ],
    )
    def test_frozen_column_rewrite_is_blocked_by_sql(
        self, section_a, tenant_a, doer_a, column, value
    ):
        blocker = _blocker(section_a, tenant_a, doer_a)
        original = getattr(blocker, column)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {BLOCKER_TABLE} SET {column} = {value} WHERE id = %s", [blocker.pk])
        assert "immutable" in str(exc.value).lower()

        blocker.refresh_from_db()
        assert getattr(blocker, column) == original

    def test_title_rewrite_through_the_orm_is_blocked(self, section_a, tenant_a, doer_a):
        """`save()` bypasses the manager entirely -- this is the path the
        queryset guard cannot see and the trigger must catch."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        blocker.title = "Rewritten through save()"
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                blocker.save()
        blocker.refresh_from_db()
        assert blocker.title == "Synthetic blocker"

    def test_severity_rewrite_through_the_orm_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a, severity=BlockerSeverity.HIGH)
        blocker.severity = BlockerSeverity.LOW
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                blocker.save()
        blocker.refresh_from_db()
        assert blocker.severity == BlockerSeverity.HIGH

    def test_section_swap_is_blocked(self, dossier_a, tenant_a, doer_a, section_a):
        """A blocker moved between sections would move a readiness gate."""
        other = make_section(dossier_a, tenant_a, doer_a, "2")
        blocker = _blocker(section_a, tenant_a, doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET section_id = %s WHERE id = %s",
                [other.pk, blocker.pk],
            )
        assert "immutable" in str(exc.value).lower()
        blocker.refresh_from_db()
        assert blocker.section_id == section_a.pk

    def test_tenant_swap_is_blocked(self, section_a, tenant_a, tenant_b, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET tenant_id = %s WHERE id = %s",
                [tenant_b.pk, blocker.pk],
            )
        blocker.refresh_from_db()
        assert blocker.tenant_id == tenant_a.pk

    def test_created_by_rewrite_is_blocked(self, section_a, tenant_a, doer_a, vp_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET created_by_id = %s WHERE id = %s",
                [vp_a.pk, blocker.pk],
            )
        blocker.refresh_from_db()
        assert blocker.created_by_id == doer_a.pk

    def test_queryset_update_is_blocked(self, section_a, tenant_a, doer_a):
        _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DossierMutationForbidden):
            DossierSectionBlocker.objects.filter(section=section_a).update(title="Wiped")
        assert DossierSectionBlocker.objects.filter(title="Wiped").count() == 0

    def test_queryset_bulk_update_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        blocker.title = "Wiped"
        with pytest.raises(DossierMutationForbidden):
            DossierSectionBlocker.objects.bulk_update([blocker], ["title"])
        assert DossierSectionBlocker.objects.filter(title="Wiped").count() == 0

    def test_unqualified_sql_update_rewrites_nothing(self, section_a, tenant_a, doer_a):
        _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS):
            _sql(f"UPDATE {BLOCKER_TABLE} SET title = 'wiped'")
        assert DossierSectionBlocker.objects.filter(title="wiped").count() == 0


@pytest.mark.django_db
class TestBlockerResolutionLifecycle:
    """OPEN -> RESOLVED, exactly once, then immutable forever."""

    def test_valid_resolution_succeeds(self, section_a, tenant_a, doer_a):
        """The guard must not have made the intended transition impossible."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)

        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.RESOLVED
        assert blocker.resolved_by_id == doer_a.pk
        assert blocker.resolved_at is not None

    def test_resolution_carrying_a_frozen_field_change_is_rejected_whole(
        self, section_a, tenant_a, doer_a
    ):
        """A legal transition must not smuggle an illegal edit alongside it."""
        blocker = _blocker(section_a, tenant_a, doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET status = 'resolved', resolved_at = NOW(), "
                f"resolved_by_id = %s, title = 'Smuggled' WHERE id = %s",
                [doer_a.pk, blocker.pk],
            )
        assert "immutable" in str(exc.value).lower()

        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.OPEN
        assert blocker.title == "Synthetic blocker"

    def test_partial_resolution_stamp_is_rejected(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET status = 'resolved', resolved_at = NOW() "
                f"WHERE id = %s",
                [blocker.pk],
            )
        assert "both resolved_at and resolved_by" in str(exc.value).lower()

        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET status = 'resolved', resolved_by_id = %s "
                f"WHERE id = %s",
                [doer_a.pk, blocker.pk],
            )

        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.OPEN
        assert blocker.resolved_at is None
        assert blocker.resolved_by_id is None

    def test_reopen_is_blocked(self, section_a, tenant_a, doer_a):
        """The CHECK constraint alone permits this: the reopened row is
        internally consistent. Only a trigger can see where it came from."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET status = 'open', resolved_at = NULL, "
                f"resolved_by_id = NULL WHERE id = %s",
                [blocker.pk],
            )
        assert "already resolved" in str(exc.value).lower()

        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.RESOLVED
        assert blocker.resolved_at is not None

    def test_reopen_through_the_orm_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        blocker.refresh_from_db()

        blocker.status = BlockerStatus.OPEN
        blocker.resolved_at = None
        blocker.resolved_by = None
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                blocker.save()

        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.RESOLVED

    def test_second_resolution_is_blocked(self, section_a, tenant_a, doer_a, vp_a):
        """Re-resolving would rewrite who resolved it and when."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        blocker.refresh_from_db()
        first_resolver, first_at = blocker.resolved_by_id, blocker.resolved_at

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET resolved_by_id = %s, resolved_at = NOW() "
                f"WHERE id = %s",
                [vp_a.pk, blocker.pk],
            )
        assert "already resolved" in str(exc.value).lower()

        blocker.refresh_from_db()
        assert blocker.resolved_by_id == first_resolver
        assert blocker.resolved_at == first_at

    def test_content_rewrite_after_resolution_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)

        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET title = 'Rewritten after the fact' WHERE id = %s",
                [blocker.pk],
            )
        assert "already resolved" in str(exc.value).lower()
        blocker.refresh_from_db()
        assert blocker.title == "Synthetic blocker"

    def test_updated_at_alone_is_not_a_backdoor(self, section_a, tenant_a, doer_a):
        """An open row touched with nothing but `updated_at` is still refused:
        the only legal UPDATE is the resolution itself."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {BLOCKER_TABLE} SET updated_at = NOW() WHERE id = %s", [blocker.pk])
        assert "open -> resolved" in str(exc.value).lower()

    def test_status_change_to_an_unknown_value_is_blocked(self, section_a, tenant_a, doer_a):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DB_ERRORS):
            _sql(
                f"UPDATE {BLOCKER_TABLE} SET status = 'withdrawn' WHERE id = %s",
                [blocker.pk],
            )
        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.OPEN

    def test_service_refuses_a_second_resolution_before_the_database_has_to(
        self, section_a, tenant_a, doer_a
    ):
        """The service still gives the caller a clean 409 rather than a 500 --
        the trigger is the floor, not the user-facing behaviour."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        blocker.refresh_from_db()
        with pytest.raises(services.DossierLocked):
            services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)

    def test_resolution_still_recalculates_readiness(self, section_a, tenant_a, doer_a):
        """End-to-end: the governed transition must still move the gate it
        exists to control."""
        blocker = _blocker(section_a, tenant_a, doer_a)
        section_a.refresh_from_db()
        assert section_a.readiness == Readiness.NOT_READY

        services.update_section(
            section=section_a,
            tenant=tenant_a,
            actor=doer_a,
            status=SectionStatus.COMPLETE,
        )
        section_a.refresh_from_db()
        assert section_a.readiness == Readiness.NOT_READY, "open blocker still gates it"

        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        section_a.refresh_from_db()
        assert section_a.readiness == Readiness.READY


# ---------------------------------------------------------------------------
# Installation and coverage
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGovernanceTriggerInstallationAndCoverage:
    #: Mirrors submission_dossiers/0003. The coverage test below fails the build
    #: if the two ever drift apart.
    BLOCKER_FROZEN = {
        "id",
        "public_id",
        "tenant_id",
        "section_id",
        "title",
        "description",
        "severity",
        "created_by_id",
        "created_at",
    }
    BLOCKER_TRANSITION = {"status", "resolved_by_id", "resolved_at", "updated_at"}

    def test_section_delete_trigger_is_installed(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT trigger_name, event_manipulation FROM information_schema.triggers "
                "WHERE event_object_table = %s",
                [SECTION_TABLE],
            )
            rows = set(cur.fetchall())
        assert ("no_delete_dossier_section", "DELETE") in rows

    def test_blocker_triggers_are_installed(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT trigger_name, event_manipulation FROM information_schema.triggers "
                "WHERE event_object_table = %s",
                [BLOCKER_TABLE],
            )
            rows = set(cur.fetchall())
        assert ("no_delete_section_blocker", "DELETE") in rows
        assert ("guard_update_section_blocker", "UPDATE") in rows

    def test_guard_functions_exist(self):
        with connection.cursor() as cur:
            for fn in (
                "submission_dossiers_prevent_section_delete",
                "submission_dossiers_prevent_blocker_delete",
                "submission_dossiers_guard_blocker_update",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_blocker_guard_covers_every_column(self):
        """An enumerate-by-name guard is sound only while the enumeration is
        complete. Add a column and forget the trigger and it would be silently
        rewritable during a resolution -- so this fails the build instead."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                [BLOCKER_TABLE],
            )
            actual = {row[0] for row in cur.fetchall()}
        accounted = self.BLOCKER_FROZEN | self.BLOCKER_TRANSITION
        assert actual == accounted, (
            "submission_dossiers/0003 lists blocker columns by name -- update the trigger "
            f"and this test together. Unaccounted: {actual - accounted}; "
            f"stale: {accounted - actual}"
        )

    def test_section_table_has_no_columns_that_imply_a_delete_path(self):
        """The section guard is unconditional, so it needs no column list. What
        it does need is for `retired_at`/`retired_by_id` to still exist: they are
        the only supported removal path, and losing them would leave the table
        with no way to retire anything."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                [SECTION_TABLE],
            )
            actual = {row[0] for row in cur.fetchall()}
        assert {"retired_at", "retired_by_id"} <= actual


# ---------------------------------------------------------------------------
# Isolation and audit for the governed paths
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGovernedHistoryIsolationAndAudit:
    def test_cross_tenant_blocker_resolution_is_refused(
        self, section_a, tenant_a, tenant_b, doer_a, doer_b
    ):
        blocker = _blocker(section_a, tenant_a, doer_a)
        with pytest.raises(DossierSectionBlocker.DoesNotExist):
            services.resolve_blocker(blocker=blocker, tenant=tenant_b, actor=doer_b)
        blocker.refresh_from_db()
        assert blocker.status == BlockerStatus.OPEN

    def test_refused_deletion_emits_no_audit_event(self, section_a, tenant_a, doer_a):
        """A refusal is not an event: nothing happened."""
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        with pytest.raises(DossierMutationForbidden):
            section_a.delete()
        with pytest.raises(DossierMutationForbidden):
            DossierSection.objects.filter(pk=section_a.pk).delete()
        assert AuditEvent.objects.count() == before

    def test_resolution_records_no_blocker_free_text(self, section_a, tenant_a, doer_a):
        """Blocker title and description describe the submission and must not
        be copied into an audit row, which has different retention."""
        from audit.models import AuditEvent

        blocker = _blocker(
            section_a,
            tenant_a,
            doer_a,
            title="Confidential blocker title",
            description="Confidential blocker description",
        )
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)

        blob = " ".join(str(e.payload) for e in AuditEvent.objects.all())
        assert "Confidential blocker title" not in blob
        assert "Confidential blocker description" not in blob
        assert str(blocker.public_id) in blob

    def test_resolved_at_is_the_database_truth_not_a_client_claim(
        self, section_a, tenant_a, doer_a
    ):
        blocker = _blocker(section_a, tenant_a, doer_a)
        before = timezone.now()
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        blocker.refresh_from_db()
        assert blocker.resolved_at >= before
