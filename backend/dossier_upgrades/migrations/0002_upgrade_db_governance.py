"""Database-level governance for upgrade plans, items and applied history.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- exactly 6 plpgsql functions and 7
              triggers. No table is altered, no column is added or dropped, and
              no row is read, written or destroyed.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the 7
              triggers and 6 functions created here and nothing else. It
              destroys no data; it destroys only the protection.

              (These counts are asserted against the generated SQL by a symmetry
              test. Milestone 10 shipped a docstring claiming five functions and
              eight triggers where the SQL had seven of each, and nothing caught
              it until review -- so the numbers here are checked by the build,
              not by proofreading.)

**Removing this protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any governed upgrade data exists. The
relationship is one-way: `0002` reverses on its own, and `0001` cannot be
reversed safely whether or not `0002` is applied.

---

WHY THIS EXISTS

An applied upgrade is a claim about what happened to a governed dossier: which
version it moved from, which it moved to, who decided, and which proposed
changes they accepted. If that record can be rewritten afterwards, it stops
being a record.

The service layer already enforces every rule below. That is not the guarantee:
`Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
auto-creates, not `objects` -- so restricting the public manager cannot cover
`objects.create()` or a bare `save()`, and a raw cursor, a psql session or a
migration never passes through Python at all.

WHY THERE IS NO SANCTIONED WINDOW

Milestone 9 needed a transaction-scoped operation declaration because a
`DossierSection` is legitimately mutable by four operations with four different
column sets. Upgrade rows are not: a plan's own `status` is the discriminator,
exactly as a blueprint version's is.

    DRAFT / READY   items may be reviewed; the plan may transition
    APPLIED         frozen forever
    CANCELLED       frozen forever

The triggers read that status directly. It cannot be forgotten by a caller, it
cannot be left open, it needs no Python cooperation, and it is the same fact a
reviewer reads off the row.

WHAT IS ENFORCED

**Plans.** Identity and provenance frozen always: `id`, `public_id`,
`tenant_id`, `dossier_id`, `blueprint_id`, `source_version_id`,
`target_version_id`, `created_by_id`, `created_at`. A terminal plan refuses every
UPDATE. An open plan may move only DRAFT -> READY -> APPLIED, or either open
state -> CANCELLED, with the matching stamps set together. DELETE refused: a
plan is cancelled, never removed.

**Items.** Identity frozen always, including the change the item describes --
`change_type`, `field_name`, `before_value`, `after_value`, `section_code` and
the three section references. A review may move `status` and stamp the reviewer,
and nothing else. Once the parent plan is terminal every UPDATE is refused, which
is what makes an applied plan's accept/reject record permanent. DELETE is
permitted **only while the parent plan is open**, because
`services.regenerate_plan` legitimately replaces an open proposal wholesale;
once a plan is applied or cancelled its items are history and the database
refuses to remove them.

**Applied history.** `DossierUpgradeApplication` and `UpgradeSectionOrigin`
refuse UPDATE and DELETE outright. There is no legitimate edit to a record that
an upgrade happened.

**Provenance INSERT is validated too**, learning from the Milestone 10 review:
freezing a row that was never checked on the way in does not protect the truth,
it preserves whatever was written. An application must name a plan, dossier and
versions that agree with each other and with its own tenant.

Row-level BEFORE DELETE triggers do not fire on TRUNCATE, so the Django test
database teardown is unaffected.

PostgreSQL only.
"""

from django.db import migrations

PLAN_TABLE = "dossier_upgrades_dossierupgradeplan"
ITEM_TABLE = "dossier_upgrades_dossierupgradeplanitem"
APPLICATION_TABLE = "dossier_upgrades_dossierupgradeapplication"
ORIGIN_TABLE = "dossier_upgrades_upgradesectionorigin"
VERSION_TABLE = "dossier_blueprints_dossierblueprintversion"
DOSSIER_SECTION_TABLE = "submission_dossiers_dossiersection"

