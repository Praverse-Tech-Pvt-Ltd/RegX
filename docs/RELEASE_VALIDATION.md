# Release validation evidence — Milestone 16

What was actually run against the Milestone 9–15 platform, and what each run
proved. Every row here is a command that was executed, not a review opinion.

Findings and their disposition are in
[`RELEASE_BLOCKERS.md`](RELEASE_BLOCKERS.md). Migration classification is in
[`MIGRATION_INVENTORY.md`](MIGRATION_INVENTORY.md). The merge sequence is in
[`STACKED_MERGE_PLAN.md`](STACKED_MERGE_PLAN.md).

## Readiness summary

| Area | Evidence | Status | Risk | Fix required | Release blocking |
|---|---|---|---|---|---|
| Fresh database, zero to head | 59 migrations applied to an empty database, exit 0 | **PASS** | — | no | no |
| Forward upgrade with data | Milestone 8 database populated with M8-era code, then migrated through all 15 stack migrations | **PASS** | — | no | no |
| Migration classification | All 15 verified against migration code | **PASS** | one file carried no classification | fixed | no |
| Governed database objects | 57 triggers, 46 functions, asserted by name and table | **PASS** | — | no | no |
| Raw-SQL immutability | Terminal execution UPDATE refused, including after restore | **PASS** | — | no | no |
| Governed delete | Delete refused at the database for every governed history table | **PASS** | — | no | no |
| Tenant isolation | See matrix below | **PASS** | — | no | no |
| Existence oracle | See below | **PASS** | — | no | no |
| Permission composition | See below | **PASS** | — | no | no |
| API surface | 200 paths, no collisions, no internal id or secret exposed | **PASS** | — | no | no |
| State semantics | No overclaim in any module; guard extended to all nine | **PASS** | guard covered 3 of 8 | fixed | no |
| Part 11 / validation claims | 61 occurrences reviewed in context | **PASS** | — | no | no |
| Audit inventory | 85 event types; allow-listed in every release-scope module | **PASS** | 5 pre-stack modules unfiltered | recorded | no |
| Backup | Real `scripts/backup.sh` against a stack holding M9–M15 data | **PASS** | — | no | no |
| Restore | Real `scripts/restore.sh`; 23 post-restore checks | **PASS** | — | no | no |
| Document storage restore | File deleted before restore, recovered, bytes match the checksum the row asserts | **PASS** | — | no | no |
| Frozen package after restore | Manifest checksum identical; same cited version; export succeeds | **PASS** | — | no | no |
| External history after restore | Terminal execution still immutable | **PASS** | — | no | no |
| Task reliability doc | Reconciled against task code | **PASS** | two false statements | fixed | no |
| Health / readiness | Verified in containers through nginx | **PASS** | — | no | no |
| Environment contract | `check_env.py`, exit 1 missing / 0 present | **PASS** | — | no | no |
| Secret scan | Whole M9–M16 range | **PASS** | — | no | no |
| Docker fresh start | Clean project, fresh volumes, built from this branch | **PASS** | — | no | no |
| Rollback dry run | Class A reversed and re-applied, twice | **PASS** | — | no | no |
| Stack dependencies | Every tip matches its head; linear ancestry | **PASS** | — | no | no |
| CI | Cannot run | **BLOCKED** | organisation billing | not ours | see blockers |

## Fresh database and forward upgrade

Two independent databases, plus a third in containers.

```
fresh      empty -> 59 migrations                    57 triggers, 46 functions
upgrade    M8 code -> 44 migrations, populated,
           then M16 code -> +15 migrations           57 triggers, 46 functions
container  empty -> 59 migrations                    57 triggers, 46 functions
```

The governed floor is **identical** on a fresh install and on one upgraded from
Milestone 8. That parity is the result worth having: a trigger installed only on
new databases would be invisible to every behavioural test, because those run
against a freshly migrated database every time.

Data survival across the upgrade was checked by identity, not by row count
alone: case number, document and version public IDs, SHA-256 checksum, storage
key, workflow state and transition history all unchanged.

## Tenant isolation matrix

Tenant A must not see, modify, or infer the existence of tenant B's resources.
The mechanism differs by endpoint shape, and the matrix records which applies
rather than flattening them.

| Module | Read | Create | Update | Action | History | Export / link | Mechanism |
|---|---|---|---|---|---|---|---|
| `regulatory_cases` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 on addressable resources |
| `submission_dossiers` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `dossier_blueprints` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `dossier_upgrades` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `submission_operations` | ✓ | n/a | n/a | n/a | ✓ | n/a | **absence** — a read model returns rows, so isolation is that the row never appears |
| `submission_packages` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `external_integrations` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `workflows` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `documents` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **absence** in lists, 404 on detail |

Coverage counted from the suite: 461 cross-tenant assertions across 56 test
files. The two "absence" rows are the ones worth reading twice — a read model
cannot 404 for a row it simply did not select, so its isolation test has to
assert the row is *not present*, which is a weaker-looking assertion doing the
same job.

Public IDs are UUIDs and are never sequential, so a public ID from one tenant
carries no information about another's. Internal BIGINT primary keys are not
exposed anywhere in the API surface — re-verified against the generated OpenAPI
schema.

## Existence-oracle behaviour

The rule is that an unauthorised caller must not learn whether a resource
exists. The status code is not standardised across domains where established
semantics differ; what is asserted is that absent, cross-tenant and unauthorised
are **indistinguishable** to the caller.

| Resource | Absent | Cross-tenant | Unauthorised |
|---|---|---|---|
| case | 404 | 404 | 404 |
| dossier | 404 | 404 | 404 |
| blueprint | 404 | 404 | 404 |
| upgrade plan | 404 | 404 | 404 |
| package | 404 | 404 | 404 |
| connector | 404 | 404 | 404 |
| external execution | 404 | 404 | 404 |
| document evidence link | 404 | 404 | 404 |

The Milestone 8 lesson holds throughout: the target-module permission is checked
**before** the target is resolved, so a caller without permission cannot
distinguish "no such thing" from "not yours" by timing or by message.

## Permission composition

Cross-domain actions require every permission independently. No action launders
one permission into another.

| Action | Requires |
|---|---|
| Link document evidence to a workflow | workflow action **and** document view |
| Link a resource to a dossier section | dossier update **and** target-module view |
| Instantiate a blueprint into a dossier | blueprint view **and** dossier create **and** case view |
| Export a package | package export **and** document view |
| Run a connector import | connector execute **and** document create |
| Push a package through a connector | connector execute **and** package export **and** document view |

The composition that matters most is the last: it spans three modules, and a
caller holding only connector permission must not reach document content through
it.

## What was not validated

Listed in [`RELEASE_BLOCKERS.md`](RELEASE_BLOCKERS.md) under *Not validated*. No
CI run, no load testing, no penetration test, no production-scale restore, no
failover.
