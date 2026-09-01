"""Database-level protection for the three governed section link tables.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- two plpgsql functions and six triggers.
              No table is altered and no row is touched.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the six
              triggers and two functions created here and nothing else.

**It does NOT make reversing 0001 safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any dossier exists. A rollback that
drops the link tables takes this guard down with them, which is the opposite of
protection.

---

WHY THIS EXISTS

The manager blocks `update()`, `delete()` and `bulk_update()` on a queryset, and
`Model.delete()` raises. None of that stops:

    link = DossierSectionDocument.objects.get(...)
    link.document = some_other_document
    link.save()

`save()` issues a plain UPDATE that never passes through the manager, so a
governed link could be repointed, moved to another section or another tenant, or
have its provenance rewritten -- outside the service layer and with no audit
row. Only the database can refuse that.

This is applied from the start rather than added after review, because
independent review of Milestone 8 found exactly this gap in the equivalent case
link tables and it is the same mistake either way.

Follows `regulatory_cases/0002` and `workflows/0005`: the same plpgsql shape,
deliberately NOT a blanket UPDATE ban. A link must make exactly one transition,
active -> unlinked, once. So the guard:

  * forbids DELETE outright, including after an unlink;
  * forbids any UPDATE to an already-unlinked row;
  * freezes every column except the two unlink stamps;
  * requires both stamps to move together;
  * permits `updated_at` to change ONLY inside that transition, so it cannot
    become a backdoor for an otherwise-frozen row.

PostgreSQL only.
"""

from django.db import migrations

TABLES = {
    "submission_dossiers_dossiersectiondocument": "document_id",
    "submission_dossiers_dossiersectionworkflow": "workflow_item_id",
    "submission_dossiers_dossiersectionchecklist": "checklist_execution_id",
}

DELETE_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_prevent_link_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'section link rows cannot be deleted: unlink instead.';
END;
$$;
"""

# One shared function for all three tables; TG_ARGV[0] carries the target column
# so the frozen-column comparison cannot go stale on one table while staying
# correct on the others.
UPDATE_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_guard_link_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    target_col text := TG_ARGV[0];
    old_target text;
    new_target text;
BEGIN
    IF OLD.unlinked_at IS NOT NULL THEN
        RAISE EXCEPTION 'section link row is already unlinked and is immutable.';
    END IF;

    old_target := to_jsonb(OLD) ->> target_col;
    new_target := to_jsonb(NEW) ->> target_col;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.section_id IS DISTINCT FROM OLD.section_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR new_target IS DISTINCT FROM old_target
       OR NEW.purpose IS DISTINCT FROM OLD.purpose
       OR NEW.linked_by_id IS DISTINCT FROM OLD.linked_by_id
       OR NEW.linked_at IS DISTINCT FROM OLD.linked_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'section link rows are immutable except for unlinking.';
    END IF;

    IF NEW.unlinked_at IS NULL OR NEW.unlinked_by_id IS NULL THEN
        RAISE EXCEPTION 'section link unlink must set both unlinked_at and unlinked_by.';
    END IF;

    RETURN NEW;
END;
$$;
"""


def _short(table: str) -> str:
    return table.replace("submission_dossiers_dossiersection", "")


def _triggers_for(table: str, target_col: str) -> str:
    s = _short(table)
    return f"""
CREATE TRIGGER no_delete_section_{s}_link
BEFORE DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_prevent_link_delete();

CREATE TRIGGER guard_update_section_{s}_link
BEFORE UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_guard_link_update('{target_col}');
"""


def _drop_for(table: str) -> str:
    s = _short(table)
    return f"""
DROP TRIGGER IF EXISTS no_delete_section_{s}_link ON {table};
DROP TRIGGER IF EXISTS guard_update_section_{s}_link ON {table};
"""


CREATE_SQL = DELETE_FN + UPDATE_FN + "".join(_triggers_for(t, c) for t, c in TABLES.items())

DROP_SQL = (
    "".join(_drop_for(t) for t in TABLES)
    + """
DROP FUNCTION IF EXISTS submission_dossiers_prevent_link_delete();
DROP FUNCTION IF EXISTS submission_dossiers_guard_link_update();
"""
)


class Migration(migrations.Migration):
    dependencies = [
        ("submission_dossiers", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
