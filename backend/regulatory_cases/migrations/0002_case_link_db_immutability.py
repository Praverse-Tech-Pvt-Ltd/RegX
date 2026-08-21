"""Database-level protection for the three governed case link tables.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- two plpgsql functions and six triggers.
              No table is altered and no row is touched.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the six
              triggers and two functions created here and nothing else.

**It does NOT make reversing 0001 safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any case exists: reversing it drops
the case and link tables and destroys the record of what each case cited, along
with the per-tenant number sequence. A rollback that drops those tables takes
this guard down with them, which is the opposite of protection.

---

WHY THIS EXISTS

The model manager already blocks `update()`, `delete()` and `bulk_update()` on a
queryset, and `Model.delete()` raises. None of that stops the obvious path:

    link = RegulatoryCaseDocument.objects.get(...)
    link.document = some_other_document
    link.save()

`save()` issues a plain UPDATE that never passes through the manager, so a
governed link could be repointed at a different document, moved to another case
or another tenant, or have its provenance rewritten -- all without the service
layer, and all without an audit row. Only the database can refuse that.

Follows `workflows/0005` -- the same plpgsql shape for the same reason, applied
three times because each link table is its own table.

Like that migration, this is **deliberately not a blanket UPDATE ban**. A link
must be able to make exactly one transition: active -> unlinked, once. So the
guard:

  * forbids DELETE outright, including after an unlink;
  * forbids any UPDATE to an already-unlinked row;
  * forbids changing any column other than the two unlink stamps;
  * requires both stamps to move together;
  * permits `updated_at` to change ONLY inside that sanctioned transition, so
    it cannot become a backdoor for an otherwise-frozen row.

PostgreSQL only. SQLite could not express this and is prohibited anyway.
"""

from django.db import migrations

# The three tables differ only in the name of their target column, so the guard
# is generated per table from one template rather than written out three times
# and left to drift.
TABLES = {
    "regulatory_cases_regulatorycaseworkflow": "workflow_item_id",
    "regulatory_cases_regulatorycasedocument": "document_id",
    "regulatory_cases_regulatorycasechecklist": "checklist_execution_id",
}

DELETE_FN = """
CREATE OR REPLACE FUNCTION regulatory_cases_prevent_link_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'case link rows cannot be deleted: unlink instead.';
END;
$$;
"""

# One shared function for all three tables. `TG_ARGV[0]` carries the target
# column name, so the frozen-column comparison stays complete on every table
# without three near-identical function bodies.
UPDATE_FN = """
CREATE OR REPLACE FUNCTION regulatory_cases_guard_link_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    target_col text := TG_ARGV[0];
    old_target text;
    new_target text;
BEGIN
    IF OLD.unlinked_at IS NOT NULL THEN
        RAISE EXCEPTION 'case link row is already unlinked and is immutable.';
    END IF;

    -- to_jsonb rather than dynamic record-field access: it needs no EXECUTE,
    -- no composite-type resolution, and reads the same on every table.
    old_target := to_jsonb(OLD) ->> target_col;
    new_target := to_jsonb(NEW) ->> target_col;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.case_id IS DISTINCT FROM OLD.case_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR new_target IS DISTINCT FROM old_target
       OR NEW.label IS DISTINCT FROM OLD.label
       OR NEW.linked_by_id IS DISTINCT FROM OLD.linked_by_id
       OR NEW.linked_at IS DISTINCT FROM OLD.linked_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'case link rows are immutable except for unlinking.';
    END IF;

    IF NEW.unlinked_at IS NULL OR NEW.unlinked_by_id IS NULL THEN
        RAISE EXCEPTION 'case link unlink must set both unlinked_at and unlinked_by.';
    END IF;

    RETURN NEW;
END;
$$;
"""


def _triggers_for(table: str, target_col: str) -> str:
    short = table.replace("regulatory_cases_regulatorycase", "")
    return f"""
CREATE TRIGGER no_delete_case_{short}_link
BEFORE DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION regulatory_cases_prevent_link_delete();

CREATE TRIGGER guard_update_case_{short}_link
BEFORE UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION regulatory_cases_guard_link_update('{target_col}');
"""


def _drop_triggers_for(table: str) -> str:
    short = table.replace("regulatory_cases_regulatorycase", "")
    return f"""
DROP TRIGGER IF EXISTS no_delete_case_{short}_link ON {table};
DROP TRIGGER IF EXISTS guard_update_case_{short}_link ON {table};
"""


CREATE_SQL = DELETE_FN + UPDATE_FN + "".join(_triggers_for(t, col) for t, col in TABLES.items())

DROP_SQL = (
    "".join(_drop_triggers_for(t) for t in TABLES)
    + """
DROP FUNCTION IF EXISTS regulatory_cases_prevent_link_delete();
DROP FUNCTION IF EXISTS regulatory_cases_guard_link_update();
"""
)


class Migration(migrations.Migration):
    dependencies = [
        ("regulatory_cases", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
