"""Database-level protection for formulation versions (Option A, owner decision 2026-11-18).

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only: 3 plpgsql functions and 4 triggers. No
              table is altered and no row is read or written.
    ROLLBACK: Class A. `reverse_sql` drops exactly those 4 triggers and 3
              functions. It destroys no data, only the protection.

WHY

An approved formulation version is what IIG checklist runs and IID assessment
snapshots point at. `formulations.approval` is the only sanctioned way to move a
version through review, but `Model.save()`, `QuerySet.update()`, a raw cursor or
a psql session never pass through it. The same reasoning and approach as the
blueprint, package and checklist governance migrations: the version's own
`status` is the discriminator, read by the triggers.

WHAT IS ENFORCED

  * Version identity is frozen always: product, version number, creator, public
    id, creation time.
  * draft: content editable; may only stay draft or go to under_review, and
    then the submission stamps must be set.
  * under_review: content frozen; may only go to draft (return stamps and a
    reason set), retired (reject stamps and a reason set) or approved (approval
    stamps and a note set, and the approver is NEITHER the creator NOR the
    submitter: separation of duties at the database level too).
  * approved: frozen; the only change allowed is approved -> superseded with
    `superseded_at` set.
  * superseded and retired: no change at all.
  * A version that is not a draft cannot be deleted.
  * Components and dosing regimens can be inserted, changed or deleted only
    while their version is a draft.

NOT ENFORCED HERE (stated, not hidden)

  INSERT of a version is not restricted: test fixtures create versions directly
  in any status. No application code does so for an approved version: the API
  creates drafts only and the demo seed now goes through `formulations.approval`.
"""

from django.db import migrations

_STAMP_COLUMNS = (
    "status",
    "submitted_by_id",
    "submitted_at",
    "returned_by_id",
    "returned_at",
    "return_reason",
    "rejected_by_id",
    "rejected_at",
    "reject_reason",
    "approved_by_id",
    "approved_at",
    "approval_note",
    "superseded_at",
    "updated_at",
)
_WITHOUT_STAMPS = " - ".join(f"'{c}'" for c in _STAMP_COLUMNS)

