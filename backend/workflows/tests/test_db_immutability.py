"""Database-level immutability for WorkflowTransition.

The model and queryset guards prove the ORM refuses. These prove the *database*
refuses, which is what matters for a governed history table: raw SQL, a psql
session, or any future code path that bypasses the manager is still stopped.

Mirrors the protection `audit/0001_initial.py` gives `audit_auditevent`.
PostgreSQL only -- SQLite could not express this, and is prohibited anyway.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from workflows import services
from workflows.models import WorkflowItem, WorkflowTransition

TABLE = "workflows_workflowtransition"


def _seed_transition(item, tenant, actor):
    services.perform_transition(item=item, action="submit", actor=actor, tenant=tenant)
    return WorkflowTransition.objects.get(workflow_item=item)


@pytest.mark.django_db
class TestDatabaseLevelImmutability:
    def test_raw_update_is_rejected_by_the_database(self, item_a, tenant_a, doer_a):
        """Bypass the ORM entirely -- the trigger must still refuse."""
        row = _seed_transition(item_a, tenant_a, doer_a)

        with pytest.raises((InternalError, ProgrammingError)) as exc_info:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {TABLE} SET reason = %s WHERE id = %s", ["tampered", row.pk])

        assert "immutable" in str(exc_info.value).lower()

        row.refresh_from_db()
        assert row.reason == "", "the row must be unchanged after a refused UPDATE"

    def test_raw_delete_is_rejected_by_the_database(self, item_a, tenant_a, doer_a):
        row = _seed_transition(item_a, tenant_a, doer_a)

        with pytest.raises((InternalError, ProgrammingError)) as exc_info:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {TABLE} WHERE id = %s", [row.pk])

        assert "immutable" in str(exc_info.value).lower()
        assert WorkflowTransition.objects.filter(pk=row.pk).exists()

    def test_raw_bulk_update_across_all_rows_is_rejected(
        self, item_a, tenant_a, doer_a, reviewer_a
    ):
        """An unqualified UPDATE is the shape a careless cleanup script takes."""
        _seed_transition(item_a, tenant_a, doer_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        assert WorkflowTransition.objects.count() == 2

        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {TABLE} SET reason = 'wiped'")

        assert WorkflowTransition.objects.filter(reason="wiped").count() == 0

    def test_raw_delete_all_is_rejected(self, item_a, tenant_a, doer_a):
        _seed_transition(item_a, tenant_a, doer_a)

        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {TABLE}")

        assert WorkflowTransition.objects.count() == 1

    def test_insert_still_succeeds(self, item_a, tenant_a, doer_a):
        """The triggers are BEFORE UPDATE / BEFORE DELETE only. Appending must
        remain possible or the table would be write-once-never."""
        before = WorkflowTransition.objects.count()
        row = _seed_transition(item_a, tenant_a, doer_a)
        assert WorkflowTransition.objects.count() == before + 1
        assert row.from_state == WorkflowItem.State.DRAFT
        assert row.to_state == WorkflowItem.State.SUBMITTED

    def test_normal_transitions_still_work_end_to_end(self, item_a, tenant_a, doer_a, reviewer_a):
        """A trigger that broke ordinary operation would be worse than none."""
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item_a, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )
        final = services.perform_transition(
            item=item_a, action="approve", actor=reviewer_a, tenant=tenant_a
        )

        assert final.state == WorkflowItem.State.APPROVED
        rows = list(WorkflowTransition.objects.filter(workflow_item=item_a))
        assert len(rows) == 3
        assert [r.to_state for r in rows] == ["submitted", "in_review", "approved"]

    def test_workflow_item_itself_remains_mutable(self, item_a, tenant_a, doer_a):
        """Only the history table is frozen. The item must still change state,
        or the engine would not function."""
        services.perform_transition(item=item_a, action="submit", actor=doer_a, tenant=tenant_a)
        item_a.refresh_from_db()
        assert item_a.state == WorkflowItem.State.SUBMITTED

        item_a.title = "Renamed after transition"
        item_a.save(update_fields=["title"])
        item_a.refresh_from_db()
        assert item_a.title == "Renamed after transition"


@pytest.mark.django_db
class TestTriggerInstallation:
    def test_both_triggers_exist_on_the_table(self):
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE event_object_table = %s
                ORDER BY trigger_name
                """,
                [TABLE],
            )
            names = sorted({row[0] for row in cur.fetchall()})

        assert "no_update_workflow_transition" in names
        assert "no_delete_workflow_transition" in names

    def test_guard_function_exists(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM pg_proc WHERE proname = %s",
                ["workflows_prevent_transition_update_delete"],
            )
            assert cur.fetchone()[0] == 1


@pytest.mark.django_db
class TestOrmGuardsRetained:
    """Defence in depth: the model-level guards stay, and still fire first.

    They give a domain exception with a clear message instead of a database
    error, which is a better failure for application code to handle.
    """

    def test_orm_guards_still_raise_before_reaching_the_database(self, item_a, tenant_a, doer_a):
        from workflows.models import WorkflowHistoryMutationForbidden

        row = _seed_transition(item_a, tenant_a, doer_a)

        with pytest.raises(WorkflowHistoryMutationForbidden):
            row.delete()
        with pytest.raises(WorkflowHistoryMutationForbidden):
            WorkflowTransition.objects.filter(pk=row.pk).update(reason="x")
        with pytest.raises(WorkflowHistoryMutationForbidden):
            WorkflowTransition.objects.filter(pk=row.pk).delete()

        # Nothing reached the database, so the row is intact either way.
        row.refresh_from_db()
        assert row.reason == ""
