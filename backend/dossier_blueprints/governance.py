"""The governed-mutation exception for blueprints, and why there is no window.

Milestone 9 needed a *sanctioned window* -- a transaction-scoped declaration of
which operation was running -- because a `DossierSection` is legitimately mutable
by four different operations with four different column sets, and the database
had no other way to tell a reorder from a readiness write from an arbitrary
rewrite.

**Blueprints do not have that problem, so they do not get that mechanism.**

A blueprint version's own `status` is the discriminator:

    DRAFT      structure is editable
    ACTIVE     structure is frozen forever
    RETIRED    structure is frozen forever

The `0002` triggers read the version's status directly. That is strictly better
than a session parameter here: it cannot be forgotten by a caller, it cannot be
left open, it needs no Python cooperation at all, and it is the same fact a human
reviewer reads off the row. Adding a window on top would add a mechanism without
adding a guarantee, and every mechanism is another thing to get wrong.

Where a caller identity *is* needed -- who activated, who retired -- it is a
stamped column, not an ambient context.
"""


class BlueprintMutationForbidden(Exception):
    """Raised when a governed blueprint row is mutated outside the service layer.

    Defined in its own module so `models` can import it without a cycle, and
    re-exported from `dossier_blueprints.models`, which is where callers look.
    """
