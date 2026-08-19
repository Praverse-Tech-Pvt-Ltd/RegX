# RegX — Parallel Technical Readiness

**Discovery only. No code changed, no governance state touched.**

What engineering can legitimately do while Milestone 5A Item 1 waits on human
regulatory input.

Assessed against `regx-main` `a04a3639831a2b5f20c61902e5d127ed48a5aa09`.

---

## 0. Governance parking notice

> ### MILESTONE 5A PRODUCTION GOVERNANCE: **WAITING FOR HUMAN REGULATORY INPUT**

| | |
|---|---|
| Item 1 | **PENDING** — scope input recorded, closure awaiting named decision-maker, role, date and per-source metadata |
| Governance approvals | **0 of 20** |
| Production templates | **NOT FORMALLY APPROVED** |
| Production questions authored | **0** |
| Production questions approved | **0** |

Item 1 decisions are **not modified** by this pass. No approver, reviewer,
rationale, source interpretation, date or signature has been fabricated. The
governance work is parked on `regx/discovery/milestone-5a-production-content`
(4 commits, unmerged) and is untouched here.

**Nothing in this document is a route around the gate.** Every item below is
technical and independent of Item 1.

---

## 1. Current main health

| Check | Result |
|---|---|
| `origin/regx-main` | `a04a3639831a2b5f20c61902e5d127ed48a5aa09` — unchanged since PR #23 |
| Working tree | clean |
| **Backend CI** on `a04a363` | **success** |
| **Frontend CI** on `a04a363` | **success** |
| **Docker Integration** on `a04a363` | **success** |
| `manage.py check` | no issues |
| `makemigrations --check` | no changes detected |
| Migration graph | 38 migrations, consistent, no conflicts |
| Tracked-secret scan | **PASS** — no high-confidence patterns; no `.env`, key or credential file tracked |
| `db.sqlite3` sanitation | holds on main — 0 sessions, 0 usable password hashes |

Exact-main CI evidence is **current**; no re-run was needed.

---

## 2. Findings

Seven items, all discovered from the repository's own state rather than
invented. The codebase carries **no first-party TODO/FIXME debt** — a grep finds
six matches, all of them test fixture names containing the string "HACK".

### F-1 — The E2E harness silently tests the wrong server *(Critical)*

`playwright.config.ts` sets `reuseExistingServer: !process.env["CI"]`, and the
compose stack publishes the frontend container on the same port 3000. When the
integrated stack is running, Playwright **reuses the container** instead of
starting a dev server.

The container's bundle calls the API at `:8080`; every historical spec mocks
`:8000`. The mocks therefore never match, real calls return 403, and pages
redirect mid-test.

Measured this pass, same command, same commit:

| Condition | Result |
|---|---|
| Stack running (container on `:3000`) | **40 failed / 72 passed** |
| Container stopped (Playwright starts its own dev server) | **112 passed / 0 failed** |

This already produced one wrong conclusion earlier in the project — a report
stating "6 pre-existing failures" that were an artifact of exactly this. It is
documented in `INTEGRATION_E2E_EVIDENCE.md`, but as a *procedure to remember*
rather than something the harness prevents.

The failure mode that matters is not the 40 red tests, which are loud. It is
that a suite can appear to pass while exercising a different server than the
author intended.

### F-2 — `DEPLOYMENT_BOUNDARIES.md` documents a secret contract that does not exist *(Critical)*

The document lists three required secrets. Checked against the code and compose:

| Documented | Reality |
|---|---|
| `DJANGO_SECRET_KEY` | correct — hard-required by compose |
| `MFA_ENCRYPTION_KEY` | correct — hard-required by compose |
| `DATABASE_URL` | **never read anywhere.** `settings/base.py` reads `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` |
| *(missing)* | **`POSTGRES_PASSWORD`** — hard-required, `:?` guard |
| *(missing)* | **`COMPANY_SECRET_KEY`** — hard-required, `:?` guard |
| *(missing)* | `COMPANY_BASE_URL`, `COMPANY_SERVER_MODE`, `INTEGRATED_APP_URL` — optional with defaults, but meaningful |

