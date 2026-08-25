"""Database-level governance for blueprint versions, sections and provenance.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- five plpgsql functions and eight
              triggers. No table is altered, no column is added or dropped, and
              no row is read or written.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the eight
              triggers and five functions created here and nothing else. It
              destroys no data; it destroys only the protection.

**Removing protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any governed blueprint or
instantiation data exists. The relationship is one-way: `0002` reverses on its
own, and `0001` cannot be reversed safely whether or not `0002` is applied.

---

WHY THIS EXISTS

A blueprint version is what every dossier in the tenant gets stamped out of, and
an instantiation record is the only surviving statement of where a dossier came
from. Neither can be left to the service layer alone: `Model.save()` resolves
through `_base_manager` -- a plain `Manager` Django auto-creates, not `objects` --
so restricting the public manager cannot cover it, and a raw cursor, a psql
session or a migration never passes through Python at all.

WHY THERE IS NO SANCTIONED WINDOW

Milestone 9 needed a transaction-scoped "which operation is running" declaration
because a dossier section is legitimately mutable by four operations with four
different column sets. **Blueprints do not have that problem.** A version's own
`status` is the discriminator:

    DRAFT      structure editable
    ACTIVE     structure frozen forever
    RETIRED    structure frozen forever

The triggers read that status directly. It cannot be forgotten by a caller, it
cannot be left open, it needs no Python cooperation, and it is the same fact a
human reviewer reads off the row. A window here would add a mechanism without
adding a guarantee.

WHAT IS ENFORCED

  * **Versions.** Identity and provenance frozen always. A RETIRED version
    refuses every UPDATE. An ACTIVE one may only go to RETIRED. A DRAFT may edit
    its notes and go to ACTIVE or RETIRED. `version_number` never moves, so the
    race guard in the service cannot be undone afterwards. DELETE refused.

  * **Sections.** Frozen entirely unless their version is DRAFT -- one rule that
    covers "no edits after activation", "no edits after retirement" and "no
    inserting into a published version". Identity frozen always. Retirement is
    one-way. DELETE refused. INSERT re-validates the hierarchy: no self-parent,
    same version, same tenant, parent not retired, no cycle, bounded depth.

  * **Provenance.** `BlueprintInstantiation` and `BlueprintSectionOrigin` refuse
    UPDATE and DELETE outright. There is no legitimate edit: the row records
    that a thing happened, and rewriting which blueprint version a dossier came
    from would falsify the only record of it.

Row-level BEFORE DELETE triggers do not fire on TRUNCATE, so the Django test
database teardown is unaffected.

PostgreSQL only.
"""

from django.db import migrations

VERSION_TABLE = "dossier_blueprints_dossierblueprintversion"
SECTION_TABLE = "dossier_blueprints_dossierblueprintsection"
INSTANTIATION_TABLE = "dossier_blueprints_blueprintinstantiation"
ORIGIN_TABLE = "dossier_blueprints_blueprintsectionorigin"

#: Mirrors `models.MAX_BLUEPRINT_DEPTH`; asserted equal in the tests.
MAX_DEPTH = 10

VERSION_UPDATE_FN = """
CREATE OR REPLACE FUNCTION dossier_blueprints_guard_version_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.blueprint_id IS DISTINCT FROM OLD.blueprint_id
       OR NEW.version_number IS DISTINCT FROM OLD.version_number
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.supersedes_id IS DISTINCT FROM OLD.supersedes_id
    THEN
        RAISE EXCEPTION
            'blueprint version identity and provenance are immutable.';
    END IF;

    -- A retired version is finished history.
    IF OLD.status = 'retired' THEN
        RAISE EXCEPTION 'blueprint version is retired and is immutable.';
    END IF;

    IF OLD.status = 'active' THEN
        IF NEW.notes IS DISTINCT FROM OLD.notes THEN
            RAISE EXCEPTION 'an active blueprint version is immutable.';
        END IF;
        IF NEW.status IS DISTINCT FROM 'retired' THEN
            RAISE EXCEPTION 'an active blueprint version may only be retired.';
        END IF;
        IF NEW.retired_at IS NULL OR NEW.retired_by_id IS NULL THEN
            RAISE EXCEPTION 'retirement must set both retired_at and retired_by.';
        END IF;
        IF NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
        THEN
            RAISE EXCEPTION 'activation stamps are immutable once set.';
        END IF;
        RETURN NEW;
    END IF;

    -- OLD.status = 'draft'
    IF NEW.status = 'active' THEN
        IF NEW.activated_at IS NULL OR NEW.activated_by_id IS NULL THEN
            RAISE EXCEPTION 'activation must set both activated_at and activated_by.';
        END IF;
    ELSIF NEW.status = 'retired' THEN
        IF NEW.retired_at IS NULL OR NEW.retired_by_id IS NULL THEN
            RAISE EXCEPTION 'retirement must set both retired_at and retired_by.';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'unknown blueprint version status: %', NEW.status;
    END IF;

    RETURN NEW;
END;
$fn$;
"""

VERSION_DELETE_FN = """
CREATE OR REPLACE FUNCTION dossier_blueprints_prevent_version_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'blueprint version rows cannot be deleted: retire the version instead.';
END;
$fn$;
"""

