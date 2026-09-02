"""A persisted revision family, and a database floor under revision numbers.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A, **conditional on the data**. One nullable column, one
              derivation over rows already in this table, two constraints, and
              one replaced plus one added trigger function.

              The condition: `unique_revision_per_package_family` will refuse to
              build if any existing family already holds two packages with the
              same `revision_number`. The code this migration replaces keyed
              revisions on `tenant + case + name`, so a package renamed between
              two clones could produce exactly that. Check before deploying:

                  SELECT COALESCE(family_root_id, id) AS family, tenant_id,
                         revision_number, count(*)
                    FROM submission_packages_submissionpackage
                   GROUP BY 1, 2, 3 HAVING count(*) > 1;

              Empty result -> Class A. Non-empty -> the duplicates have to be
              resolved by hand first, and that is a decision about which package
              keeps which number, not something a migration may guess.

    ROLLBACK: Class A. The reverse drops both constraints, drops the trigger and
              function added here, restores the exact `0002` update-guard body,
              sets every `family_root_id` back to NULL and drops the column --
              which is precisely the state before this migration ran.

              **This contains a data step and is still not class C or D.** The
              runbook's rule 1 flags `RunSQL`/`RunPython` because a data
              migration usually destroys information a restore has to bring
              back. This one destroys none: `family_root` is *derived* from
              `source_package`, which this migration never touches, so the
              reverse loses nothing and the forward step can be recomputed at
              any time by running it again.

**This does not make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any package data exists.

---

WHY FAMILY IDENTITY IS A COLUMN

Revision numbers are unique within a revision family, so "which family" has to
be a question the database can answer. Two other answers were rejected:

  * **`tenant + case + name`.** A package name is display text a user may edit
    at any time. Keying revisions on it means a rename silently forks one family
    into two -- or merges two and collides their numbers. Identity may not
    depend on a mutable label.

  * **Walking `source_package` at read time.** Correct but unlockable: the walk
    costs a query per hop, and a concurrent clone can extend the chain while the
    walk is in progress, so two transactions can disagree about the very row
    they are supposed to be serialising on.

`family_root_id` is written once, at insert, and frozen by the update guard
thereafter. A founder stores NULL -- a row cannot reference its own primary key
before that key exists -- so the family of any package is
`COALESCE(family_root_id, id)`, and that expression is what both the uniqueness
index and `clone_package`'s lock use.

WHAT THE TOPOLOGY ACTUALLY IS

`source_package` is a **tree, not a chain**: two clones of the same frozen
revision are both legitimate, and nothing in the schema forbids it. The model
previously called it a chain. The schema never enforced that, so the claim is
withdrawn rather than enforced retroactively -- adding a constraint to forbid
branches would break a working feature in order to make a comment true.

What *is* linear is `revision_number` within a family, and that is now a unique
index rather than a description.

WHY THE UNIQUE INDEX EXISTS ALONGSIDE THE LOCK

`clone_package` locks the family root before assigning a number, which
serialises every clone in a family whichever revision it started from. The index
is the floor under that: it holds for a transaction that never took the lock --
a raw cursor, a psql session, a future code path nobody re-reviewed.
"""

import importlib

import django.db.models.deletion
import django.db.models.functions.comparison
from django.conf import settings
from django.db import migrations, models

PACKAGE_TABLE = "submission_packages_submissionpackage"

# The reverse of the replaced guard is the *original* body, taken from the
# migration that created it rather than retyped here. Two hand-maintained copies
# of the same plpgsql drift, and the copy that drifts is the one nothing runs.
_0002 = importlib.import_module("submission_packages.migrations.0002_package_db_governance")

#: `guard_update_package` refuses every UPDATE to a FROZEN or CANCELLED row, so
#: the derivation below cannot run while it is armed -- a database holding one
#: frozen package would fail this migration outright.
#:
#: The guard is therefore disabled for exactly the length of the derivation, by
#: name, and re-armed in the same statement block. This is safe for one specific
#: reason: `family_root_id` is not new information. It is computed from
#: `source_package_id`, which the guard already holds immutable, so the column is
#: being *completed* for rows frozen before it existed, not rewritten. Nothing
#: else about those rows is touched, and the ACCESS EXCLUSIVE lock the ALTER
#: takes means no other session can write through the open window.
#:
#: Django runs this migration inside a transaction, so a failure anywhere below
#: rolls the disable back with it and the guard is never left down.
DISARM_SQL = f"ALTER TABLE {PACKAGE_TABLE} DISABLE TRIGGER guard_update_package;"

#: Django declares foreign keys DEFERRABLE INITIALLY DEFERRED, so the derivation
#: leaves that many unchecked FK events queued -- and PostgreSQL refuses to ALTER
#: a table with pending trigger events, which would make the re-arm below fail on
#: any database that actually has clones (and silently succeed on one that does
#: not, which is worse). Flushing them first checks every new `family_root_id`
#: reference immediately, then leaves the table alterable.
REARM_SQL = f"""SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE {PACKAGE_TABLE} ENABLE TRIGGER guard_update_package;"""

