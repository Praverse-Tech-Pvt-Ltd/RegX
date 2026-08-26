"""Database-level INSERT validation for blueprint provenance.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- exactly 2 plpgsql functions and 2
              triggers. No table is altered, no column is added or dropped, and
              no row is read, written or destroyed.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the 2
              triggers and 2 functions created here and nothing else. It
              destroys no data; it destroys only the protection.

**Removing this protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any governed blueprint or
instantiation data exists. The relationship is one-way: `0003` reverses on its
own, and `0001` cannot be reversed safely whether or not `0002` and `0003` are
still applied.

---

WHY THIS EXISTS

`0002` froze `BlueprintInstantiation` and `BlueprintSectionOrigin` against
UPDATE and DELETE. Independent review found the asymmetry: **INSERT was not
validated at the database layer.**

That combination is worse than either gap alone. A direct ORM call or a raw
cursor could write a provenance row asserting something untrue --

    "this dossier was built from Blueprint A version 7"

when the dossier belongs to another tenant, or the version belongs to a
different blueprint, or version 7 never existed -- and the `0002` triggers would
then freeze that false record **permanently**. Immutability applied to an
unvalidated write does not protect the truth; it preserves the lie.

Provenance is the only surviving statement of where a dossier came from. A
dossier is deliberately a snapshot that never reads back to its blueprint, so a
false provenance row cannot be detected by comparing the two afterwards. It has
to be refused at the moment it is written.

The service layer already validates all of this. That is not the guarantee:
`Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
auto-creates, not `objects` -- so restricting the public manager cannot cover
`objects.create()`, and a raw cursor, a psql session or a migration never passes
through Python at all.

---

WHAT IS ENFORCED

**`BlueprintInstantiation`** -- every referenced row must exist, and:

    NEW.tenant_id == dossier.tenant_id
    NEW.tenant_id == blueprint.tenant_id
    NEW.tenant_id == blueprint_version.tenant_id
    blueprint_version.blueprint_id == NEW.blueprint_id
    NEW.version_number == blueprint_version.version_number

The blueprint/version coherence check matters even inside one tenant: a record
naming Blueprint A while pointing at a version of Blueprint B is internally
contradictory, and nothing downstream would notice.

The `version_number` check exists because that column is an immutable snapshot.
Without it a caller could write a truthful FK beside a fabricated number, and
every reader that trusts the snapshot -- which is the point of having one --
would be misled.

**`BlueprintSectionOrigin`** -- every referenced row must exist, and:

    NEW.tenant_id == instantiation.tenant_id
    dossier_section.tenant_id == NEW.tenant_id
    blueprint_section.tenant_id == NEW.tenant_id
    dossier_section.dossier_id == instantiation.dossier_id
    blueprint_section.blueprint_version_id == instantiation.blueprint_version_id

The last two are the ones that make the mapping mean anything: an origin row is
a claim that *this* dossier section came from *that* blueprint section, and it
is only coherent if the dossier section belongs to the instantiation's dossier
and the blueprint section belongs to the instantiation's version.

Everything fails closed: a missing referenced row is refused, not skipped.

`0002` is untouched. Its behaviour is unchanged and its triggers still hold.

PostgreSQL only.
"""

from django.db import migrations

INSTANTIATION_TABLE = "dossier_blueprints_blueprintinstantiation"
ORIGIN_TABLE = "dossier_blueprints_blueprintsectionorigin"
BLUEPRINT_TABLE = "dossier_blueprints_dossierblueprint"
VERSION_TABLE = "dossier_blueprints_dossierblueprintversion"
BLUEPRINT_SECTION_TABLE = "dossier_blueprints_dossierblueprintsection"
DOSSIER_TABLE = "submission_dossiers_submissiondossier"
DOSSIER_SECTION_TABLE = "submission_dossiers_dossiersection"

INSTANTIATION_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION dossier_blueprints_guard_instantiation_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    dossier_tenant   bigint;
    blueprint_tenant bigint;
    version_tenant   bigint;
    version_owner    bigint;
    version_num      integer;
