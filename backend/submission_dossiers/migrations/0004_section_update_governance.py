"""Database-level governance for dossier section UPDATE and INSERT.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- two plpgsql functions and two triggers.
              No table is altered, no column is added or dropped, and no row is
              read or written.

    ROLLBACK: Class A **on its own terms**. `reverse_sql` drops exactly the two
              triggers and two functions created here and nothing else. It
              destroys no data; it destroys only the protection.

**`0001` remains CLASS C -- DATA RESTORE REQUIRED** once any governed dossier
data exists. Removing protection is not the same as making destruction safe. The
relationship is one-way: `0004` reverses on its own, and `0001` cannot be
reversed safely whether or not `0002`, `0003` and `0004` are still applied.

---

WHY THIS EXISTS

`0003` closed section DELETE. It deliberately left UPDATE open, because two
sanctioned operations need it: `reorder_section` renumbers a sibling group with
`.update()`, and `recalculate_dossier` writes derived readiness with
`.bulk_update()`.

Independent review found the consequence. The same doors let any caller holding
the ORM write columns no service path would ever let them write::

    DossierSection.objects.filter(pk=s.pk).update(tenant_id=other_tenant.pk)
    DossierSection.objects.filter(pk=s.pk).update(dossier_id=other_dossier.pk)
    DossierSection.objects.filter(pk=s.pk).update(parent_id=its_own_descendant.pk)
    DossierSection.objects.filter(pk=s.pk).update(readiness='ready')
    s.parent = descendant; s.save()
    s.tenant = other_tenant; s.save()

skipping hierarchy validation, same-tenant enforcement, cross-dossier
validation, cycle prevention, derived readiness, terminal-dossier gating and
audit -- in one call, leaving no trace.

A blanket UPDATE ban is not the fix: it breaks reorder and readiness. What is
needed is the ability to tell *which* operation is writing, and to hold that
operation to exactly the columns it may touch.

---

HOW: THE SANCTIONED WINDOW

`submission_dossiers.governance.section_write` declares the running operation in
a transaction-scoped PostgreSQL run-time parameter::

    SELECT set_config('regx.dossier_section_op', 'reorder', true)

`true` means `SET LOCAL`, so the declaration dies with the transaction and
cannot leak into the next request on a pooled connection.

The trigger reads it and applies that operation's column allow-list. Anything
with no declaration -- a raw cursor, a psql session, a stray `.update()`, a
migration written by someone in a hurry -- matches no allow-list and is refused
outright.

**Declaring an operation grants nothing on its own.** It only selects which
narrow allow-list applies, and every one of them is narrow:

    (no window)   nothing. Every UPDATE refused.
    update        parent_id, section_code, title, description, notes,
                  required, status, owner_id, due_date, updated_at
    reorder       sequence, updated_at
    recalculate   readiness, readiness_reason, updated_at
    retire        retired_at, retired_by_id, updated_at

Declaring `reorder` and then writing `tenant_id` is refused exactly as firmly as
declaring nothing, because the frozen columns below are checked first and hold
under every window.

PERMANENTLY FROZEN, under every operation and every window:

    id, public_id, tenant_id, dossier_id, created_by_id, created_at

RETIREMENT IS ONE-WAY. A retired row is frozen entirely: once `retired_at` is
set, every UPDATE is refused, which covers unretiring, re-retiring, and editing
content after retirement in a single rule. Retiring itself must move
`retired_at` and `retired_by_id` together, NULL to non-NULL.

HIERARCHY. `parent_id` is writable only under the `update` window, and the
trigger independently re-checks what `services.validate_parent` checks in
Python: no self-parent, same dossier, same tenant, parent not retired, and no
cycle. The cycle walk climbs the ancestor chain and is bounded by
MAX_SECTION_DEPTH + 2 hops, so it is a handful of indexed single-row lookups and
runs only when `parent_id` actually changes.

The bound is doing two jobs: it terminates the walk on a pre-existing cycle
rather than spinning, and it enforces the depth ceiling from below. The Python
layer additionally checks the depth of the *subtree being moved*, which the
trigger does not attempt -- Python remains the fuller check, and the trigger is
the floor that holds when Python is not in the path at all.

INSERT is checked too, for the same hierarchy invariants. A raw INSERT could
otherwise create a section whose parent is in another tenant or another dossier
-- the symmetric hole, and cheap to close here.

PostgreSQL only.
"""

from django.db import migrations

SECTION_TABLE = "submission_dossiers_dossiersection"

#: Mirrors `governance.SECTION_OP_SETTING`. The Python constant and this string
#: must agree; `test_section_update_governance.py` asserts they do.
OP_SETTING = "regx.dossier_section_op"

