# Lock order register

Every operation that takes more than one row lock, in the order it takes them.

**This records what the code does.** Where an ordering is enforced only by
convention and not by a test, it says so. A register that describes an intended
discipline rather than the actual one is worse than none, because it is read as
proof.

## Why order is the whole discipline

Two transactions that take the same locks in the same order queue. Two that take
them in opposite orders deadlock, and PostgreSQL resolves it by killing one —
which surfaces as an intermittent 500 under load and is close to impossible to
reproduce on demand. The rule is therefore not "take fewer locks", it is **take
them in one order everywhere**.

## Register

| Operation | Lock 1 | Lock 2 | Lock 3 | Why | Conflicts with | Deadlock test |
|---|---|---|---|---|---|---|
| `workflows.perform_transition` | `WorkflowItem` | — | — | The item is the serialization point; the transition table decides the rest | another transition on the same item | `workflows/tests/test_transition_concurrency.py` |
| `submission_dossiers` section mutation | `SubmissionDossier` | `DossierSection` | — | The dossier is the parent and the readiness projection is computed from it, so it is the coarser lock and is taken first | upgrade apply, other section mutations | code inspection only — see below |
| `dossier_upgrades.apply_plan` | `SubmissionDossier` | `DossierUpgradePlan` | `DossierBlueprintVersion` by `version_number` | **Dossier first**, matching section mutation, so applying a plan and editing a section cannot invert | section mutation, plan item changes | code inspection only — see below |
| `dossier_upgrades.set_item_status` | `DossierUpgradePlan` | `DossierUpgradePlanItem` | — | Plan before item, so two item changes on one plan queue | `apply_plan`, another item change | covered by plan-level serialization |
| `dossier_blueprints` version/section edits | `DossierBlueprint` | `DossierBlueprintVersion` | `BlueprintSection` | Outer to inner; activation also locks the sibling version set so "only one active" holds | another activation, section edit | existing M10 tests |
| `submission_packages` entry mutation / freeze | `SubmissionPackage` | `SubmissionPackageEntry` by pk | — | The package row decides freeze-vs-add; entries are locked in pk order so two multi-entry operations agree | freeze vs add entry | M13 `test_export_clone_concurrency.py` |
| `submission_packages.clone_package` | **family root** `SubmissionPackage` | source `SubmissionPackage` | — | Two clones of two different revisions lock two different source rows, so the source lock serializes nothing between them. The family root is the same row for every member | another clone in the same family | M13 `test_review_fixes.py` |
| `external_integrations.create_execution` | `Connector` | — | — | The connector's status is re-read under its own lock, so an execution cannot be queued onto a connector that was just disabled | disable, config edit | `external_integrations/tests/test_execution_concurrency.py` |
| `external_integrations.claim_execution` | `ConnectorExecution` | — | — | Exactly one worker moves QUEUED → RUNNING; the loser sees a non-QUEUED status and stops before any remote call | a second worker, a duplicate delivery | `external_integrations/tests/test_execution_concurrency.py` |
| `templates_registry` version lifecycle | `TemplateVersion` | `Template` | — | Version then template, consistently | another lifecycle transition | existing M4 tests |
| `iig_checklist` execution mutation | `ChecklistExecution` | responses **ordered by pk** | — | The pk ordering is what stops two multi-response writes inverting | another response write, cascade | existing M7 tests |
| `regulatory_cases.create_case` | counter row (`get_or_create`) | — | — | The counter is the serialization point, so two concurrent creates take different numbers | another create | existing M8 tests |

## Findings

**No inversion was found.** The two operations that touch both a dossier and
something owned by it — section mutation and upgrade apply — both take
`SubmissionDossier` first. `apply_plan` says so in a comment at the lock site,
and the register now records it as a fact rather than a local note.

**That pair is verified by code inspection, not by a deadlock test**, and the
table says so. Building the fixture for a concurrent apply-versus-edit race
needs a blueprint, a dossier instantiated from it, a generated plan and a
section, and Milestone 15 did not build it. Recording it as tested when it is
not would be exactly the failure Milestone 11 shipped — a claimed test that
lived somewhere else. Every ordering in the table that *is* covered by a test
names the file.

The evidence for the pair is direct: both call sites take
`SubmissionDossier.objects.select_for_update()` before locking anything they
own, `dossier_upgrades/services.py` carries a `LOCK ORDER` comment at the site,
and no call site anywhere takes a section or plan lock before the dossier.

The one ordering that is *not* obvious from reading a single function is the
package family root, which exists precisely because the intuitive lock (the
source package) is the wrong one. Milestone 13 found that by testing two clones
of two different revisions; nothing about the code reads as wrong until you ask
what two transactions on different rows serialize on.

## Where the concurrency tests live

With the domain they test, not in `common`. The first version of these tests was
placed in `common/tests/` because they span domains — and `import-linter` refused
it: `common` is the innermost layer, and a test there importing
`external_integrations.services` and `audit.models` inverts the architecture just
as surely as production code would.

Only the thread-running helper is shared, in `common.concurrency_testing`, and it
imports nothing from any domain. That is what makes the placement legal rather
than merely convenient.

## What is deliberately not locked

* **Read paths take no locks.** The dashboard, the tree, and every list are
  ordinary reads. A read that took locks would turn a slow page into a source of
  contention for writers.
* **`ConnectorExecution` does not lock its `Connector` while running.** The
  configuration it uses was snapshotted at creation, so it does not need the row
  to stay still; holding a connector lock for the length of a remote call would
  block every other execution on that connector for as long as the network takes.

## Adding to this register

If a new operation takes two locks, it goes in the table before it merges, and
the ordering must match anything already listed for the same pair. If it cannot,
that is a design question rather than a documentation one.
