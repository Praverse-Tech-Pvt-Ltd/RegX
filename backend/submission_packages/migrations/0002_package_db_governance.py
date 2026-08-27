"""Database-level governance for packages, entries and frozen manifests.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- exactly 7 plpgsql functions and 7
              triggers. No table is altered, no column is added or dropped, and
              no row is read, written or destroyed.

    ROLLBACK: Class A **on its own terms**. `DROP_SQL` drops exactly the 7
              triggers and 7 functions created here and nothing else. It
              destroys no data; it destroys only the protection.

              (These counts are asserted against the generated SQL by a symmetry
              test. Milestone 10 shipped a docstring claiming five functions and
              eight triggers where the SQL had seven of each, and Milestone 11
              claimed a test covered its counts when none did -- so these numbers
              are checked by the build rather than by proofreading.)

**Removing this protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any package data exists.

---

WHY THIS EXISTS

A frozen package is a claim about which exact document versions were assembled,
in what order, under what paths, and what the manifest of that assembly hashed
to. If any of it can be rewritten afterwards, it stops being a claim and becomes
a guess with a checksum attached.

The service layer already enforces every rule below. That is not the guarantee:
`Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
auto-creates, not `objects` -- so restricting the public manager cannot cover
`objects.create()` or a bare `save()`, and a raw cursor, a psql session or a
migration never passes through Python at all.

WHY THERE IS NO SANCTIONED WINDOW

Milestone 9 needed a transaction-scoped operation declaration because a
`DossierSection` is legitimately mutable by four operations with four different
column sets. Package rows are not: the package's own `status` is the
discriminator, exactly as a blueprint version's and an upgrade plan's are. The
trigger reads it directly, so it cannot be forgotten, cannot be left open, and
needs no Python cooperation.

WHAT EACH TRIGGER ENFORCES

  guard_update_package         identity and provenance frozen always; a FROZEN
                               or CANCELLED package refuses every UPDATE; only
                               DRAFT<->IN_REVIEW->FROZEN and open->CANCELLED.
  no_delete_package            packages are never deleted.
  guard_insert_package_entry   an entry is coherent on the way in: same tenant
                               as its package, a document version owned by that
                               tenant, and a dossier section on the package's
                               own case. The Milestone 10 lesson -- freezing a
                               row that was never checked on the way in
                               preserves whatever was written, not the truth.
  guard_update_package_entry   the binding is immutable; only removal and
                               sequence may move, and only while the package is
                               DRAFT.
  guard_delete_package_entry   entries are retired, never deleted.
  guard_insert_snapshot        a snapshot is coherent with the package it
                               describes.
  freeze_snapshot              a manifest, once written, refuses UPDATE and
                               DELETE outright.

WHAT THE DATABASE CANNOT PROVE HERE

The trigger checks that a snapshot's `manifest_checksum` is a 64-character
lowercase hex string and that its counts agree with the package. It does **not**
recompute SHA-256 over the JSON: doing that in plpgsql would require reproducing
Python's exact canonical serialisation -- key ordering, separators, Unicode
escaping -- in a second language, and two implementations of a canonical form
drift. The cryptographic binding is proved by the freeze transaction and by the
manifest being immutable thereafter. Claiming the database verifies the hash
would be claiming a guarantee that is not there.
"""

from django.db import migrations

PACKAGE_TABLE = "submission_packages_submissionpackage"
ENTRY_TABLE = "submission_packages_submissionpackageentry"
SNAPSHOT_TABLE = "submission_packages_submissionpackagesnapshot"
VERSION_TABLE = "documents_documentversion"
DOCUMENT_TABLE = "documents_document"
SECTION_TABLE = "submission_dossiers_dossiersection"
DOSSIER_TABLE = "submission_dossiers_submissiondossier"