Someone deploying from this document would fail at `docker compose build`, on
compose interpolation, before anything started — which is precisely how the
`COMPANY_SECRET_KEY` gap was discovered in CI during the site integration.

The production checklist is also silent on the CSP posture actually shipped
(`script-src 'self' 'unsafe-inline'`, with the reasoning recorded only in
`next.config.ts`).

### F-3 — No backup, restore or disaster-recovery documentation *(Major)*

Three stateful volumes exist and none has a documented procedure:

| Volume | Contents | Loss impact |
|---|---|---|
| `postgres_data` | all RegX operational data — executions, responses, snapshots, audit | total |
| `document_storage` | uploaded documents | total for the document platform |
| `company_db` | company site SQLite, seeded once from the committed file | recoverable by re-seeding |

No backup schedule, no restore procedure, no tested recovery path, no RPO/RTO
statement. For a system whose value proposition is a defensible audit trail,
an untested restore is a material gap.

### F-4 — `celery` and `frontend` have no healthcheck *(Major)*

Five of seven services define one; these two do not. Compose therefore cannot
report whether the Celery worker is actually consuming, only that its process
is up. The Docker Integration workflow compensates by grepping the log for
`ready.` and checking restart counts — a CI-only check that does not exist at
runtime.

### F-5 — No `LOGGING` configuration *(Major)*

`grep LOGGING backend/regx/settings/*.py` finds exactly one hit:
`LOGGING = {}` in `test.py`, to silence tests. Development and production use
Django's defaults. There is no structured logging, no correlation identifier, no
documented log destination, and no statement of what must never be logged —
which matters here because governed payloads carry regulated values and the
codebase is otherwise careful to expose UUIDs only.

### F-6 — No rollback procedure or release verification checklist *(Major)*

`DEPLOYMENT_BOUNDARIES.md` has a 7-line production checklist and nothing about
releasing or reverting. Migrations `0006` and `0007` are additive and
reversible, but that is a property of those two migrations, not a documented
procedure. There is no runbook, no smoke-test list for a fresh deployment, and
no defined rollback path.

### F-7 — `fda-iid.spec.ts` parallel flakiness *(Low)*

Previously observed: a varying subset failing on `toHaveURL` after form submit
under full-suite parallel load, passing 29/29 in isolation and at
`--workers=1`. **It did not reproduce in this pass** — three isolated runs and
two clean full-suite runs all passed. `INTEGRATION_E2E_EVIDENCE.md` already
recommends a ticket to add an explicit `waitForURL` or await the submit
response. Kept open at low priority; intermittent absence is not evidence of a
fix.

---

## 3. Work-item table

