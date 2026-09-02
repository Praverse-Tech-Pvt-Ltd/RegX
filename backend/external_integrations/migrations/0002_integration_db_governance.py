"""Database-level governance for connectors, executions and object links.

MIGRATION CLASSIFICATION (docs/RELEASE_ROLLBACK_RUNBOOK.md section 4)

    FORWARD:  Class A. Additive only -- exactly 8 plpgsql functions and 9
              triggers. No table is altered, no column added or dropped, and no
              row is read, written or destroyed.

    ROLLBACK: Class A **on its own terms**. `DROP_SQL` drops exactly the 9
              triggers and 8 functions created here and nothing else. It
              destroys no data; it destroys only the protection.

              (The counts are asserted against the generated SQL by a symmetry
              test that ships with this migration. Milestone 10 shipped a
              docstring claiming five functions and eight triggers where the SQL
              had seven of each, so these numbers are checked by the build
              rather than by proofreading.)

**Removing this protection does NOT make reversing `0001` safe.** `0001` remains
**CLASS C -- DATA RESTORE REQUIRED** once any execution history exists: a
terminal execution is the record that a document or a package left this
deployment, and that record is not derivable from anything else. The remote
system may or may not still have the bytes; RegX's statement about what it sent,
when, and under which configuration exists only here.

---

WHY THIS EXISTS

An execution is evidence. It says which exact bytes went to which configured
destination and how the attempt ended. If it can be rewritten afterwards it
stops being evidence and becomes a note somebody could have edited.

The service layer already enforces every rule below. That is not the guarantee:
`Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
auto-creates, not `objects` -- so restricting the public manager cannot cover
`objects.create()` or a bare `save()`, and a raw cursor, a psql session or a
migration never passes through Python at all.

WHAT EACH TRIGGER ENFORCES

  guard_insert_connector        a connector is coherent on the way in: a
                               positive configuration version, and a
                               configuration that is a JSON object rather than
                               a scalar or a list.
  guard_update_connector        tenant and type never move; the configuration
                               version never decreases, and never stands still
                               while the configuration changes.
  guard_insert_credential_ref   a credential reference belongs to the same
                               tenant as its connector. Milestone 14's version
                               of the cross-tenant coherence rule: tenant A must
                               not be able to name tenant B's credential.
  guard_insert_execution        an execution is coherent on the way in: same
                               tenant as its connector, a configuration version
                               that exists, and QUEUED as the only legal
                               starting state.
  guard_update_execution        identity and provenance frozen always; a
                               terminal execution refuses every UPDATE; status
                               moves only along the documented lifecycle.
  prevent_delete                executions and object links are never deleted.
                               Shared by both tables -- one function, two
                               triggers -- because the rule and the message are
                               identical and two copies would drift.
  guard_insert_object_link      a link is coherent on the way in: same tenant as
                               its connector, and it names a remote object.
  guard_update_object_link      which RegX resource a link is about never moves.
                               The remote identifiers may -- a remote system can
                               re-version its own object -- but repointing a link
                               at a different document would rewrite the answer
                               to "what did we send there".

WHAT THE DATABASE CANNOT PROVE HERE

It cannot tell whether `configuration` is *safe* -- that a `base_url` resolves
to a public address, that a header is on the allow-list, that a path prefix does
not traverse. Reproducing `netpolicy` and `config_schema` in plpgsql would mean
two implementations of a security policy in two languages, and the one that
drifts would be the one nothing tests. The trigger checks shape; Python checks
policy, on write and again on use. Claiming the database validated the
destination would be claiming a guarantee that is not there.

It also cannot tell whether a remote system actually stored anything. Nothing
here, and nothing anywhere in this app, records that as if it were known.
"""

from django.db import migrations

CONNECTOR_TABLE = "external_integrations_connector"
CREDENTIAL_TABLE = "external_integrations_connectorcredentialreference"
EXECUTION_TABLE = "external_integrations_connectorexecution"
LINK_TABLE = "external_integrations_externalobjectlink"

CONNECTOR_INSERT_FN = """
CREATE OR REPLACE FUNCTION external_integrations_guard_connector_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.configuration_version < 1 THEN
        RAISE EXCEPTION 'a connector configuration version starts at 1.';
    END IF;
    -- Shape only. Whether the configuration is *safe* is a Python question;
    -- see the module docstring.
    IF jsonb_typeof(NEW.configuration::jsonb) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'connector configuration must be a json object.';
    END IF;
    RETURN NEW;
END;
$fn$;
"""