PACKAGE_UPDATE_FN = """
CREATE OR REPLACE FUNCTION submission_packages_guard_package_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    -- Identity and provenance never move, in any state.
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.regulatory_case_id IS DISTINCT FROM OLD.regulatory_case_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.source_package_id IS DISTINCT FROM OLD.source_package_id
       OR NEW.revision_number IS DISTINCT FROM OLD.revision_number
    THEN
        RAISE EXCEPTION 'package identity and provenance are immutable.';
    END IF;

    IF OLD.status IN ('frozen', 'cancelled') THEN
        RAISE EXCEPTION 'a % package cannot be changed.', OLD.status;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'draft'     AND NEW.status IN ('in_review', 'cancelled'))
            OR (OLD.status = 'in_review' AND NEW.status IN ('draft', 'frozen', 'cancelled'))
        ) THEN
            RAISE EXCEPTION 'package status cannot move from % to %.', OLD.status, NEW.status;
        END IF;

        IF NEW.status = 'frozen' THEN
            IF NEW.frozen_at IS NULL OR NEW.frozen_by_id IS NULL THEN
                RAISE EXCEPTION 'a frozen package must record who froze it and when.';
            END IF;
            IF NEW.manifest_checksum IS NULL OR NEW.manifest_checksum !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'a frozen package must carry a sha-256 manifest checksum.';
            END IF;
        END IF;

        IF NEW.status = 'cancelled' AND (NEW.cancelled_at IS NULL OR NEW.cancelled_by_id IS NULL)
        THEN
            RAISE EXCEPTION 'a cancelled package must record who cancelled it and when.';
        END IF;
    ELSE
        -- No status change, so the freeze stamps must not appear either.
        IF NEW.frozen_at IS DISTINCT FROM OLD.frozen_at
           OR NEW.frozen_by_id IS DISTINCT FROM OLD.frozen_by_id
           OR NEW.manifest_checksum IS DISTINCT FROM OLD.manifest_checksum
        THEN
            RAISE EXCEPTION 'freeze stamps may only be written by a freeze.';
        END IF;
    END IF;

    RETURN NEW;
END;
$fn$;
"""

PACKAGE_DELETE_FN = """
CREATE OR REPLACE FUNCTION submission_packages_prevent_package_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'submission packages cannot be deleted.';
END;
$fn$;
"""

ENTRY_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION submission_packages_guard_entry_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    pkg_tenant   bigint;
    pkg_case     bigint;
    pkg_status   varchar;
    ver_tenant   bigint;
    sec_tenant   bigint;
    sec_case     bigint;
BEGIN
    SELECT tenant_id, regulatory_case_id, status
      INTO pkg_tenant, pkg_case, pkg_status
      FROM {PACKAGE_TABLE} WHERE id = NEW.package_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'package entry references a package that does not exist.';
    END IF;

    IF pkg_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'package entry tenant does not match its package.';
    END IF;
    IF pkg_status NOT IN ('draft') THEN
        RAISE EXCEPTION 'entries may only be added while the package is draft.';
    END IF;

    -- DocumentVersion carries no tenant of its own; ownership is via document.
    SELECT d.tenant_id INTO ver_tenant
      FROM {VERSION_TABLE} v JOIN {DOCUMENT_TABLE} d ON d.id = v.document_id
     WHERE v.id = NEW.document_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'package entry references a document version that does not exist.';
    END IF;
    IF ver_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'package entry cites a document version from another tenant.';
    END IF;

    IF NEW.dossier_section_id IS NOT NULL THEN
        SELECT s.tenant_id, dd.regulatory_case_id INTO sec_tenant, sec_case
          FROM {SECTION_TABLE} s JOIN {DOSSIER_TABLE} dd ON dd.id = s.dossier_id
         WHERE s.id = NEW.dossier_section_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'package entry references a section that does not exist.';
        END IF;
        IF sec_tenant IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'package entry links a section from another tenant.';
        END IF;
        IF sec_case IS DISTINCT FROM pkg_case THEN
            RAISE EXCEPTION 'package entry links a section from another case.';
        END IF;
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constants above