FORWARD = f"""
CREATE OR REPLACE FUNCTION formulations_guard_version_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.id <> OLD.id OR NEW.public_id <> OLD.public_id
       OR NEW.product_id <> OLD.product_id OR NEW.version_number <> OLD.version_number
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'formulation version identity is immutable.';
    END IF;

    IF OLD.status IN ('superseded', 'retired') THEN
        RAISE EXCEPTION 'formulation version is % and immutable.', OLD.status;
    END IF;

    IF OLD.status = 'approved' THEN
        IF NEW.status <> 'superseded' OR NEW.superseded_at IS NULL
           OR (to_jsonb(NEW) - 'status' - 'superseded_at' - 'updated_at')
              <> (to_jsonb(OLD) - 'status' - 'superseded_at' - 'updated_at') THEN
            RAISE EXCEPTION
                'an approved formulation version is immutable; it may only be superseded.';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'under_review' THEN
        IF (to_jsonb(NEW) - {_WITHOUT_STAMPS}) <> (to_jsonb(OLD) - {_WITHOUT_STAMPS}) THEN
            RAISE EXCEPTION 'a formulation version under review cannot be changed.';
        END IF;
        IF NEW.status = 'under_review' THEN
            RETURN NEW;
        ELSIF NEW.status = 'draft' THEN
            IF NEW.returned_by_id IS NULL OR NEW.returned_at IS NULL
               OR btrim(NEW.return_reason) = '' THEN
                RAISE EXCEPTION 'returning a version needs who, when and a reason.';
            END IF;
        ELSIF NEW.status = 'retired' THEN
            IF NEW.rejected_by_id IS NULL OR NEW.rejected_at IS NULL
               OR btrim(NEW.reject_reason) = '' THEN
                RAISE EXCEPTION 'rejecting a version needs who, when and a reason.';
            END IF;
        ELSIF NEW.status = 'approved' THEN
            IF NEW.approved_by_id IS NULL OR NEW.approved_at IS NULL
               OR btrim(NEW.approval_note) = '' THEN
                RAISE EXCEPTION 'approving a version needs who, when and a note.';
            END IF;
            IF NEW.approved_by_id = NEW.created_by_id
               OR NEW.approved_by_id = NEW.submitted_by_id THEN
                RAISE EXCEPTION
                    'the creator or submitter of a formulation version cannot approve it.';
            END IF;
        ELSE
            RAISE EXCEPTION 'a version under review cannot become %.', NEW.status;
        END IF;
        RETURN NEW;
    END IF;

    -- draft
    IF NEW.status = 'draft' THEN
        RETURN NEW;
    ELSIF NEW.status = 'under_review' THEN
        IF NEW.submitted_by_id IS NULL OR NEW.submitted_at IS NULL THEN
            RAISE EXCEPTION 'submitting a version needs who and when.';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a draft formulation version cannot become % directly.', NEW.status;
END;
$fn$;

CREATE OR REPLACE FUNCTION formulations_prevent_version_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF OLD.status <> 'draft' THEN
        RAISE EXCEPTION 'a % formulation version cannot be deleted.', OLD.status;
    END IF;
    RETURN OLD;
END;
$fn$;

CREATE OR REPLACE FUNCTION formulations_guard_version_child()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    parent_status text;
    parent_id bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        parent_id := OLD.formulation_version_id;
    ELSE
        parent_id := NEW.formulation_version_id;
    END IF;
    SELECT status INTO parent_status FROM formulations_formulationversion WHERE id = parent_id;
    IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
        RAISE EXCEPTION '% of a % formulation version cannot be changed.', TG_TABLE_NAME, parent_status;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.formulation_version_id <> OLD.formulation_version_id THEN
        SELECT status INTO parent_status FROM formulations_formulationversion
            WHERE id = OLD.formulation_version_id;
        IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
            RAISE EXCEPTION 'a row cannot be moved out of a % formulation version.', parent_status;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$fn$;

CREATE TRIGGER formulations_version_guard_update
    BEFORE UPDATE ON formulations_formulationversion
    FOR EACH ROW EXECUTE FUNCTION formulations_guard_version_update();
CREATE TRIGGER formulations_version_prevent_delete
    BEFORE DELETE ON formulations_formulationversion
    FOR EACH ROW EXECUTE FUNCTION formulations_prevent_version_delete();
CREATE TRIGGER formulations_component_guard
    BEFORE INSERT OR UPDATE OR DELETE ON formulations_formulationcomponent
    FOR EACH ROW EXECUTE FUNCTION formulations_guard_version_child();
CREATE TRIGGER formulations_dosingregimen_guard
    BEFORE INSERT OR UPDATE OR DELETE ON formulations_dosingregimen
    FOR EACH ROW EXECUTE FUNCTION formulations_guard_version_child();
"""  # noqa: S608 - interpolates only the constant column names above

REVERSE = """
DROP TRIGGER IF EXISTS formulations_dosingregimen_guard ON formulations_dosingregimen;
DROP TRIGGER IF EXISTS formulations_component_guard ON formulations_formulationcomponent;
DROP TRIGGER IF EXISTS formulations_version_prevent_delete ON formulations_formulationversion;
DROP TRIGGER IF EXISTS formulations_version_guard_update ON formulations_formulationversion;
DROP FUNCTION IF EXISTS formulations_guard_version_child();
DROP FUNCTION IF EXISTS formulations_prevent_version_delete();
DROP FUNCTION IF EXISTS formulations_guard_version_update();
"""


class Migration(migrations.Migration):
    dependencies = [("formulations", "0003_version_review_and_approval_fields")]

    operations = [migrations.RunSQL(FORWARD, reverse_sql=REVERSE)]
