"""The governed-mutation exception for upgrade plans, and why there is no window.

Milestone 9 needed a sanctioned *window* -- a transaction-scoped declaration of
which operation was running -- because a `DossierSection` is legitimately mutable
by four operations with four different column sets, and the database had no
other way to tell one from another.

Upgrade plans do not have that problem, for the same reason blueprints did not:
a plan's own `status` is the discriminator.

    DRAFT / READY   items may be accepted, rejected, re-reviewed
    APPLIED         frozen forever
    CANCELLED       frozen forever

The `0002` triggers read that status directly. It cannot be forgotten by a
caller, it cannot be left open, it needs no Python cooperation, and it is the
same fact a reviewer reads off the row.

Applied history -- `DossierUpgradeApplication` and `UpgradeSectionOrigin` -- is
simpler still: it refuses UPDATE and DELETE outright, because there is no
legitimate edit to a record that an upgrade happened.
"""


class UpgradeMutationForbidden(Exception):
    """Raised when a governed upgrade row is mutated outside the service layer.

    Defined here so `models` can import it without a cycle, and re-exported from
    `dossier_upgrades.models`, which is where callers look.
    """