ENTRY_UPDATE_FN = f"""
CREATE OR REPLACE FUNCTION submission_packages_guard_entry_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    pkg_status varchar;
BEGIN
    -- The binding is the entry. None of it may ever move, in any state: a
    -- package that could re-point an entry at different bytes after the fact
    -- would make every frozen manifest a statement about nothing.
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.package_id IS DISTINCT FROM OLD.package_id
       OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.dossier_section_id IS DISTINCT FROM OLD.dossier_section_id
       OR NEW.logical_path IS DISTINCT FROM OLD.logical_path
       OR NEW.export_filename IS DISTINCT FROM OLD.export_filename
       OR NEW.added_by_id IS DISTINCT FROM OLD.added_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'a package entry binding is immutable.';
    END IF;

    SELECT status INTO pkg_status FROM {PACKAGE_TABLE} WHERE id = OLD.package_id;
    IF pkg_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'package entries can only change while the package is draft.';
    END IF;

    IF OLD.removed_at IS NOT NULL AND NEW.removed_at IS DISTINCT FROM OLD.removed_at THEN
        RAISE EXCEPTION 'a removed package entry cannot be reinstated.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

ENTRY_DELETE_FN = """
CREATE OR REPLACE FUNCTION submission_packages_prevent_entry_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'package entries are retired, never deleted.';
END;
$fn$;
"""

SNAPSHOT_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION submission_packages_guard_snapshot_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    pkg_tenant bigint;
    live_count integer;
BEGIN
    SELECT tenant_id INTO pkg_tenant FROM {PACKAGE_TABLE} WHERE id = NEW.package_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'manifest references a package that does not exist.';
    END IF;
    IF pkg_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'manifest tenant does not match its package.';
    END IF;

    IF NEW.manifest_checksum IS NULL OR NEW.manifest_checksum !~ '^[0-9a-f]{{64}}$' THEN
        RAISE EXCEPTION 'manifest checksum must be a sha-256 hex digest.';
    END IF;
    IF NEW.frozen_at IS NULL OR NEW.frozen_by_id IS NULL THEN
        RAISE EXCEPTION 'a manifest must record who froze it and when.';
    END IF;

    -- The count must match the package's live active entries. This is a real
    -- coherence check; it is NOT a verification of the JSON hash, which the
    -- docstring explains is deliberately not attempted here.
    SELECT count(*) INTO live_count
      FROM {ENTRY_TABLE}
     WHERE package_id = NEW.package_id AND removed_at IS NULL;
    IF live_count IS DISTINCT FROM NEW.entry_count THEN
        RAISE EXCEPTION 'manifest entry count does not match the package.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constants above

SNAPSHOT_FREEZE_FN = """
CREATE OR REPLACE FUNCTION submission_packages_freeze_snapshot()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a frozen package manifest cannot be deleted.';
    END IF;
    RAISE EXCEPTION 'a frozen package manifest cannot be changed.';
END;
$fn$;
"""

CREATE_SQL = (
    PACKAGE_UPDATE_FN
    + PACKAGE_DELETE_FN
    + ENTRY_INSERT_FN
    + ENTRY_UPDATE_FN
    + ENTRY_DELETE_FN
    + SNAPSHOT_INSERT_FN
    + SNAPSHOT_FREEZE_FN
    + f"""
CREATE TRIGGER guard_update_package
    BEFORE UPDATE ON {PACKAGE_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_guard_package_update();

CREATE TRIGGER no_delete_package
    BEFORE DELETE ON {PACKAGE_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_prevent_package_delete();

CREATE TRIGGER guard_insert_package_entry
    BEFORE INSERT ON {ENTRY_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_guard_entry_insert();

CREATE TRIGGER guard_update_package_entry
    BEFORE UPDATE ON {ENTRY_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_guard_entry_update();

CREATE TRIGGER guard_delete_package_entry
    BEFORE DELETE ON {ENTRY_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_prevent_entry_delete();

CREATE TRIGGER guard_insert_package_snapshot
    BEFORE INSERT ON {SNAPSHOT_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_guard_snapshot_insert();

CREATE TRIGGER freeze_package_snapshot
    BEFORE UPDATE OR DELETE ON {SNAPSHOT_TABLE}
    FOR EACH ROW EXECUTE FUNCTION submission_packages_freeze_snapshot();
"""
)

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_update_package ON {PACKAGE_TABLE};
DROP TRIGGER IF EXISTS no_delete_package ON {PACKAGE_TABLE};
DROP TRIGGER IF EXISTS guard_insert_package_entry ON {ENTRY_TABLE};
DROP TRIGGER IF EXISTS guard_update_package_entry ON {ENTRY_TABLE};
DROP TRIGGER IF EXISTS guard_delete_package_entry ON {ENTRY_TABLE};
DROP TRIGGER IF EXISTS guard_insert_package_snapshot ON {SNAPSHOT_TABLE};
DROP TRIGGER IF EXISTS freeze_package_snapshot ON {SNAPSHOT_TABLE};

DROP FUNCTION IF EXISTS submission_packages_guard_package_update();
DROP FUNCTION IF EXISTS submission_packages_prevent_package_delete();
DROP FUNCTION IF EXISTS submission_packages_guard_entry_insert();
DROP FUNCTION IF EXISTS submission_packages_guard_entry_update();
DROP FUNCTION IF EXISTS submission_packages_prevent_entry_delete();
DROP FUNCTION IF EXISTS submission_packages_guard_snapshot_insert();
DROP FUNCTION IF EXISTS submission_packages_freeze_snapshot();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("submission_packages", "0001_initial"),
        ("documents", "0001_initial"),
        ("submission_dossiers", "0004_section_update_governance"),
    ]

    operations = [migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL)]