BEGIN
    SELECT tenant_id INTO dossier_tenant
      FROM {DOSSIER_TABLE} WHERE id = NEW.dossier_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provenance references a dossier that does not exist.';
    END IF;

    SELECT tenant_id INTO blueprint_tenant
      FROM {BLUEPRINT_TABLE} WHERE id = NEW.blueprint_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provenance references a blueprint that does not exist.';
    END IF;

    SELECT tenant_id, blueprint_id, version_number
      INTO version_tenant, version_owner, version_num
      FROM {VERSION_TABLE} WHERE id = NEW.blueprint_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provenance references a blueprint version that does not exist.';
    END IF;

    IF dossier_tenant IS DISTINCT FROM NEW.tenant_id
       OR blueprint_tenant IS DISTINCT FROM NEW.tenant_id
       OR version_tenant IS DISTINCT FROM NEW.tenant_id
    THEN
        RAISE EXCEPTION
            'provenance tenant does not match the dossier, blueprint and version it names.';
    END IF;

    IF version_owner IS DISTINCT FROM NEW.blueprint_id THEN
        RAISE EXCEPTION
            'provenance names a blueprint that does not own the version it points at.';
    END IF;

    IF NEW.version_number IS DISTINCT FROM version_num THEN
        RAISE EXCEPTION
            'provenance version_number snapshot does not match the version it points at.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are the module constants above

ORIGIN_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION dossier_blueprints_guard_origin_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    inst_tenant       bigint;
    inst_dossier      bigint;
    inst_version      bigint;
    section_tenant    bigint;
    section_dossier   bigint;
    bp_section_tenant bigint;
    bp_section_ver    bigint;
BEGIN
    SELECT tenant_id, dossier_id, blueprint_version_id
      INTO inst_tenant, inst_dossier, inst_version
      FROM {INSTANTIATION_TABLE} WHERE id = NEW.instantiation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'section origin references an instantiation that does not exist.';
    END IF;

    SELECT tenant_id, dossier_id INTO section_tenant, section_dossier
      FROM {DOSSIER_SECTION_TABLE} WHERE id = NEW.dossier_section_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'section origin references a dossier section that does not exist.';
    END IF;

    SELECT tenant_id, blueprint_version_id INTO bp_section_tenant, bp_section_ver
      FROM {BLUEPRINT_SECTION_TABLE} WHERE id = NEW.blueprint_section_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'section origin references a blueprint section that does not exist.';
    END IF;

    IF inst_tenant IS DISTINCT FROM NEW.tenant_id
       OR section_tenant IS DISTINCT FROM NEW.tenant_id
       OR bp_section_tenant IS DISTINCT FROM NEW.tenant_id
    THEN
        RAISE EXCEPTION
            'section origin tenant does not match the rows it names.';
    END IF;

    IF section_dossier IS DISTINCT FROM inst_dossier THEN
        RAISE EXCEPTION
            'section origin names a dossier section from a different dossier.';
    END IF;

    IF bp_section_ver IS DISTINCT FROM inst_version THEN
        RAISE EXCEPTION
            'section origin names a blueprint section from a different version.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolations are the module constants above

TRIGGERS = f"""
CREATE TRIGGER guard_insert_blueprint_instantiation
BEFORE INSERT ON {INSTANTIATION_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_guard_instantiation_insert();

CREATE TRIGGER guard_insert_blueprint_section_origin
BEFORE INSERT ON {ORIGIN_TABLE}
FOR EACH ROW EXECUTE FUNCTION dossier_blueprints_guard_origin_insert();
"""

CREATE_SQL = INSTANTIATION_INSERT_FN + ORIGIN_INSERT_FN + TRIGGERS

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_insert_blueprint_instantiation ON {INSTANTIATION_TABLE};
DROP TRIGGER IF EXISTS guard_insert_blueprint_section_origin ON {ORIGIN_TABLE};

DROP FUNCTION IF EXISTS dossier_blueprints_guard_instantiation_insert();
DROP FUNCTION IF EXISTS dossier_blueprints_guard_origin_insert();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("dossier_blueprints", "0002_blueprint_db_governance"),
        # The guard reads submission_dossiers tables, so those must exist first.
        ("submission_dossiers", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
