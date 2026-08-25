"""Database-level governance for dossier sections and blocker history.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- three plpgsql functions and three
              triggers. No table is altered, no column is added or dropped, and
              no row is read or written.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the
              three triggers and three functions created here and nothing else.
              Reversing it destroys no data; it destroys only the protection.

**Removing protection does NOT make reversing 0001 safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any dossier exists: reversing it drops
the outline, the section hierarchy and ordering, the link history including
retired links, and the whole blocker history with its resolution provenance.
The relationship is one-way -- this migration can be reversed on its own, and
`0001` cannot be reversed safely whether or not this one is still applied.

---

WHY THIS EXISTS

Independent review of Milestone 9 found two gaps that the service layer alone
cannot close.

**1. Dossier sections could still be hard-deleted.**

The app chose governed retirement (`retired_at` / `retired_by`) as the only
removal path. Retirement was enforced in services, and the existing tests proved
`on_delete=PROTECT` refuses a section that already holds a governed
relationship. That is not the same guarantee. A section with no children, no
blockers and no links had nothing protecting it, so all three of these removed
the row:

    section.delete()
    DossierSection.objects.filter(...).delete()
    DELETE FROM submission_dossiers_dossiersection WHERE id = ...;

A section's creation is already auditable history and the row must not simply
disappear. Python-side guards close the first two; only the database closes the
third, and only the database sees a raw cursor, a psql session, a cascade or a
migration written by someone in a hurry.

**2. Blocker history was not governed at all.**

`DossierSectionBlocker` had a CHECK constraint keeping the two resolution halves
consistent -- open carries neither stamp, resolved carries both. A CHECK
constraint evaluates one row at one instant and cannot see the previous version
of that row, so it permitted:

    blocker.status = "open"
    blocker.resolved_at = None
    blocker.resolved_by = None
    blocker.save()                 # a resolved blocker reopened, silently

and it permitted rewriting `title`, `description`, `severity`, `section_id`,
`tenant_id`, `created_by_id`, `public_id` or `created_at` at any time with no
audit row. Blockers gate readiness directly, so a rewritable blocker is a
rewritable readiness signal.

The desired lifecycle is one transition and no more:

    OPEN ---> RESOLVED ---> (immutable forever)

with DELETE refused in both states.

---

SHAPE

Follows `submission_dossiers/0002`, `regulatory_cases/0002` and `workflows/0005`:
BEFORE-row triggers in plpgsql, enumerating frozen columns by name so a reviewer
can read the guarantee straight off the function body. The accompanying
`information_schema` coverage test fails the build if a column is ever added
without being classified here, because an enumerate-by-name guard is sound only
while the enumeration stays complete.

The blocker update guard is deliberately NOT a blanket UPDATE ban. Exactly one
transition is legal, so it:

  * refuses any UPDATE at all once the row is resolved -- one rule that covers
    reopening, re-resolving, and any later content rewrite;
  * freezes every content and provenance column;
  * requires the UPDATE to BE the resolution -- `status` must become 'resolved'
    and both stamps must be non-null -- so a bare `updated_at` touch on an open
    row is refused rather than becoming a backdoor.

Row-level BEFORE DELETE triggers do not fire on TRUNCATE, so the Django test
database teardown is unaffected, exactly as for the `0002` link triggers.

PostgreSQL only.
"""

from django.db import migrations

SECTION_TABLE = "submission_dossiers_dossiersection"
BLOCKER_TABLE = "submission_dossiers_dossiersectionblocker"

SECTION_DELETE_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_prevent_section_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'dossier section rows cannot be deleted: retire the section instead.';
END;
$fn$;
"""

BLOCKER_DELETE_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_prevent_blocker_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'blocker history cannot be deleted.';
END;
$fn$;
"""

# Frozen:     id, public_id, tenant_id, section_id, title, description,
#             severity, created_by_id, created_at
# Transition: status, resolved_by_id, resolved_at, updated_at
BLOCKER_UPDATE_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_guard_blocker_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    -- One transition, once. A resolved blocker is finished history, so this
    -- single rule refuses reopening, re-resolving and any later rewrite.
    IF OLD.status = 'resolved' THEN
        RAISE EXCEPTION 'blocker is already resolved and is immutable.';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.section_id IS DISTINCT FROM OLD.section_id
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.severity IS DISTINCT FROM OLD.severity
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION
            'blocker content and provenance are immutable; only resolution may change.';
    END IF;

    -- The only legal UPDATE is the resolution itself. This is what stops a bare
    -- updated_at touch on an open row from becoming a backdoor.
    IF NEW.status IS DISTINCT FROM 'resolved' THEN
        RAISE EXCEPTION 'the only permitted blocker update is open -> resolved.';
    END IF;

    IF NEW.resolved_at IS NULL OR NEW.resolved_by_id IS NULL THEN
        RAISE EXCEPTION 'blocker resolution must set both resolved_at and resolved_by.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""

TRIGGERS = f"""
CREATE TRIGGER no_delete_dossier_section
BEFORE DELETE ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_prevent_section_delete();

CREATE TRIGGER no_delete_section_blocker
BEFORE DELETE ON {BLOCKER_TABLE}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_prevent_blocker_delete();

CREATE TRIGGER guard_update_section_blocker
BEFORE UPDATE ON {BLOCKER_TABLE}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_guard_blocker_update();
"""

CREATE_SQL = SECTION_DELETE_FN + BLOCKER_DELETE_FN + BLOCKER_UPDATE_FN + TRIGGERS

DROP_SQL = f"""
DROP TRIGGER IF EXISTS no_delete_dossier_section ON {SECTION_TABLE};
DROP TRIGGER IF EXISTS no_delete_section_blocker ON {BLOCKER_TABLE};
DROP TRIGGER IF EXISTS guard_update_section_blocker ON {BLOCKER_TABLE};

DROP FUNCTION IF EXISTS submission_dossiers_prevent_section_delete();
DROP FUNCTION IF EXISTS submission_dossiers_prevent_blocker_delete();
DROP FUNCTION IF EXISTS submission_dossiers_guard_blocker_update();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("submission_dossiers", "0002_section_link_db_immutability"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