CONNECTOR_UPDATE_FN = """
CREATE OR REPLACE FUNCTION external_integrations_guard_connector_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.connector_type IS DISTINCT FROM OLD.connector_type
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'connector identity is immutable.';
    END IF;

    IF NEW.configuration_version < OLD.configuration_version THEN
        RAISE EXCEPTION 'a connector configuration version never decreases.';
    END IF;

    -- The version is what a queued execution compares itself against. A
    -- configuration that changed without it would let a retry follow an edit
    -- while still claiming to be running the version it was created under.
    IF NEW.configuration::text IS DISTINCT FROM OLD.configuration::text
       AND NEW.configuration_version = OLD.configuration_version
    THEN
        RAISE EXCEPTION 'changing a connector configuration must bump its version.';
    END IF;

    IF jsonb_typeof(NEW.configuration::jsonb) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'connector configuration must be a json object.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""

CREDENTIAL_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION external_integrations_guard_credential_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    connector_tenant bigint;
BEGIN
    SELECT tenant_id INTO connector_tenant
      FROM {CONNECTOR_TABLE} WHERE id = NEW.connector_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the connector does not exist.';
    END IF;
    IF connector_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'a credential reference cannot cross tenants.';
    END IF;
    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

EXECUTION_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION external_integrations_guard_execution_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    connector_tenant  bigint;
    connector_version integer;
BEGIN
    SELECT tenant_id, configuration_version INTO connector_tenant, connector_version
      FROM {CONNECTOR_TABLE} WHERE id = NEW.connector_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the connector does not exist.';
    END IF;
    IF connector_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'an execution cannot cross tenants.';
    END IF;

    -- The Milestone 10 lesson: a row that was never checked on the way in
    -- preserves whatever was written, not the truth.
    IF NEW.status <> 'queued' THEN
        RAISE EXCEPTION 'an execution starts queued.';
    END IF;
    IF NEW.finished_at IS NOT NULL THEN
        RAISE EXCEPTION 'a new execution cannot already be finished.';
    END IF;
    IF NEW.connector_configuration_version < 1
       OR NEW.connector_configuration_version > connector_version
    THEN
        RAISE EXCEPTION 'an execution must name a configuration version that exists.';
    END IF;
    IF NEW.idempotency_key IS NULL OR length(NEW.idempotency_key) < 16 THEN
        RAISE EXCEPTION 'an execution must carry an idempotency key.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

EXECUTION_UPDATE_FN = """
CREATE OR REPLACE FUNCTION external_integrations_guard_execution_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    -- Identity and provenance never move, in any state. `resource_public_id`
    -- and the snapshot fields are in here because they are the statement of
    -- *what was transferred*: a row whose subject could be rewritten after the
    -- fact would be worse than no record.
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.connector_id IS DISTINCT FROM OLD.connector_id
       OR NEW.operation IS DISTINCT FROM OLD.operation
       OR NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id
       OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.resource_type IS DISTINCT FROM OLD.resource_type
       OR NEW.resource_public_id IS DISTINCT FROM OLD.resource_public_id
       OR NEW.snapshot_public_id IS DISTINCT FROM OLD.snapshot_public_id
       OR NEW.manifest_checksum IS DISTINCT FROM OLD.manifest_checksum
       OR NEW.connector_configuration_version IS DISTINCT FROM OLD.connector_configuration_version
       OR NEW.configuration_snapshot::text IS DISTINCT FROM OLD.configuration_snapshot::text
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'execution identity and provenance are immutable.';
    END IF;

    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'a % execution cannot be changed.', OLD.status;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'queued'  AND NEW.status IN ('running', 'cancelled', 'failed'))
            OR (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'cancelled'))
        ) THEN
            RAISE EXCEPTION 'an execution cannot move from % to %.', OLD.status, NEW.status;
        END IF;

        IF NEW.status IN ('succeeded', 'failed', 'cancelled') AND NEW.finished_at IS NULL THEN
            RAISE EXCEPTION 'a finished execution must record when it finished.';
        END IF;
    END IF;

    IF NEW.attempt_count < OLD.attempt_count THEN
        RAISE EXCEPTION 'an execution attempt count never decreases.';
    END IF;

    RETURN NEW;