#: Mirrors `models.MAX_SECTION_DEPTH`; asserted equal by the same test.
MAX_DEPTH = 10

# S608 (SQL injection) is suppressed for this one literal, not repo-wide: the
# only interpolations are the two module constants above -- a table name that
# is frozen for the lifetime of a migration, and an integer. No value here
# reaches the string from a caller, a request or a row.
HIERARCHY_FN = f"""
CREATE OR REPLACE FUNCTION submission_dossiers_check_section_parent(
    child_id bigint,
    new_parent_id bigint,
    child_dossier_id bigint,
    child_tenant_id bigint
) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    parent_dossier bigint;
    parent_tenant  bigint;
    parent_retired timestamptz;
    walker         bigint;
    hops           int := 0;
BEGIN
    IF new_parent_id IS NULL THEN
        RETURN;
    END IF;

    IF new_parent_id = child_id THEN
        RAISE EXCEPTION 'a dossier section cannot be its own parent.';
    END IF;

    SELECT dossier_id, tenant_id, retired_at
      INTO parent_dossier, parent_tenant, parent_retired
      FROM {SECTION_TABLE}
     WHERE id = new_parent_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'parent section does not exist.';
    END IF;
    IF parent_dossier IS DISTINCT FROM child_dossier_id THEN
        RAISE EXCEPTION 'parent section belongs to a different dossier.';
    END IF;
    IF parent_tenant IS DISTINCT FROM child_tenant_id THEN
        RAISE EXCEPTION 'parent section belongs to a different tenant.';
    END IF;
    IF parent_retired IS NOT NULL THEN
        RAISE EXCEPTION 'parent section is retired.';
    END IF;

    -- Climb the ancestor chain. The bound both terminates on a pre-existing
    -- cycle and enforces the depth ceiling from below.
    walker := new_parent_id;
    WHILE walker IS NOT NULL LOOP
        IF walker = child_id THEN
            RAISE EXCEPTION 'that parent would create a cycle in the section tree.';
        END IF;
        hops := hops + 1;
        IF hops > {MAX_DEPTH} + 2 THEN
            RAISE EXCEPTION 'section nesting is too deep.';
        END IF;
        SELECT parent_id INTO walker FROM {SECTION_TABLE} WHERE id = walker;
    END LOOP;
END;
$fn$;
"""  # noqa: S608 - see the note above the literal

