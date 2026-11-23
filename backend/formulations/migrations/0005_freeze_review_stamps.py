"""QA-18: freeze the submitter and the review stamps while a formulation version is under review.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Replaces one plpgsql function (formulations_guard_version_update)
              in place. No table is altered and no row is read or written. Trigger and
              function counts are unchanged.
    ROLLBACK: Class A. `reverse_sql` restores 0004's function text exactly.

WHY (docs/qa/QA_CODEX_REPORT.md QA-18, reproduced in #154)

Under review, 0004 excluded the review stamps from its "nothing changed" check, let a
same-status update through, and compared the approver with NEW.submitted_by_id. So SQL
could change who submitted a version, and one UPDATE could rewrite the submitter and
approve as the original submitter.

WHAT CHANGES

  * Under review, submitted_by_id and submitted_at never change.
  * Staying under review changes nothing but updated_at.
  * Leaving review (to draft, retired or approved) may set only that step's own stamps
    (return, reject or approval); every other stamp must equal its stored value.
  * The self-approval check compares with the stored (OLD) creator and submitter.

Everything else in the function is 0004's text unchanged.
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
        -- QA-18: the submitter is frozen while under review, whatever the target status.
        IF NEW.submitted_by_id IS DISTINCT FROM OLD.submitted_by_id
           OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
            RAISE EXCEPTION 'the submitter of a formulation version under review cannot be changed.';
        END IF;
        IF NEW.status = 'under_review' THEN
            -- QA-18: staying under review changes nothing (only updated_at may move).
            IF (to_jsonb(NEW) - 'updated_at') <> (to_jsonb(OLD) - 'updated_at') THEN
                RAISE EXCEPTION 'the review stamps of a formulation version under review cannot be changed.';
            END IF;
            RETURN NEW;
        END IF;
        -- QA-18: leaving review sets only that step's own stamps; every other stamp is unchanged.
        IF (NEW.status = 'draft' AND (to_jsonb(NEW) - 'status' - 'updated_at' - 'returned_by_id'
                - 'returned_at' - 'return_reason')
                <> (to_jsonb(OLD) - 'status' - 'updated_at' - 'returned_by_id' - 'returned_at'
                - 'return_reason'))
           OR (NEW.status = 'retired' AND (to_jsonb(NEW) - 'status' - 'updated_at' - 'rejected_by_id'
                - 'rejected_at' - 'reject_reason')
                <> (to_jsonb(OLD) - 'status' - 'updated_at' - 'rejected_by_id' - 'rejected_at'
                - 'reject_reason'))
           OR (NEW.status = 'approved' AND (to_jsonb(NEW) - 'status' - 'updated_at' - 'approved_by_id'
                - 'approved_at' - 'approval_note')
                <> (to_jsonb(OLD) - 'status' - 'updated_at' - 'approved_by_id' - 'approved_at'
                - 'approval_note')) THEN
            RAISE EXCEPTION 'leaving review may set only that step''s own stamps.';
        END IF;
        IF NEW.status = 'draft' THEN
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
            -- QA-18: compare with the STORED creator and submitter, never with values
            -- the same statement could rewrite.
            IF NEW.approved_by_id = OLD.created_by_id
               OR NEW.approved_by_id = OLD.submitted_by_id THEN
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
"""  # noqa: S608 - interpolates only the constant column names above

REVERSE = f"""
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
"""


class Migration(migrations.Migration):
    dependencies = [("formulations", "0004_version_db_governance")]

    operations = [migrations.RunSQL(FORWARD, reverse_sql=REVERSE)]