END;
$fn$;
"""

DELETE_FN = """
CREATE OR REPLACE FUNCTION external_integrations_prevent_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'external integration history cannot be deleted.';
END;
$fn$;
"""

LINK_UPDATE_FN = """
CREATE OR REPLACE FUNCTION external_integrations_guard_link_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.public_id IS DISTINCT FROM OLD.public_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.connector_id IS DISTINCT FROM OLD.connector_id
       OR NEW.resource_type IS DISTINCT FROM OLD.resource_type
       OR NEW.resource_public_id IS DISTINCT FROM OLD.resource_public_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'an external object link cannot be repointed.';
    END IF;
    RETURN NEW;
END;
$fn$;
"""

LINK_INSERT_FN = f"""
CREATE OR REPLACE FUNCTION external_integrations_guard_link_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
DECLARE
    connector_tenant bigint;
BEGIN
    SELECT tenant_id INTO connector_tenant
      FROM {CONNECTOR_TABLE} WHERE id = NEW.connector_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the connector does not exist.';
    END IF;
    IF connector_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'an external object link cannot cross tenants.';
    END IF;
    IF NEW.external_object_id IS NULL OR length(NEW.external_object_id) = 0 THEN
        RAISE EXCEPTION 'an external object link must name a remote object.';
    END IF;
    RETURN NEW;
END;
$fn$;
"""  # noqa: S608 - DDL; the only interpolation is the module constant above

CREATE_SQL = (
    CONNECTOR_INSERT_FN
    + CONNECTOR_UPDATE_FN
    + CREDENTIAL_INSERT_FN
    + EXECUTION_INSERT_FN
    + EXECUTION_UPDATE_FN
    + DELETE_FN
    + LINK_INSERT_FN
    + LINK_UPDATE_FN
    + f"""
CREATE TRIGGER guard_insert_connector
    BEFORE INSERT ON {CONNECTOR_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_connector_insert();

CREATE TRIGGER guard_update_connector
    BEFORE UPDATE ON {CONNECTOR_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_connector_update();

CREATE TRIGGER guard_insert_credential_reference
    BEFORE INSERT ON {CREDENTIAL_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_credential_insert();

CREATE TRIGGER guard_insert_execution
    BEFORE INSERT ON {EXECUTION_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_execution_insert();

CREATE TRIGGER guard_update_execution
    BEFORE UPDATE ON {EXECUTION_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_execution_update();

CREATE TRIGGER no_delete_execution
    BEFORE DELETE ON {EXECUTION_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_prevent_delete();

CREATE TRIGGER guard_insert_external_object_link
    BEFORE INSERT ON {LINK_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_link_insert();

CREATE TRIGGER guard_update_external_object_link
    BEFORE UPDATE ON {LINK_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_guard_link_update();

CREATE TRIGGER no_delete_external_object_link
    BEFORE DELETE ON {LINK_TABLE}
    FOR EACH ROW EXECUTE FUNCTION external_integrations_prevent_delete();
"""
)

DROP_SQL = f"""
DROP TRIGGER IF EXISTS guard_insert_connector ON {CONNECTOR_TABLE};
DROP TRIGGER IF EXISTS guard_update_connector ON {CONNECTOR_TABLE};
DROP TRIGGER IF EXISTS guard_insert_credential_reference ON {CREDENTIAL_TABLE};
DROP TRIGGER IF EXISTS guard_insert_execution ON {EXECUTION_TABLE};
DROP TRIGGER IF EXISTS guard_update_execution ON {EXECUTION_TABLE};
DROP TRIGGER IF EXISTS no_delete_execution ON {EXECUTION_TABLE};
DROP TRIGGER IF EXISTS guard_insert_external_object_link ON {LINK_TABLE};
DROP TRIGGER IF EXISTS guard_update_external_object_link ON {LINK_TABLE};
DROP TRIGGER IF EXISTS no_delete_external_object_link ON {LINK_TABLE};

DROP FUNCTION IF EXISTS external_integrations_guard_connector_insert();
DROP FUNCTION IF EXISTS external_integrations_guard_connector_update();
DROP FUNCTION IF EXISTS external_integrations_guard_credential_insert();
DROP FUNCTION IF EXISTS external_integrations_guard_execution_insert();
DROP FUNCTION IF EXISTS external_integrations_guard_execution_update();
DROP FUNCTION IF EXISTS external_integrations_prevent_delete();
DROP FUNCTION IF EXISTS external_integrations_guard_link_insert();
DROP FUNCTION IF EXISTS external_integrations_guard_link_update();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("external_integrations", "0001_initial"),
    ]

    operations = [migrations.RunSQL(sql=CREATE_SQL, reverse_sql=DROP_SQL)]
