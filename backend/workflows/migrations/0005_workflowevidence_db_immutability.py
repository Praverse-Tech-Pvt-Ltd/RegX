"""Database-level protection for WorkflowEvidence.

Follows `audit/0001_initial.py` and `workflows/0003` -- the same plpgsql shape,
the same `RunSQL` + `reverse_sql` structure. No new immutability architecture.

**Deliberately not identical to the other two.** `AuditEvent` and
`WorkflowTransition` forbid every UPDATE; evidence must permit exactly one --
stamping `unlinked_by` / `unlinked_at` on an active row, which is how a link is
retired without destroying the record that it existed.

So the trigger forbids DELETE outright, and forbids any UPDATE that:

  * touches an already-unlinked row (an unlink is final), or
  * changes any column other than the two unlink stamps, or
  * clears the stamps back to NULL (no un-unlinking).

The result is append-only-with-one-transition: a row can move active -> unlinked
once, and nothing else. Every other field is frozen from insert.

PostgreSQL only. Reverse removes only the function and triggers created here.
"""

from django.db import migrations

CREATE_EVIDENCE_GUARD = """
CREATE OR REPLACE FUNCTION workflows_prevent_evidence_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'workflow_evidence rows cannot be deleted: unlink instead.';
END;
$$;

CREATE OR REPLACE FUNCTION workflows_guard_evidence_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.unlinked_at IS NOT NULL THEN
        RAISE EXCEPTION 'workflow_evidence row is already unlinked and is immutable.';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.workflow_item_id IS DISTINCT FROM OLD.workflow_item_id
       OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.label IS DISTINCT FROM OLD.label
       OR NEW.linked_by_id IS DISTINCT FROM OLD.linked_by_id
       OR NEW.linked_at IS DISTINCT FROM OLD.linked_at
    THEN
        RAISE EXCEPTION 'workflow_evidence rows are immutable except for unlinking.';
    END IF;

    IF NEW.unlinked_at IS NULL OR NEW.unlinked_by_id IS NULL THEN
        RAISE EXCEPTION 'workflow_evidence unlink must set both unlinked_at and unlinked_by.';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER no_delete_workflow_evidence
BEFORE DELETE ON workflows_workflowevidence
FOR EACH ROW EXECUTE FUNCTION workflows_prevent_evidence_delete();

CREATE TRIGGER guard_update_workflow_evidence
BEFORE UPDATE ON workflows_workflowevidence
FOR EACH ROW EXECUTE FUNCTION workflows_guard_evidence_update();
"""

DROP_EVIDENCE_GUARD = """
DROP TRIGGER IF EXISTS no_delete_workflow_evidence ON workflows_workflowevidence;
DROP TRIGGER IF EXISTS guard_update_workflow_evidence ON workflows_workflowevidence;
DROP FUNCTION IF EXISTS workflows_prevent_evidence_delete();
DROP FUNCTION IF EXISTS workflows_guard_evidence_update();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0004_workflowevidence"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_EVIDENCE_GUARD,
            reverse_sql=DROP_EVIDENCE_GUARD,
        ),
    ]
