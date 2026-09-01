# Release blockers

State at the Milestone 16 head. **The four sections are kept apart on purpose:**
an engineering defect, a policy decision the owner has not made, and an
infrastructure condition nobody here controls are three different reasons a
release cannot proceed, and merging them into one list makes all three
unactionable.

Nothing in this document resolves anything. Milestone 16 may record these; it
may not decide them.

---

## BLOCKING

**None found by Milestone 16.**

Every defect this milestone found was an inaccuracy in documentation or a gap in
test coverage. None changed a runtime behaviour, and all are fixed on this
branch — see NON-BLOCKING below for what they were.

That is a statement about what was validated, not a claim that the platform is
defect-free. What was actually exercised: a zero-to-head migration on a fresh
database, a populated Milestone 8 database migrated forward through the whole
chain, a full backup and restore with file recovery and checksum verification, a
Class A rollback dry run in both directions, and the complete gate set. What was
not exercised is listed under *Not validated* at the end.

---

## NON-BLOCKING

Found and fixed on this branch.

| # | Finding | Where | Fix |
|---|---|---|---|
| 1 | `TASK_RELIABILITY.md` gave `process_document_version` a **30s** retry backoff; the task declares `default_retry_delay=60` and both retry sites pass no `countdown` | `docs/TASK_RELIABILITY.md` | corrected to 60s |
| 2 | The same document claimed **"all four dispatch sites use `transaction.on_commit`"**. Three do; `documents/tasks.py` dispatches inline on purpose, a Milestone 15 decision that was made and then not written down | `docs/TASK_RELIABILITY.md` | section rewritten to describe three deferred and one deliberate inline, with the reasoning |
| 3 | `external_integrations/0001_initial` was the **only migration in the M9–M15 stack with no classification block**, while `ROADMAP.md` asserted its class in prose. An operator following the runbook's "classify every migration before deploying" would have found nothing at the file | `backend/external_integrations/migrations/0001_initial.py` | classification added: **C once execution history exists** |
| 4 | `ROADMAP.md` classified `submission_packages/0001` and `0002` but not `0003` — and with it lost the **required pre-deploy operator action** | `docs/ROADMAP.md` | recorded in `MIGRATION_INVENTORY.md`, where the query now lives |
| 5 | The runbook's migration survey described **23 migrations across 11 apps** with `RunSQL: 1`. The tree holds **44 across 17**, with 14 `RunSQL` — every one reversible | `docs/RELEASE_ROLLBACK_RUNBOOK.md` §4 | survey re-run and corrected; its conclusions were unaffected |
| 6 | The regulatory-overclaim guard existed for three modules and **not** for `submission_dossiers`, `dossier_blueprints`, `dossier_upgrades`, `regulatory_cases` or `workflows`. All five were clean — this was a coverage gap, not an overclaim | `backend/common/tests/test_regulatory_claim_guard.py` | one cross-module guard covering all nine governed modules, plus a test that fails when a new governed app is added and not covered |

### Recorded, deliberately not changed

**Five pre-stack modules do not allow-list their audit payloads** —
`documents`, `fda_data`, `formulations`, `iid_assessment`,
`templates_registry`. Every module in the M9–M15 release scope does.

This was checked rather than assumed: the connector import path reaches
`documents` audit events, so it was the one that mattered. Its payloads carry
only internally-derived public IDs and integers — no filename, no declared MIME
type, no remote response text. No remote input reaches an unfiltered payload.

Retrofitting allow-lists onto five modules outside the release scope is a change
Milestone 16 is not chartered to make, and making it would mean shipping an
untested refactor in a validation milestone.

**`DOCUMENT_SCANNER_BACKEND` defaults to `stub`.** Uploads are not scanned. This
is a deployment prerequisite rather than a defect — `check_env.py` already
reports it — but it must be set to a real scanner before any deployment accepts
uploads it did not create.

---

## DEFERRED OWNER / POLICY

Unchanged by this milestone. Recorded as external release constraints.

| Item | State |
|---|---|
| Production regulatory content approvals | **0 of 20 approved** |
| Item 1 | **unresolved** |
| Owner-policy decision package | **deferred**, decisions not taken |
| Part 11 / validated-system claim status | **not claimed anywhere**, and Milestone 16 re-verified that: 61 occurrences of the relevant phrases scanned, all disclaimers, negative test assertions, or an unrelated spec section numbered "Part 11" |
| **S-1** — GitHub Support purge of the superseded unsanitised company DB blob still fetchable by SHA after the PR #22 force-push | **NOT CONFIRMED** |
| **S-2** — Provider-side revocation of three historical OpenAI project keys and change of the historical SMTP password, all originating in the read-only company source | **NOT CONFIRMED** |

Milestone 16 ran a secret scan across the whole M9–M16 range. Every match was a
self-labelled synthetic fixture; no new credential was committed, so **S-1 and
S-2 are untouched by this release** and remain exactly as the owner left them.

---

## INFRASTRUCTURE

Conditions of the environment, not of the code.

| Condition | Effect | Status |
|---|---|---|
| **GitHub Actions blocked at organisation level by a billing / spending limit** | No CI run can be allocated for any PR in the stack. Every gate in this release was therefore run locally and its exact output recorded | `CI INFRASTRUCTURE BLOCK: GITHUB ORGANIZATION BILLING`. No workflow file was modified to work around it |
| **`gh` CLI unauthenticated on this host** | PRs cannot be opened from here even though `git push` succeeds — the two use different credential stores | Reported, not worked around. Extracting the git credential to authenticate `gh` was deliberately not done |
| **Two PostgreSQL servers on the validation host** | A native `postgresql-x64-16` service owns `localhost:5432` while the compose project publishes the same port, so host-side `psql` and `docker compose exec postgres psql` reach **different databases** | A property of this host, not of RegX. The backup and restore scripts and every document route through `compose exec` and are unaffected; verified that no doc instructs host-side `psql` |

---

## Not validated

Stated so that the absence is not read as a pass.

* **No CI run.** Every result in this release is a local run. The organisation
  billing condition above is why.
* **No load or soak testing.** Capacity limits are structural bounds, tested at
  the sizes recorded in `CAPACITY_AND_LIMITS.md`, not throughput measurements.
* **No penetration test.** Tenant isolation, existence-oracle behaviour and
  permission composition are covered by tests, which is not the same as an
  adversarial assessment.
* **No production-scale restore.** The backup and restore rehearsal used
  synthetic data in a disposable compose project, torn down with `down -v`.
* **No multi-node or failover behaviour.** Single-host compose only.
