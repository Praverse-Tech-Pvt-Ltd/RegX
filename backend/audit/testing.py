"""Test support for QA-09: make every audit write fail, for real, in PostgreSQL.

The governed-write pattern (QA-09) is: a change and the audit record that describes
it are written in ONE `transaction.atomic()` block, the emit inside the block. Then
they commit together or not at all.

`audit_writes_fail()` proves it for a path: it installs a trigger that refuses every
INSERT into `audit_auditevent`, so the path's emit raises. A path that follows the
pattern rolls its change back; a path that does not leaves the change committed with
no audit record. Use it in `django_db(transaction=True)` tests, so the trigger and the
code under test run with real commits (no surrounding test transaction).
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import connection

_FAIL = """
CREATE OR REPLACE FUNCTION qa09_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF {when} THEN RAISE EXCEPTION 'QA-09 injected audit failure'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER qa09_fail_audit BEFORE INSERT ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION qa09_fail_audit();
"""
_UNDO = (
    "DROP TRIGGER IF EXISTS qa09_fail_audit ON audit_auditevent; "
    "DROP FUNCTION IF EXISTS qa09_fail_audit();"
)


@contextmanager
def audit_writes_fail(when: str = "true"):
    """Every audit INSERT inside the block raises, or only those matching `when` (an SQL
    condition on NEW, e.g. "NEW.actor_id IS NOT NULL"; test code only).

    Call the code under test through `attempt()`: the test asserts on the database
    afterwards, not on how the failure surfaced (a 500 in production)."""
    with connection.cursor() as cur:
        cur.execute(_FAIL.format(when=when))
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute(_UNDO)


def attempt(fn, *args, **kwargs):
    """Call `fn`; return its result, or None if it raised (the injected failure)."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None
