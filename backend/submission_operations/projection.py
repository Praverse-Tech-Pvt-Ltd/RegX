"""Which modules the caller may be told about, and what "no answer" looks like.

ZERO AND NULL ARE DIFFERENT ANSWERS
-----------------------------------
`0` means *there are none*. `null` means *you are not entitled to know*. A
dashboard that renders `0` for a module the caller cannot see is not being
cautious, it is lying -- and worse, it is lying in a way that is
indistinguishable from the truth right up until the tenant actually has twelve
of the thing, at which point the caller learns the count is real. Returning `0`
also leaks on the way back: a caller who sees `0` documents today and `0`
tomorrow has learned something about a module they were never granted.

So an unavailable dimension is `None` all the way through the service layer and
`null` on the wire, and the frontend renders "Unavailable", never a number.

WHY A DEDICATED TYPE
--------------------
This could have been a convention -- "remember to check the permission before
you count" -- and conventions of that shape fail silently the first time
somebody adds a field. `Visibility` makes it structural: the aggregation code
cannot reach a restricted module's numbers without going through a gate that
returns `None`, and `restricted_projection` is the single place that decides
what an unavailable section looks like.
"""

from dataclasses import dataclass

#: Every module the dashboard can read from, and the authoritative view
#: permission that governs it. The dashboard invents none of these -- each is the
#: same codename that module's own API checks, so a caller sees exactly the
#: aggregate of what they could already have read one page at a time.
MODULE_CASES = "cases"
MODULE_DOSSIERS = "dossiers"
MODULE_DOCUMENTS = "documents"
MODULE_WORKFLOWS = "workflows"
MODULE_CHECKLISTS = "checklists"
MODULE_BLUEPRINTS = "blueprints"
MODULE_UPGRADES = "upgrades"

ALL_MODULES = (
    MODULE_CASES,
    MODULE_DOSSIERS,
    MODULE_DOCUMENTS,
    MODULE_WORKFLOWS,
    MODULE_CHECKLISTS,
    MODULE_BLUEPRINTS,
    MODULE_UPGRADES,
)


@dataclass(frozen=True)
class Visibility:
    """What this caller may be told about, resolved once per request.

    Frozen: a request's visibility is a fact about the caller, not a working
    variable. Recomputing it mid-request -- or worse, mutating it -- is how a
    panel ends up rendered against a different answer than the one the gate
    gave.
    """

    cases: bool
    dossiers: bool
    documents: bool
    workflows: bool
    checklists: bool
    blueprints: bool
    upgrades: bool

    def allows(self, module: str) -> bool:
        return bool(getattr(self, module))

    def gate(self, module: str, value):
        """`value` if the caller may know it, otherwise `None`.

        Callers pass a **computed** value here, so this is the last line of
        defence rather than the only one: for anything expensive, check
        `allows()` first and skip the query entirely. Running a restricted
        query and discarding the result wastes the database and, more
        importantly, invites a later edit to use the intermediate value.
        """
        return value if self.allows(module) else None

    @property
    def restricted_modules(self) -> list[str]:
        return [m for m in ALL_MODULES if not self.allows(m)]


def visibility_for(user, tenant) -> Visibility:
    """Resolve every module gate once, through each module's own helper.

    Deliberately not a loop over a table of codenames: each helper is imported
    by name so that deleting or renaming one is an import error here rather than
    a silently-False lookup that quietly opens a panel nobody re-reviewed.
    """
    from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
    from documents.permissions import has_document_permission
    from dossier_blueprints.permissions import PERM_VIEW as BLUEPRINTS_VIEW
    from dossier_blueprints.permissions import has_blueprint_permission
    from dossier_upgrades.permissions import PERM_VIEW as UPGRADES_VIEW
    from dossier_upgrades.permissions import has_upgrade_permission
    from iig_checklist.permissions import PERM_VIEW_EXECUTION as CHECKLISTS_VIEW
    from iig_checklist.permissions import has_iig_checklist_permission
    from regulatory_cases.permissions import PERM_VIEW as CASES_VIEW
    from regulatory_cases.permissions import has_case_permission
    from submission_dossiers.permissions import PERM_VIEW as DOSSIERS_VIEW
    from submission_dossiers.permissions import has_dossier_permission
    from workflows.permissions import PERM_VIEW as WORKFLOWS_VIEW
    from workflows.permissions import has_workflow_permission

    return Visibility(
        cases=has_case_permission(user, tenant, CASES_VIEW),
        dossiers=has_dossier_permission(user, tenant, DOSSIERS_VIEW),
        documents=has_document_permission(user, tenant, DOCUMENTS_VIEW),
        workflows=has_workflow_permission(user, tenant, WORKFLOWS_VIEW),
        checklists=has_iig_checklist_permission(user, tenant, CHECKLISTS_VIEW),
        blueprints=has_blueprint_permission(user, tenant, BLUEPRINTS_VIEW),
        upgrades=has_upgrade_permission(user, tenant, UPGRADES_VIEW),
    )


def restricted_projection() -> None:
    """What an unavailable module looks like. Exactly `None` -- never `{}`, never
    a dict of zeroes, never an object with a `restricted` flag beside real
    numbers, because every one of those has to be defended against on the
    frontend too and one missed branch renders a zero."""
    return None