PLAN_UPDATE_FN = """
CREATE OR REPLACE FUNCTION dossier_upgrades_guard_plan_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
       OR NEW.blueprint_id IS DISTINCT FROM OLD.blueprint_id
       OR NEW.source_version_id IS DISTINCT FROM OLD.source_version_id
       OR NEW.target_version_id IS DISTINCT FROM OLD.target_version_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION
            'upgrade plan identity and provenance are immutable.';
    END IF;

    IF OLD.status IN ('applied', 'cancelled') THEN
        RAISE EXCEPTION 'upgrade plan is % and is immutable.', OLD.status;
    END IF;

    IF NEW.status = 'applied' THEN
        IF OLD.status IS DISTINCT FROM 'ready' THEN
            RAISE EXCEPTION 'only a plan marked ready may be applied.';
        END IF;
        IF NEW.applied_at IS NULL OR NEW.applied_by_id IS NULL THEN
            RAISE EXCEPTION 'applying must set both applied_at and applied_by.';
        END IF;
    ELSIF NEW.status = 'cancelled' THEN
        IF NEW.cancelled_at IS NULL OR NEW.cancelled_by_id IS NULL THEN
            RAISE EXCEPTION 'cancelling must set both cancelled_at and cancelled_by.';
        END IF;
    ELSIF NEW.status = 'ready' THEN
        IF NEW.reviewed_at IS NULL OR NEW.reviewed_by_id IS NULL THEN
            RAISE EXCEPTION 'marking ready must set both reviewed_at and reviewed_by.';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'unknown upgrade plan status: %', NEW.status;
    END IF;

    RETURN NEW;
END;
$fn$;
"""

PLAN_DELETE_FN = """
CREATE OR REPLACE FUNCTION dossier_upgrades_prevent_plan_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'upgrade plans cannot be deleted: cancel the plan instead.';
END;
$fn$;
"""

ITEM_UPDATE_FN = f"""
CREATE OR REPLACE FUNCTION dossier_upgrades_guard_item_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    plan_status text;
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.change_type IS DISTINCT FROM OLD.change_type
       OR NEW.field_name IS DISTINCT FROM OLD.field_name
       OR NEW.before_value IS DISTINCT FROM OLD.before_value
       OR NEW.after_value IS DISTINCT FROM OLD.after_value
       OR NEW.section_code IS DISTINCT FROM OLD.section_code
       OR NEW.dossier_section_id IS DISTINCT FROM OLD.dossier_section_id
       OR NEW.source_section_id IS DISTINCT FROM OLD.source_section_id
       OR NEW.target_section_id IS DISTINCT FROM OLD.target_section_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence
       OR NEW.blocking_reason IS DISTINCT FROM OLD.blocking_reason
       OR NEW.requires_manual_review IS DISTINCT FROM OLD.requires_manual_review
    THEN
        RAISE EXCEPTION
            'upgrade plan item content is immutable; only its review status may change.';
    END IF;

    SELECT status INTO plan_status FROM {PLAN_TABLE} WHERE id = NEW.plan_id;
    IF plan_status IN ('applied', 'cancelled') THEN
        RAISE EXCEPTION
            'upgrade plan item belongs to a % plan and is immutable.', plan_status;
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

ITEM_DELETE_FN = f"""
CREATE OR REPLACE FUNCTION dossier_upgrades_guard_item_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    plan_status text;
BEGIN
    SELECT status INTO plan_status FROM {PLAN_TABLE} WHERE id = OLD.plan_id;
    IF plan_status IN ('applied', 'cancelled') THEN
        RAISE EXCEPTION
            'upgrade plan items of a % plan are history and cannot be deleted.', plan_status;
    END IF;
    RETURN OLD;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

APPLICATION_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION dossier_upgrades_guard_application_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    plan_tenant   bigint;
    plan_dossier  bigint;
    plan_source   bigint;
    plan_target   bigint;
    source_num    integer;
    target_num    integer;