BACKFILL_SQL = f"""
{DISARM_SQL}

WITH RECURSIVE walk(id, root_id, depth) AS (
    SELECT p.id, p.id, 0
      FROM {PACKAGE_TABLE} p
     WHERE p.source_package_id IS NULL
    UNION ALL
    SELECT c.id, w.root_id, w.depth + 1
      FROM {PACKAGE_TABLE} c
      JOIN walk w ON c.source_package_id = w.id
     WHERE w.depth < 100000
)
UPDATE {PACKAGE_TABLE} t
   SET family_root_id = w.root_id
  FROM walk w
 WHERE t.id = w.id AND w.root_id <> t.id;

DO $mig$
DECLARE
    unresolved bigint;
BEGIN
    -- Every package with a source must now name a family. A row that does not
    -- is unreachable from any founder, which means a cycle -- and a cycle has
    -- no root to serialise on, so the migration stops rather than leaving
    -- behind a family whose revision numbers nothing governs.
    SELECT count(*) INTO unresolved
      FROM {PACKAGE_TABLE}
     WHERE source_package_id IS NOT NULL AND family_root_id IS NULL;
    IF unresolved > 0 THEN
        RAISE EXCEPTION
            '% package row(s) could not be resolved to a revision family.', unresolved;
    END IF;
END;
$mig$;

{REARM_SQL}
"""  # noqa: S608 - DDL/derivation; the only interpolation is the table name above

BACKFILL_REVERSE_SQL = f"""
{DISARM_SQL}
UPDATE {PACKAGE_TABLE} SET family_root_id = NULL;
{REARM_SQL}
"""  # noqa: S608 - the column is dropped immediately after this runs

# `0002`'s guard with `family_root_id` added to the immutable set. Family
# membership is provenance: a row that could change families could change which
# revision numbers it collides with, and the unique index would be enforcing a
# grouping that moves underneath it.
PACKAGE_UPDATE_FN_V2 = _0002.PACKAGE_UPDATE_FN.replace(
    "       OR NEW.revision_number IS DISTINCT FROM OLD.revision_number\n",
    "       OR NEW.revision_number IS DISTINCT FROM OLD.revision_number\n"
    "       OR NEW.family_root_id IS DISTINCT FROM OLD.family_root_id\n",
)
if "family_root_id" not in PACKAGE_UPDATE_FN_V2:  # pragma: no cover - build-time guard
    raise RuntimeError("the 0002 package update guard no longer matches; 0003 cannot patch it")

PACKAGE_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION submission_packages_guard_package_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    root_tenant bigint;
    root_case   bigint;
    root_family bigint;
    src_tenant  bigint;
    src_case    bigint;
    src_family  bigint;
BEGIN
    -- A package that starts its own family.
    IF NEW.family_root_id IS NULL THEN
        IF NEW.source_package_id IS NOT NULL THEN
            RAISE EXCEPTION 'a copied package must record its revision family.';
        END IF;
        IF NEW.revision_number <> 1 THEN
            RAISE EXCEPTION 'the first package in a revision family is revision 1.';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.source_package_id IS NULL THEN
        RAISE EXCEPTION 'a package in a revision family must record what it was copied from.';
    END IF;
    IF NEW.revision_number <= 1 THEN
        RAISE EXCEPTION 'a copied package must carry a revision above the first.';
    END IF;

    SELECT tenant_id, regulatory_case_id, family_root_id
      INTO root_tenant, root_case, root_family
      FROM {PACKAGE_TABLE} WHERE id = NEW.family_root_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the named revision family does not exist.';
    END IF;
    IF root_family IS NOT NULL THEN
        RAISE EXCEPTION 'a revision family root cannot belong to another family.';
    END IF;
    IF root_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'a package cannot join a revision family in another tenant.';
    END IF;
    IF root_case IS DISTINCT FROM NEW.regulatory_case_id THEN
        RAISE EXCEPTION 'a package cannot join a revision family on another regulatory case.';
    END IF;

    SELECT tenant_id, regulatory_case_id, COALESCE(family_root_id, id)
      INTO src_tenant, src_case, src_family
      FROM {PACKAGE_TABLE} WHERE id = NEW.source_package_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the source package does not exist.';
    END IF;
    IF src_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'a package cannot be copied across tenants.';
    END IF;
    IF src_case IS DISTINCT FROM NEW.regulatory_case_id THEN
        RAISE EXCEPTION 'a package cannot be copied across regulatory cases.';
    END IF;
    IF src_family IS DISTINCT FROM NEW.family_root_id THEN
        RAISE EXCEPTION 'a copy must join the same revision family as its source.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the table name above

GOVERNANCE_SQL = (
    PACKAGE_UPDATE_FN_V2
    + PACKAGE_INSERT_FN
    + f"""
CREATE TRIGGER guard_insert_package
    BEFORE INSERT ON {PACKAGE_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_guard_package_insert();
"""
)

GOVERNANCE_REVERSE_SQL = (
    f"""
DROP TRIGGER IF EXISTS guard_insert_package ON {PACKAGE_TABLE};
DROP FUNCTION IF EXISTS submission_packages_guard_package_insert();
"""
    + _0002.PACKAGE_UPDATE_FN
)


class Migration(migrations.Migration):
    dependencies = [
        ("regulatory_cases", "0002_case_link_db_immutability"),
        ("submission_packages", "0002_package_db_governance"),
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="submissionpackage",
            name="family_root",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="family_members",
                to="submission_packages.submissionpackage",
            ),
        ),
        # Derive families for rows that predate the column, BEFORE the unique
        # index is built over them.
        migrations.RunSQL(sql=BACKFILL_SQL, reverse_sql=BACKFILL_REVERSE_SQL),
        migrations.AddConstraint(
            model_name="submissionpackage",
            constraint=models.CheckConstraint(
                condition=models.Q(("family_root", models.F("id")), _negated=True),
                name="package_is_not_its_own_family_root",
            ),
        ),
        migrations.AddConstraint(
            model_name="submissionpackage",
            constraint=models.UniqueConstraint(
                django.db.models.functions.comparison.Coalesce("family_root", "id"),
                models.F("tenant"),
                models.F("revision_number"),
                name="unique_revision_per_package_family",
            ),
        ),
        migrations.RunSQL(sql=GOVERNANCE_SQL, reverse_sql=GOVERNANCE_REVERSE_SQL),
    ]
