"""No governed module claims regulatory or agency status.

WHY THIS EXISTS

Three modules already carried a banned-phrase guard: `submission_operations`,
`submission_packages` and `external_integrations`, each scanning its own
directory. Milestone 16 found that five governed modules had none —
`submission_dossiers`, `dossier_blueprints`, `dossier_upgrades`,
`regulatory_cases` and `workflows`.

All five were clean when checked, so this closes a **coverage** gap rather than
fixing a defect. That distinction matters: nothing was overclaiming, but nothing
would have noticed if it started. The words this forbids are the ones that turn
an internal workspace into an assertion about what a regulator has accepted, and
they tend to arrive in a UI string or a docstring written in a hurry, which is
precisely where no behavioural test looks.

WHY ONE GUARD RATHER THAN FIVE MORE

The per-module version had drifted into three slightly different banned lists.
A single list applied to every governed module means adding a module to the
platform, rather than remembering to copy a test into it, is what puts it under
guard. The existing per-module tests are left alone: they are not wrong, and
deleting working tests to tidy up is how coverage quietly shrinks.

WHAT IS DELIBERATELY NOT BANNED

`APPROVED` as a workflow state, and `SUBMITTED` as a workflow state. Those are
legitimate internal lifecycle names with an established meaning in this codebase
-- an item approved by a reviewer, not a submission approved by an agency.
Banning the bare words would force a rename of the workflow engine and would say
nothing true. What is banned is the phrasing that asserts an *external* verdict.
"""

import pathlib

import pytest

#: Every module that holds governed regulatory workflow data.
GOVERNED_MODULES = (
    "regulatory_cases",
    "submission_dossiers",
    "dossier_blueprints",
    "dossier_upgrades",
    "submission_operations",
    "submission_packages",
    "external_integrations",
    "workflows",
    "iig_checklist",
)

#: Phrases that assert an outside body has accepted, approved or validated
#: something. Lower-cased before comparison.
BANNED = (
    "agency ready",
    "fda ready",
    "ema ready",
    "fda compliant",
    "ema compliant",
    "submitted to agency",
    "submission accepted",
    "agency accepted",
    "regulatory filed",
    "regulatory approved",
    "regulatory compliant",
    "approved submission",
    "part 11 compliant",
    "21 cfr part 11 compliant",
    "validated system",
    "validated production",
    "gxp validated",
    "exactly-once delivery",
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def _offenders(module: str):
    """Every (file, line, phrase) in `module` that makes a forbidden claim.

    Test files are skipped: a test that asserts a phrase is absent has to name
    it, and treating that as a violation would make the guard unwriteable.
    """
    root = BACKEND / module
    found = []
    if not root.exists():
        return found
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            for phrase in BANNED:
                if phrase in lowered:
                    found.append((path.relative_to(BACKEND).as_posix(), number, phrase))
    return found


@pytest.mark.parametrize("module", GOVERNED_MODULES)
def test_no_governed_module_claims_regulatory_status(module):
    """THE regression test, once per governed module."""
    offenders = _offenders(module)
    assert offenders == [], "\n".join(
        f"{path}:{number} claims {phrase!r}" for path, number, phrase in offenders
    )


def test_the_guard_covers_every_module_that_has_migrations():
    """The guard's own coverage, checked against the tree.

    The gap this test closes was not a missing assertion but a missing *module*
    in someone's list. So the list is compared against what actually exists:
    a new governed app with its own migrations must be added here, and the
    failure says so.
    """
    governed_with_tables = {
        path.parent.parent.name
        for path in BACKEND.glob("*/migrations/0001_initial.py")
        if path.parent.parent.name
        not in {"identity", "tenancy", "authorization", "audit", "common"}
    }
    # Foundation data apps carry no regulatory workflow claims of this kind.
    foundation = {"fda_data", "formulations", "iid_assessment", "templates_registry", "documents"}
    expected = governed_with_tables - foundation

    missing = sorted(expected - set(GOVERNED_MODULES))
    assert missing == [], (
        f"governed app(s) not covered by the regulatory claim guard: {', '.join(missing)}. "
        "Add them to GOVERNED_MODULES, or to `foundation` with a reason."
    )
