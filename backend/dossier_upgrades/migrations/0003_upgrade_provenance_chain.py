"""The applied-upgrade chain may not fork, and may not start from nowhere.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. One unique constraint and exactly 1 plpgsql function and
              1 trigger. No column is added or dropped, no row is read, written
              or destroyed.

              The constraint is created against an existing table, so it is
              validated on apply. On a database that already holds a forked
              chain it will fail loudly rather than silently drop a row --
              which is the correct behaviour: a fork is a data-integrity
              incident, not something a migration should paper over.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the 1
              trigger and 1 function created here, and Django drops the
              constraint. It destroys no data; it destroys only the protection.

              (The counts are asserted against the generated SQL by the same
              symmetry test that covers `0002`.)

**Removing this protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any governed upgrade data exists. The
relationship is one-way.

---

WHY THIS EXISTS

`0002` proved that each history row is internally coherent: its tenant, dossier
and versions match the plan it names. It says nothing about how the row relates
to the rows already there. Two plans can be generated from the same source
version -- v1 to v2 and v1 to v3 -- and both reviewed and marked ready. Only one
may ever be applied. Without this, the second one writes a second history row
also claiming to start at v1, and the dossier's provenance forks into two
mutually exclusive accounts of what it is.

The service layer refuses this under lock. That is the primary defence and this
does not replace it -- but a lock only protects transactions that take it, and
`Model.save()`, `objects.create()`, a raw cursor and a psql session take
nothing.

WHAT EACH HALF ACTUALLY ENFORCES, AND WHAT IT DOES NOT

Being precise about this matters more than the protection sounding strong:

  UNIQUE (dossier_id, source_version_id)
      Holds under concurrency. A unique index is not snapshot-dependent, so two
      simultaneous inserts claiming the same source version cannot both succeed
      whatever the isolation level or lock order. This is the half that makes
      the fork impossible rather than merely unlikely.

      Safe because a source version can never legitimately repeat:
      `activate_version` refuses any version that is not DRAFT, so a RETIRED
      version never becomes ACTIVE again, and a dossier's chain only ever moves
      forward.

  chain trigger
      Holds against a *sequential* forged insert -- one that invents a starting
      point, or grafts a link onto a chain that ends somewhere else. It reads
      committed rows, so two concurrent inserts can both observe the same prior
      state and both pass; that gap is exactly what the unique constraint above
      closes. Neither is sufficient alone, and neither is claimed to be.

Together they mean: a dossier's history is a single chain, each link starts
where the previous one ended, and the first link starts at the version the
dossier was instantiated from.
"""

from django.db import migrations, models

APPLICATION_TABLE = "dossier_upgrades_dossierupgradeapplication"
INSTANTIATION_TABLE = "dossier_blueprints_blueprintinstantiation"

CHAIN_FN = f"""
CREATE OR REPLACE FUNCTION dossier_upgrades_guard_application_chain()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    prior_target    bigint;
    instantiated_at bigint;
BEGIN
    -- The most recent link already committed for this dossier, ordered exactly
    -- as `current_version_for` orders it so the two cannot disagree about which
    -- row is "latest".
    SELECT target_version_id INTO prior_target
      FROM {APPLICATION_TABLE}
     WHERE dossier_id = NEW.dossier_id
     ORDER BY created_at DESC, id DESC
     LIMIT 1;

    IF FOUND THEN
        IF prior_target IS DISTINCT FROM NEW.source_version_id THEN
            RAISE EXCEPTION
                'upgrade history does not continue this dossier''s chain: '
                'it starts at a version the dossier had already moved past.';
        END IF;
        RETURN NEW;
    END IF;

    -- No prior upgrade, so this is the first link and it must start where the
    -- dossier was instantiated. A dossier with no instantiation has no
    -- provenance to continue and cannot be upgraded at all.
    SELECT blueprint_version_id INTO instantiated_at
      FROM {INSTANTIATION_TABLE}
     WHERE dossier_id = NEW.dossier_id
     ORDER BY id ASC
     LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'upgrade history for a dossier that was never instantiated from a blueprint.';
    END IF;
    IF instantiated_at IS DISTINCT FROM NEW.source_version_id THEN
        RAISE EXCEPTION
            'first upgrade does not start at the version this dossier was instantiated from.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constants above

CHAIN_TRIGGER = f"""
CREATE TRIGGER guard_upgrade_application_chain
    BEFORE INSERT ON {APPLICATION_TABLE}
    FOR EACH ROW EXECUTE FUNCTION dossier_upgrades_guard_application_chain();
"""

CREATE_SQL = CHAIN_FN + CHAIN_TRIGGER

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_upgrade_application_chain ON {APPLICATION_TABLE};
DROP FUNCTION IF EXISTS dossier_upgrades_guard_application_chain();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("dossier_blueprints", "0003_provenance_insert_governance"),
        ("dossier_upgrades", "0002_upgrade_db_governance"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="dossierupgradeapplication",
            constraint=models.UniqueConstraint(
                fields=("dossier", "source_version"),
                name="unique_upgrade_source_per_dossier",
            ),
        ),
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