| # | Work item | Why needed | Existing source | Reg. dep | Sec. dep | Risk if not done | Priority | Ready now | Change surface | Next action |
|---|---|---|---|:-:|:-:|---|---|:-:|---|---|
| F-1 | Make the E2E harness fail loudly instead of testing the wrong server | Measured 40 false failures; risk of false passes | `INTEGRATION_E2E_EVIDENCE.md` | No | No | Wrong conclusions from test runs; has already happened once | **P1** | **DONE** | dedicated port 3100, `reuseExistingServer: false`, split configs, contract test | **Implemented** on `regx/feat/e2e-harness-correctness` |
| F-2 | Correct the deployment secret contract | Documented contract is wrong; deploy fails at build | `DEPLOYMENT_BOUNDARIES.md`, `compose.yaml`, `settings/base.py` | No | No | A first deployment fails on interpolation | **P1** | **YES** | 1 doc | Implement |
| F-3 | Backup / restore / DR documentation | 3 stateful volumes, no procedure | `compose.yaml` volumes | No | No | Unrecoverable data loss; audit trail is the product | **P1** | **YES** | 1 new doc (+ optional script) | Implement |
| F-4 | Healthchecks for `celery` and `frontend` | Runtime cannot detect a dead worker | `compose.yaml` | No | No | Silent worker failure; tasks queue unprocessed | **P2** | **DONE** | `compose.yaml` (2 blocks), CI wait logic, `SERVICE_HEALTH.md` | **Implemented** on `regx/feat/service-healthchecks` |
| F-5 | `LOGGING` configuration + what must never be logged | No structured logging; regulated values in payloads | `settings/*.py` | No | No | Undiagnosable production incidents; possible over-logging of regulated data | **P2** | **DONE** | JSON formatter, request-id middleware, `LOGGING`, 43 tests, `OPERATIONAL_LOGGING.md` | **Implemented** on `regx/feat/structured-operational-logging` |
| F-6 | Rollback procedure + release verification checklist | No documented release or revert path | `DEPLOYMENT_BOUNDARIES.md` | No | No | Unrehearsed recovery during an incident | **P2** | **DONE** | `RELEASE_ROLLBACK_RUNBOOK.md`, `scripts/release_verify.sh`, CI guards | **Implemented** on `regx/feat/release-rollback-runbook` |
| F-7 | `fda-iid` parallel flakiness | Intermittent false failures | `INTEGRATION_E2E_EVIDENCE.md` | No | No | Noise erodes trust in the suite | **P3** | **DONE** | 1 config line (`expect.timeout`), no spec changed; `FDA_IID_E2E_FLAKINESS_INVESTIGATION.md` | **Reproduced, root-caused and fixed** on `regx/investigate/fda-iid-flakiness` |
| S-1 | GitHub purge of PR #22 superseded objects | Old unsanitized DB blob still fetchable by SHA | prior security pass | No | **Yes** | Password hashes remain retrievable | **P1** | **NO** | none — external request | Owner raises with GitHub Support |
| S-2 | Rotate 3 OpenAI keys + SMTP password | Live credentials in the read-only company source | prior security pass | No | **Yes** | Credentials remain valid | **P1** | **NO** | none — provider-side | Owner rotates |
| G-1 | Items 1–20 governance decisions | The production content gate | `MILESTONE_5A_APPROVAL_REGISTER.md` | **Yes** | No | Milestone 5A cannot close | — | **NO** | — | Awaiting human input |

---

## 4. Classification

**DONE (7):** F-1, F-2, F-3, F-4, F-5, F-6, F-7

**READY NOW (0):** every finding from this pass is now implemented.

**BLOCKED BY REGULATORY INPUT:** all 20 register items; production question
authoring; template instantiation; anything that would advance `0/20`.

**BLOCKED BY SECURITY OWNER (2):** S-1 GitHub historical-object purge; S-2
credential rotation. Both **NOT CONFIRMED**, and neither is engineering-actionable.

**OPTIONAL / FUTURE:** Milestones 5B–5D are explicitly unscoped
(`ROADMAP.md`: *"not scoped … each needs its own discovery"*). No roadmap is
invented here.

---

## 5. Recommended order

**Top 3, all P1, all independent of Item 1:**

1. **F-1 — E2E harness correctness.** First because it protects the reliability
   of every other verification. While it stands, any suite run with the stack up
   reports results for a server the author did not intend, and the failure has
   already produced one incorrect report.

2. **F-2 — Deployment secret contract.** Smallest change with the highest
   embarrassment cost: a one-document fix to a contract that would fail a first
   deployment at build time. Verifiable in minutes against `compose.yaml` and
   `settings/base.py`.

3. **F-3 — Backup / restore / DR.** Largest genuine risk. Three stateful volumes
   and no tested recovery path, for a system whose value is a defensible audit
   trail.

**Recommended to start now: F-1.** It is self-contained, has a measured
before/after (40 failed → 112 passed), needs no regulatory input and no owner
action, and makes every subsequent verification trustworthy.

---

## 6. What this pass did not do

No governance state changed. Item 1 untouched. No approver, reviewer, rationale,
date or signature fabricated. No production content created, loaded, activated,
approved or inferred. No architecture changed. No new feature roadmap invented.
No code modified — this is discovery only.

**Governance approvals: 0 of 20. Production questions authored: 0.**
