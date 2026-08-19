"""Database-level immutability for WorkflowTransition.

Follows the existing repository convention exactly -- `audit/0001_initial.py`
protects `audit_auditevent` with the same shape of plpgsql function plus two
BEFORE triggers. No separate immutability architecture is introduced.

The model and queryset guards in `workflows/models.py` are retained as defence
in depth. They stop the ORM; this stops everything, including raw SQL, a
`psql` session and any future code path that bypasses the manager.

PostgreSQL only. SQLite is prohibited project-wide, and this migration would
not run on it.

Reverse removes only the function and the two triggers this migration creates.
It does not touch a single history row.
"""

from django.db import migrations

CREATE_IMMUTABLE_TRIGGER = """
CREATE OR REPLACE FUNCTION workflows_prevent_transition_update_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'workflow_transition rows are immutable: UPDATE and DELETE are forbidden.';
END;
$$;

CREATE TRIGGER no_update_workflow_transition
BEFORE UPDATE ON workflows_workflowtransition
FOR EACH ROW EXECUTE FUNCTION workflows_prevent_transition_update_delete();

CREATE TRIGGER no_delete_workflow_transition
BEFORE DELETE ON workflows_workflowtransition
FOR EACH ROW EXECUTE FUNCTION workflows_prevent_transition_update_delete();
"""

DROP_IMMUTABLE_TRIGGER = """
DROP TRIGGER IF EXISTS no_update_workflow_transition ON workflows_workflowtransition;
DROP TRIGGER IF EXISTS no_delete_workflow_transition ON workflows_workflowtransition;
DROP FUNCTION IF EXISTS workflows_prevent_transition_update_delete();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0002_workflowtransition_workflowitem_assigned_at_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_IMMUTABLE_TRIGGER,
            reverse_sql=DROP_IMMUTABLE_TRIGGER,
        ),
    ]