UPDATE_FN = f"""
CREATE OR REPLACE FUNCTION submission_dossiers_guard_section_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    op text := NULLIF(current_setting('{OP_SETTING}', true), '');
BEGIN
    ------------------------------------------------------------------
    -- 1. Permanently frozen. Checked first, so no window can reach them.
    ------------------------------------------------------------------
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION
            'section identity and provenance are immutable (id, public_id, tenant, dossier, created_by, created_at).';
    END IF;

    ------------------------------------------------------------------
    -- 2. A retired section is finished history: frozen entirely. Covers
    --    unretiring, re-retiring and post-retirement content edits at once.
    ------------------------------------------------------------------
    IF OLD.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'section is retired and is immutable.';
    END IF;

    ------------------------------------------------------------------
    -- 3. No declared operation -> no write. This is the bypass itself.
    ------------------------------------------------------------------
    IF op IS NULL THEN
        RAISE EXCEPTION
            'dossier sections may only be updated through submission_dossiers.services.';
    END IF;

    ------------------------------------------------------------------
    -- 4. Per-operation column allow-lists.
    ------------------------------------------------------------------
    IF op = 'reorder' THEN
        IF NEW.parent_id IS DISTINCT FROM OLD.parent_id
           OR NEW.section_code IS DISTINCT FROM OLD.section_code
           OR NEW.title IS DISTINCT FROM OLD.title
           OR NEW.description IS DISTINCT FROM OLD.description
           OR NEW.notes IS DISTINCT FROM OLD.notes
           OR NEW.required IS DISTINCT FROM OLD.required
           OR NEW.status IS DISTINCT FROM OLD.status
           OR NEW.readiness IS DISTINCT FROM OLD.readiness
           OR NEW.readiness_reason IS DISTINCT FROM OLD.readiness_reason
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.due_date IS DISTINCT FROM OLD.due_date
           OR NEW.retired_at IS DISTINCT FROM OLD.retired_at
           OR NEW.retired_by_id IS DISTINCT FROM OLD.retired_by_id
        THEN
            RAISE EXCEPTION 'a reorder may change only sequence.';
        END IF;
        RETURN NEW;
    END IF;

    IF op = 'recalculate' THEN
        IF NEW.parent_id IS DISTINCT FROM OLD.parent_id
           OR NEW.section_code IS DISTINCT FROM OLD.section_code
           OR NEW.title IS DISTINCT FROM OLD.title
           OR NEW.description IS DISTINCT FROM OLD.description
           OR NEW.notes IS DISTINCT FROM OLD.notes
           OR NEW.required IS DISTINCT FROM OLD.required
           OR NEW.status IS DISTINCT FROM OLD.status
           OR NEW.sequence IS DISTINCT FROM OLD.sequence
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.due_date IS DISTINCT FROM OLD.due_date
           OR NEW.retired_at IS DISTINCT FROM OLD.retired_at
           OR NEW.retired_by_id IS DISTINCT FROM OLD.retired_by_id
        THEN
            RAISE EXCEPTION
                'a readiness recalculation may change only readiness and readiness_reason.';
        END IF;
        RETURN NEW;
    END IF;

    IF op = 'retire' THEN
        IF NEW.parent_id IS DISTINCT FROM OLD.parent_id
           OR NEW.section_code IS DISTINCT FROM OLD.section_code
           OR NEW.title IS DISTINCT FROM OLD.title
           OR NEW.description IS DISTINCT FROM OLD.description
           OR NEW.notes IS DISTINCT FROM OLD.notes
           OR NEW.required IS DISTINCT FROM OLD.required
           OR NEW.status IS DISTINCT FROM OLD.status
           OR NEW.readiness IS DISTINCT FROM OLD.readiness
           OR NEW.readiness_reason IS DISTINCT FROM OLD.readiness_reason
           OR NEW.sequence IS DISTINCT FROM OLD.sequence
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.due_date IS DISTINCT FROM OLD.due_date
        THEN
            RAISE EXCEPTION 'a retirement may change only the retirement stamps.';
        END IF;
        IF NEW.retired_at IS NULL OR NEW.retired_by_id IS NULL THEN
            RAISE EXCEPTION 'retirement must set both retired_at and retired_by.';
        END IF;
        RETURN NEW;
    END IF;

    IF op = 'update' THEN
        -- `sequence` is excluded on purpose: ordering has its own sanctioned
        -- path, and letting a metadata edit renumber siblings would sidestep
        -- the sibling lock that keeps ordering deterministic.
        IF NEW.sequence IS DISTINCT FROM OLD.sequence
           OR NEW.readiness IS DISTINCT FROM OLD.readiness
           OR NEW.readiness_reason IS DISTINCT FROM OLD.readiness_reason
           OR NEW.retired_at IS DISTINCT FROM OLD.retired_at
           OR NEW.retired_by_id IS DISTINCT FROM OLD.retired_by_id
        THEN
            RAISE EXCEPTION
                'a section update may not change sequence, readiness or retirement.';
        END IF;

        IF NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
            PERFORM submission_dossiers_check_section_parent(
                NEW.id, NEW.parent_id, NEW.dossier_id, NEW.tenant_id
            );
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'unknown dossier section operation: %', op;
END;
$fn$;
"""

INSERT_FN = """
CREATE OR REPLACE FUNCTION submission_dossiers_guard_section_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    -- Symmetric hole: a raw INSERT could otherwise plant a section whose parent
    -- lives in another tenant or another dossier. No window is required here --
    -- creation is not the bypass, and `services.create_section` validates the
    -- same rules before it inserts.
    PERFORM submission_dossiers_check_section_parent(
        NEW.id, NEW.parent_id, NEW.dossier_id, NEW.tenant_id
    );
    RETURN NEW;
END;
$fn$;
"""

TRIGGERS = f"""
CREATE TRIGGER guard_update_dossier_section
BEFORE UPDATE ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_guard_section_update();

CREATE TRIGGER guard_insert_dossier_section
BEFORE INSERT ON {SECTION_TABLE}
FOR EACH ROW EXECUTE FUNCTION submission_dossiers_guard_section_insert();
"""

CREATE_SQL = HIERARCHY_FN + UPDATE_FN + INSERT_FN + TRIGGERS

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_update_dossier_section ON {SECTION_TABLE};
DROP TRIGGER IF EXISTS guard_insert_dossier_section ON {SECTION_TABLE};

DROP FUNCTION IF EXISTS submission_dossiers_guard_section_update();
DROP FUNCTION IF EXISTS submission_dossiers_guard_section_insert();
DROP FUNCTION IF EXISTS submission_dossiers_check_section_parent(bigint, bigint, bigint, bigint);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("submission_dossiers", "0003_section_and_blocker_db_governance"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL),
    ]
