"""Sanctioned-write windows for `DossierSection`.

THE PROBLEM

Milestone 9 closed section DELETE at three layers but deliberately left
`update()`, `bulk_update()` and `save()` open, because two sanctioned operations
need them: `reorder_section` renumbers a sibling group with `.update()`, and
`recalculate_dossier` writes derived readiness with `.bulk_update()`.

That left a governance bypass. Any caller holding the ORM could write columns no
service path would ever let them write::

    DossierSection.objects.filter(pk=s.pk).update(tenant_id=other.pk)
    DossierSection.objects.filter(pk=s.pk).update(readiness="ready")
    s.parent = one_of_its_own_descendants; s.save()

skipping hierarchy validation, tenant scoping, cycle prevention, derived
readiness, terminal-dossier gating and audit in one step.

WHY A BLANKET BAN IS THE WRONG FIX

Banning `update()`/`bulk_update()` outright breaks reorder and readiness. Banning
them "except when services call them" is not expressible in the ORM alone -- and
an ORM-only rule is not a floor anyway, because a raw cursor, a psql session or a
migration never passes through Python.

THE APPROACH

A **sanctioned window**: a transaction-scoped declaration of *which* operation is
running, readable by both layers.

  * Python side -- a thread-local, so the model and queryset guards can refuse
    an unsanctioned write with a clear `DossierMutationForbidden` instead of a
    database error.
  * Database side -- a PostgreSQL run-time parameter set with `set_config(...,
    is_local => true)`, i.e. `SET LOCAL`, so the trigger in `0004` can see the
    same declaration and enforce a per-operation column allow-list.

`SET LOCAL` is **transaction-scoped**: it is discarded on COMMIT or ROLLBACK, so
a window cannot leak into the next request even on a pooled or long-lived
connection. `section_write` additionally clears it on the way out, so the window
is no wider than the statements that need it.

The window is a *declaration of intent*, not an authorisation. It says "this
statement is the reorder", and the trigger then holds that statement to exactly
what a reorder may touch. Declaring `reorder` and then writing `tenant_id` is
refused just as firmly as declaring nothing at all -- and the columns that are
never writable by anyone (`tenant_id`, `dossier_id`, `public_id`,
`created_by_id`, `created_at`) are refused under every window.

Opening a window therefore grants nothing on its own. Its only power is to
distinguish four narrow, individually policed operations from arbitrary
mutation, and each remains policed on its own terms.
"""

import threading
from contextlib import contextmanager, suppress

from django.db import DatabaseError, connection, transaction

#: PostgreSQL run-time parameter read by the `0004` trigger. Custom parameters
#: must be namespaced with a dot or PostgreSQL rejects them.
SECTION_OP_SETTING = "regx.dossier_section_op"

#: The only four sanctioned kinds of `DossierSection` UPDATE. Each maps to one
#: service function and to one column allow-list in the trigger.
OP_UPDATE = "update"
OP_REORDER = "reorder"
OP_RECALCULATE = "recalculate"
OP_RETIRE = "retire"

SANCTIONED_OPERATIONS = frozenset({OP_UPDATE, OP_REORDER, OP_RECALCULATE, OP_RETIRE})

_state = threading.local()


class DossierMutationForbidden(Exception):
    """Raised when a governed dossier row is mutated outside the service layer.

    Defined here rather than in `models` so `models` can import it without a
    cycle. Re-exported from `submission_dossiers.models`, which is where callers
    and tests have always found it.
    """


class SectionWriteForbidden(DossierMutationForbidden):
    """A `DossierSection` UPDATE attempted outside a sanctioned window.

    A subclass, so `except DossierMutationForbidden` catches every governed
    refusal in this app and a caller never has to know which layer said no.
    """


def current_operation():
    """The sanctioned operation running on this thread, or None."""
    return getattr(_state, "operation", None)


def require_window(detail: str) -> None:
    """Refuse a write that is not inside a sanctioned window.

    The Python layer exists to give the accidental caller a clear error rather
    than a database exception. It is **not** the guarantee -- `0004` is, and it
    holds for a raw cursor that never runs this function.
    """
    if current_operation() is None:
        raise SectionWriteForbidden(
            f"{detail} Dossier sections are governed: go through "
            f"submission_dossiers.services, which opens a sanctioned write window."
        )


@contextmanager
def section_write(operation: str):
    """Declare that the statements inside are one sanctioned operation.

    Must run inside a transaction: `SET LOCAL` outside one would either error or
    silently apply to a single implicit transaction, and either way the trigger
    would not see it where it is needed.
    """
    if operation not in SANCTIONED_OPERATIONS:
        raise ValueError(f"Unknown sanctioned operation: {operation!r}")
    if not transaction.get_connection().in_atomic_block:
        raise SectionWriteForbidden(
            "A sanctioned section write window must be opened inside a transaction."
        )

    previous = current_operation()
    if previous is not None:
        # Nesting would make the effective allow-list ambiguous: the inner
        # operation's columns, the outer's, or the union? Refusing keeps every
        # statement attributable to exactly one operation.
        raise SectionWriteForbidden(
            f"A {previous!r} write window is already open; {operation!r} cannot nest inside it."
        )

    _state.operation = operation
    _set_db_parameter(operation)
    try:
        yield
    finally:
        _state.operation = None
        # Closing early is not required for correctness -- `SET LOCAL` dies with
        # the transaction either way -- but it narrows the window to the
        # statements that need it.
        #
        # If a guard raised, the transaction is already aborted and will refuse
        # this statement too. Suppressed narrowly, and only for a database
        # error, so the caller still sees the refusal that actually matters.
        with suppress(DatabaseError):
            _set_db_parameter("")


def _set_db_parameter(value: str) -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT set_config(%s, %s, true)", [SECTION_OP_SETTING, value])
