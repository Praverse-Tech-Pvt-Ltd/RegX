# Migration inventory — Milestones 9 to 15

Every migration the stacked release introduces, classified against
[`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

**Classifications here were verified against migration code, not copied from the
comments in it.** Where a migration states its own class, that statement was
checked by reading its `reverse_sql` and its operations. One omission was found;
it is recorded below.

## What the release contains

15 migrations across 5 apps, introduced by 16 commits between `8c4d19d` (the
Milestone 8 merge) and `77b0aeb` (the Milestone 15 head).

Milestone 12 and Milestone 15 introduce **no migrations at all** — M12 is a read
model over existing tables, and M15 changed only Python and settings. Rolling
either back is a plain code revert with no schema or data consequence.

| App | New migrations | Milestone |
|---|---|---|
| `submission_dossiers` | 4 | M9 |
| `dossier_blueprints` | 3 | M10 |
| `dossier_upgrades` | 3 | M11 |
| `submission_packages` | 3 | M13 |
| `external_integrations` | 2 | M14 |

## The inventory

| App | Migration | Purpose | Forward risk | Reverse class | Data loss risk | Trigger / function dependency | Required operator action |
|---|---|---|---|---|---|---|---|
| `submission_dossiers` | `0001_initial` | Dossier, section, blocker, three link tables | **A** — six `CreateModel`, additive | **C** once any dossier exists | **Total** for dossier structure, section status history, blocker resolution provenance | none created; target of `0002`–`0004` | Restore from backup; never reverse |
| `submission_dossiers` | `0002_section_link_db_immutability` | Link rows cannot be deleted or repointed | **A** — additive | **A** on its own terms | none — drops protection only | +2 functions, +6 triggers (2 templates × 3 link tables) | none |
| `submission_dossiers` | `0003_section_and_blocker_db_governance` | Section delete and blocker history floor | **A** — additive | **A** on its own terms | none — drops protection only | +3 functions, +3 triggers | none |
| `submission_dossiers` | `0004_section_update_governance` | Closes the direct-ORM section mutation bypass | **A** — additive | **A** on its own terms | none — drops protection only | +3 functions, +2 triggers | none |
| `dossier_blueprints` | `0001_initial` | Blueprint, version, section, instantiation, section origin | **A** — five `CreateModel`, additive | **C** once any blueprint or instantiation exists | **Total** for published structure and instantiation provenance | none created | Restore from backup; never reverse |
| `dossier_blueprints` | `0002_blueprint_db_governance` | Published structure and provenance floor | **A** — additive | **A** on its own terms | none — drops protection only | +7 functions, +7 triggers | none |
| `dossier_blueprints` | `0003_provenance_insert_governance` | Validates provenance rows on INSERT, not only UPDATE | **A** — additive | **A** on its own terms | none — drops protection only | +2 functions, +2 triggers | none |
| `dossier_upgrades` | `0001_initial` | Upgrade plan, plan item, application, section origin | **A** — four `CreateModel`, additive | **C** once any governed upgrade data exists | **Total** for what was applied to which dossier, from which version | none created | Restore from backup; never reverse |
| `dossier_upgrades` | `0002_upgrade_db_governance` | Plan, item and application history floor | **A** — additive | **A** on its own terms | none — drops protection only | +6 functions, +7 triggers | none |
| `dossier_upgrades` | `0003_upgrade_provenance_chain` | Re-proves the provenance chain at apply time | **A** — one constraint, additive | **A** on its own terms | none — drops protection only | +1 function, +1 trigger | none |
| `submission_packages` | `0001_initial` | Package, entry, frozen snapshot | **A** — three `CreateModel`, additive | **C** once any package data exists | **Total** for every frozen manifest and checksum, not derivable from the documents because it deliberately does not change when they do | none created | Restore from backup; never reverse |
| `submission_packages` | `0002_package_db_governance` | Freeze, entry and snapshot floor | **A** — additive | **A** on its own terms | none — drops protection only | +7 functions, +7 triggers | none |
| `submission_packages` | `0003_package_revision_family` | Persists revision-family identity; DB floor under revision numbers | **A, conditional on the data** — see below | **A** — reverse restores the exact prior state | none: `family_root` is derived from `source_package`, which this migration never touches | +1 function, +1 trigger; **replaces** `guard_update_package` from `0002` | **YES — run the duplicate check before deploying** |
| `external_integrations` | `0001_initial` | Connector, credential reference, execution, external object link | **A** — four `CreateModel`, additive | **C** once any execution history exists | **Total** for the only record that content left this deployment; the remote side is not queryable, and a document's history says where it came from, never where it was sent | none created | Restore from backup; never reverse |
| `external_integrations` | `0002_integration_db_governance` | Connector, credential, execution and link floor | **A** — additive | **A** on its own terms | none — drops protection only | +8 functions, +9 triggers | none |

### Reconciliation

The trigger and function columns sum to **40 functions and 45 triggers** added
by this release. Adding the pre-stack governed objects — `audit/0001` (1/2),
`regulatory_cases/0002` (2/6), `workflows/0003` (1/2) and `workflows/0005` (2/2)
— gives **46 functions and 57 triggers**, which is exactly what a migrated
database contains, on a fresh install and on one upgraded from Milestone 8.
`common/tests/test_governed_database_objects.py` asserts that catalogue by name
and attachment table.

**Since this release:** `formulations/0004_version_db_governance` (Option A,
formulation version approval, 2026-11-19) adds **3 functions and 4 triggers**:
class **A** forward (additive) and **A** in reverse (drops the protection only).
The catalogue is now **49 functions and 61 triggers**; the test above asserts
the new totals.

## The one migration with a required operator action

`submission_packages/0003_package_revision_family` builds
`unique_revision_per_package_family`. It **will refuse to build** if any existing
family already holds two packages with the same `revision_number` — possible
because the code it replaces keyed revisions on `tenant + case + name`, and a
package renamed between two clones could produce exactly that.

Run this before deploying Milestone 13:

```sql
SELECT COALESCE(family_root_id, id) AS family, tenant_id,
       revision_number, count(*)
  FROM submission_packages_submissionpackage
 GROUP BY 1, 2, 3 HAVING count(*) > 1;
```

Empty result means Class A: deploy. A non-empty result means the duplicates must
be resolved by hand first. Which package keeps which number is a decision, not
something a migration may guess.

## Why a data step here is still not Class C or D

`0003` contains an `UPDATE`, and the runbook's rule 1 flags `RunSQL` because a
data migration usually destroys information a restore has to bring back. This one
destroys none. `family_root_id` is *derived* from `source_package`, which the
migration never touches, so the reverse — set it back to `NULL`, then drop the
column — returns the table to precisely its prior state, and the forward step can
be recomputed at any time by running it again.

Checked by reading `BACKFILL_REVERSE_SQL`, not by trusting the comment above it.

## Findings

**`external_integrations/0001_initial` shipped without a classification.** It was
the only migration in the Milestone 9–15 stack with no
`MIGRATION CLASSIFICATION` block, while `ROADMAP.md` asserted its class in prose.
The runbook's §4 instruction is to classify every migration before deploying, and
an operator doing that at the file would have found nothing there. Milestone 16
added the block; the class it records — **C once execution history exists** —
matches what the roadmap already said, so this is a gap in the evidence rather
than a wrong answer.

**`ROADMAP.md` documented `submission_packages/0001` and `0002` but not `0003`.**
The classification was never wrong; it was absent, and with it the required
operator action above. This inventory is now where that action lives.

**The runbook's own migration survey is stale.** §4 describes "23 migrations
across 11 apps" with `RunSQL: 1`. The tree holds **44 across 17 apps**, with
**14** `RunSQL` migrations — every one of which has `reverse_sql` — and still
zero `RunPython`, `DeleteModel`, `RemoveField`, `RenameField` and `RenameModel`.
The numbers are corrected in the runbook. Its conclusion is unaffected: the point
it makes is that structural reversibility is not safety, and that remains true.

## What no migration in this release does

No `RunPython`. No `DeleteModel`, `RemoveField`, `RenameField` or `RenameModel`.
No migration reads or rewrites a row in a table it did not create, with the
single exception of `submission_packages/0003`, which derives one nullable column
in the table it is extending.