HIERARCHY_FN = f"""
CREATE OR REPLACE FUNCTION dossier_blueprints_check_section_parent(
    child_id bigint,
    new_parent_id bigint,
    child_version_id bigint,
    child_tenant_id bigint
) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    parent_version bigint;
    parent_tenant  bigint;
    parent_retired timestamptz;
    walker         bigint;
    hops           int := 0;
BEGIN
    IF new_parent_id IS NULL THEN
        RETURN;
    END IF;

    IF new_parent_id = child_id THEN
        RAISE EXCEPTION 'a blueprint section cannot be its own parent.';
    END IF;

    SELECT blueprint_version_id, tenant_id, retired_at
      INTO parent_version, parent_tenant, parent_retired
      FROM {SECTION_TABLE}
     WHERE id = new_parent_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'parent blueprint section does not exist.';
    END IF;
    IF parent_version IS DISTINCT FROM child_version_id THEN
        RAISE EXCEPTION 'parent blueprint section belongs to a different version.';
    END IF;
    IF parent_tenant IS DISTINCT FROM child_tenant_id THEN
        RAISE EXCEPTION 'parent blueprint section belongs to a different tenant.';
    END IF;
    IF parent_retired IS NOT NULL THEN
        RAISE EXCEPTION 'parent blueprint section is retired.';
    END IF;

    walker := new_parent_id;
    WHILE walker IS NOT NULL LOOP
        IF walker = child_id THEN
            RAISE EXCEPTION 'that parent would create a cycle in the blueprint tree.';
        END IF;
        hops := hops + 1;
        IF hops > {MAX_DEPTH} + 2 THEN
            RAISE EXCEPTION 'blueprint section nesting is too deep.';
        END IF;
        SELECT parent_id INTO walker FROM {SECTION_TABLE} WHERE id = walker;
    END LOOP;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are module constants above

SECTION_UPDATE_FN = f"""
CREATE OR REPLACE FUNCTION dossier_blueprints_guard_section_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    version_status text;
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.blueprint_version_id IS DISTINCT FROM OLD.blueprint_version_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'blueprint section identity is immutable.';
    END IF;

    SELECT status INTO version_status
      FROM {VERSION_TABLE} WHERE id = NEW.blueprint_version_id;

    -- One rule covering "no edits after activation", "no edits after
    -- retirement", and every raw-SQL route to either.
    IF version_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION
            'blueprint section belongs to a % version and is immutable.', version_status;
    END IF;

    IF OLD.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'blueprint section is retired and is immutable.';
    END IF;

    IF NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
        PERFORM dossier_blueprints_check_section_parent(
            NEW.id, NEW.parent_id, NEW.blueprint_version_id, NEW.tenant_id
        );
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are the module constants above

SECTION_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION dossier_blueprints_guard_section_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    version_status text;
BEGIN
    SELECT status INTO version_status
      FROM {VERSION_TABLE} WHERE id = NEW.blueprint_version_id;

    IF version_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION
            'cannot add a section to a % blueprint version.', version_status;
    END IF;

    PERFORM dossier_blueprints_check_section_parent(
        NEW.id, NEW.parent_id, NEW.blueprint_version_id, NEW.tenant_id
    );
    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are the module constants above

SECTION_DELETE_FN = """
CREATE OR REPLACE FUNCTION dossier_blueprints_prevent_section_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'blueprint section rows cannot be deleted: retire the section instead.';
END;
$fn$;
"""

PROVENANCE_FN = """
CREATE OR REPLACE FUNCTION dossier_blueprints_prevent_provenance_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'blueprint provenance is a permanent record: it cannot be changed or deleted.';
END;
$fn$;
"""

TRIGGERS = f"""
CREATE TRIGGER guard_update_blueprint_version
BEFORE UPDATE ON {VERSION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_guard_version_update();

CREATE TRIGGER no_delete_blueprint_version
BEFORE DELETE ON {VERSION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_prevent_version_delete();

CREATE TRIGGER guard_update_blueprint_section
BEFORE UPDATE ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_guard_section_update();

CREATE TRIGGER guard_insert_blueprint_section
BEFORE INSERT ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_guard_section_insert();

CREATE TRIGGER no_delete_blueprint_section
BEFORE DELETE ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_prevent_section_delete();

CREATE TRIGGER freeze_blueprint_instantiation
BEFORE UPDATE OR DELETE ON {INSTANTIATION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_prevent_provenance_change();

CREATE TRIGGER freeze_blueprint_section_origin
BEFORE UPDATE OR DELETE ON {ORIGIN_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_prevent_provenance_change();
"""

CREATE_SQL = (
    VERSION_UPDATE_FN
    + VERSION_DELETE_FN
    + HIERARCHY_FN
    + SECTION_UPDATE_FN
    + SECTION_INSERT_FN
    + SECTION_DELETE_FN
    + PROVENANCE_FN
    + TRIGGERS
)

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_update_blueprint_version ON {VERSION_TABLE};
DROP TRIGGER IF EXISTS no_delete_blueprint_version ON {VERSION_TABLE};
DROP TRIGGER IF EXISTS guard_update_blueprint_section ON {SECTION_TABLE};
DROP TRIGGER IF EXISTS guard_insert_blueprint_section ON {SECTION_TABLE};
DROP TRIGGER IF EXISTS no_delete_blueprint_section ON {SECTION_TABLE};
DROP TRIGGER IF EXISTS freeze_blueprint_instantiation ON {INSTANTIATION_TABLE};
DROP TRIGGER IF EXISTS freeze_blueprint_section_origin ON {ORIGIN_TABLE};

DROP FUNCTION IF EXISTS dossier_blueprints_guard_version_update();
DROP FUNCTION IF EXISTS dossier_blueprints_prevent_version_delete();
DROP FUNCTION IF EXISTS dossier_blueprints_guard_section_update();
DROP FUNCTION IF EXISTS dossier_blueprints_guard_section_insert();
DROP FUNCTION IF EXISTS dossier_blueprints_prevent_section_delete();
DROP FUNCTION IF EXISTS dossier_blueprints_prevent_provenance_change();
DROP FUNCTION IF EXISTS dossier_blueprints_check_section_parent(bigint, bigint, bigint, bigint);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("dossier_blueprints", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