BEGIN
    SELECT tenant_id, dossier_id, source_version_id, target_version_id
      INTO plan_tenant, plan_dossier, plan_source, plan_target
      FROM {PLAN_TABLE} WHERE id = NEW.plan_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'upgrade history references a plan that does not exist.';
    END IF;

    IF plan_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'upgrade history tenant does not match the plan it names.';
    END IF;
    IF plan_dossier IS DISTINCT FROM NEW.dossier_id THEN
        RAISE EXCEPTION 'upgrade history names a dossier the plan is not for.';
    END IF;
    IF plan_source IS DISTINCT FROM NEW.source_version_id
       OR plan_target IS DISTINCT FROM NEW.target_version_id
    THEN
        RAISE EXCEPTION 'upgrade history versions do not match the plan.';
    END IF;

    SELECT version_number INTO source_num
      FROM {VERSION_TABLE} WHERE id = NEW.source_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'upgrade history references a source version that does not exist.';
    END IF;
    SELECT version_number INTO target_num
      FROM {VERSION_TABLE} WHERE id = NEW.target_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'upgrade history references a target version that does not exist.';
    END IF;

    IF NEW.source_version_number IS DISTINCT FROM source_num
       OR NEW.target_version_number IS DISTINCT FROM target_num
    THEN
        RAISE EXCEPTION
            'upgrade history version_number snapshot does not match the version it points at.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are the module constants above

HISTORY_FREEZE_FN = """
CREATE OR REPLACE FUNCTION dossier_upgrades_prevent_history_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'applied upgrade history is a permanent record: it cannot be changed or deleted.';
END;
$fn$;
"""

TRIGGERS = f"""
CREATE TRIGGER guard_update_upgrade_plan
BEFORE UPDATE ON {PLAN_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_guard_plan_update();

CREATE TRIGGER no_delete_upgrade_plan
BEFORE DELETE ON {PLAN_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_prevent_plan_delete();

CREATE TRIGGER guard_update_upgrade_plan_item
BEFORE UPDATE ON {ITEM_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_guard_item_update();

CREATE TRIGGER guard_delete_upgrade_plan_item
BEFORE DELETE ON {ITEM_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_guard_item_delete();

CREATE TRIGGER guard_insert_upgrade_application
BEFORE INSERT ON {APPLICATION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_guard_application_insert();

CREATE TRIGGER freeze_upgrade_history
BEFORE UPDATE OR DELETE ON {APPLICATION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_prevent_history_change();
"""

ORIGIN_TRIGGER = f"""
CREATE TRIGGER freeze_upgrade_section_origin
BEFORE UPDATE OR DELETE ON {ORIGIN_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_prevent_history_change();
"""

CREATE_SQL = (
    PLAN_UPDATE_FN
    + PLAN_DELETE_FN
    + ITEM_UPDATE_FN
    + ITEM_DELETE_FN
    + APPLICATION_INSERT_FN
    + HISTORY_FREEZE_FN
    + TRIGGERS
    + ORIGIN_TRIGGER
)

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_update_upgrade_plan ON {PLAN_TABLE};
DROP TRIGGER IF EXISTS no_delete_upgrade_plan ON {PLAN_TABLE};
DROP TRIGGER IF EXISTS guard_update_upgrade_plan_item ON {ITEM_TABLE};
DROP TRIGGER IF EXISTS guard_delete_upgrade_plan_item ON {ITEM_TABLE};
DROP TRIGGER IF EXISTS guard_insert_upgrade_application ON {APPLICATION_TABLE};
DROP TRIGGER IF EXISTS freeze_upgrade_history ON {APPLICATION_TABLE};
DROP TRIGGER IF EXISTS freeze_upgrade_section_origin ON {ORIGIN_TABLE};

DROP FUNCTION IF EXISTS dossier_upgrades_guard_plan_update();
DROP FUNCTION IF EXISTS dossier_upgrades_prevent_plan_delete();
DROP FUNCTION IF EXISTS dossier_upgrades_guard_item_update();
DROP FUNCTION IF EXISTS dossier_upgrades_guard_item_delete();
DROP FUNCTION IF EXISTS dossier_upgrades_guard_application_insert();
DROP FUNCTION IF EXISTS dossier_upgrades_prevent_history_change();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("dossier_upgrades", "0001_initial"),
        # The application guard reads the blueprint version table.
        ("dossier_blueprints", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
