# RegX — F-1 … F-7 Consolidated Readiness

**A status index, not a runbook.** Each control has a canonical document; this
page records what exists, what is merged, what is still owed, and by whom. It
deliberately does not restate the runbooks — follow the links.

Reviewed against `regx-main` `3db40b573ad24cd041b98008b680e5e79777b1a2`.

`REGX_PARALLEL_TECHNICAL_READINESS.md` is the *discovery* record that found
these seven items. This is the *closure* record.

---

## 1. Matrix

| | Gap found | Control implemented | PR | On `regx-main` |
|---|---|---|---|:-:|
| **F-1** | The E2E harness silently tested the Docker container instead of its own server | Dedicated port 3100, `reuseExistingServer: false`, pinned `baseURL`, split integrated config, 9-assertion contract test | #24 | **MERGED** |
| **F-2** | Documented secret contract did not exist — listed `DATABASE_URL`, omitted two hard-required secrets | Contract rebuilt from `compose.yaml` and settings; `check_env.py` enforces the real four | #25 | **MERGED** |
| **F-3** | Three stateful stores, no backup or restore procedure | `backup.sh` / `restore.sh`, SHA-256 manifest, destructive-action guards, tested restore | #26 | **MERGED** |
| **F-4** | `celery` and `frontend` had no healthcheck | Targeted Celery `inspect ping`; frontend HTTP probe; CI waits on health | #27 | **MERGED** |
| **F-5** | No `LOGGING` config at all; no correlation id; no never-log policy | JSON to stdout, allow-list formatter, `X-Request-ID`, 27 test functions / 44 cases | #28 | **MERGED** |
| **F-6** | No release procedure, no rollback, no migration-risk classification | Runbook, A/B/C/D classification, three rollback levels, read-only `release_verify.sh` | #29 | **MERGED** |
| **F-7** | `toHaveURL` flakiness under parallel load | Global `expect` timeout 15 s; no spec modified | #30 | **MERGED** |

**F-1 through F-7 are all merged into authoritative `regx-main`.** F-7 landed as
merge commit `3db40b573ad24cd041b98008b680e5e79777b1a2`. Verified rather than
assumed: the `expect: { timeout: 15_000 }` block is now **present** in
`frontend/playwright.config.ts` on main — the same check that previously
confirmed its absence.

---

## 2. Canonical documents

| Control | Document |
|---|---|
| F-1, F-7 | [`INTEGRATION_E2E_EVIDENCE.md`](INTEGRATION_E2E_EVIDENCE.md), [`FDA_IID_E2E_FLAKINESS_INVESTIGATION.md`](FDA_IID_E2E_FLAKINESS_INVESTIGATION.md) |
| F-2 | [`DEPLOYMENT_BOUNDARIES.md`](DEPLOYMENT_BOUNDARIES.md) |
| F-3 | [`BACKUP_RESTORE_DR.md`](BACKUP_RESTORE_DR.md) |
| F-4 | [`SERVICE_HEALTH.md`](SERVICE_HEALTH.md) |
| F-5 | [`OPERATIONAL_LOGGING.md`](OPERATIONAL_LOGGING.md) |
| F-6 | [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) |
| Pending decisions across F-3, F-5, F-6 and the security actions | [`REGX_OWNER_POLICY_DECISION_PACKAGE.md`](REGX_OWNER_POLICY_DECISION_PACKAGE.md) |
| Current integrated state across phases P0-P14 — validation, capabilities, blocked items and standing non-claims. **This page stays scoped to F-1…F-7** | [`P0_P14_HANDOFF.md`](P0_P14_HANDOFF.md) |

---

## 3. Verified on main by inspection

Not taken from the PR descriptions — re-checked against the files at
`3db40b5`. Every item below was re-run at that SHA rather than carried forward
from an earlier review:

- **F-1** — `baseURL: "http://localhost:3100"`, `reuseExistingServer: false`,
  `--port 3100`; integrated suite on its own config. No port-3000 reuse.
- **F-2** — `REQUIRED = [DJANGO_SECRET_KEY, POSTGRES_PASSWORD,
  MFA_ENCRYPTION_KEY, COMPANY_SECRET_KEY]`. **`DATABASE_URL` is read by zero
  settings files** — it was never the contract. Stub-scanner warning present.
- **F-3** — `src.backup(dst)` (SQLite online-backup API); **zero** plain
  `cp`/`docker cp` of a live database. Restore refuses on checksum mismatch,
  malformed manifest, missing `--project`, missing `--yes-destroy-data`, and a
  `*prod*|*live*` target.
- **F-4** — `celery -A regx inspect ping -d celery@$$(hostname)` and
  `wget -q -O /dev/null http://127.0.0.1:3000/signin`.
- **F-5** — 7-field allow-list, `ContextVar` (zero `threading.local`),
  `X-Request-ID`, **zero** `record.__dict__` serialisation, and the
  exception-echo limitation pinned by a named test.
- **F-7** — `expect: { timeout: 15_000 }` present in `playwright.config.ts`;
  `baseURL`, `reuseExistingServer` and the dedicated port unchanged, so the F-1
  contract survived the change.
- **F-6** — `release_verify.sh` contains no mutating operation in its code;
  `iig_checklist/0006` is **Class C — DATA RESTORE REQUIRED**, never a backward
  migration; new-code/old-schema **NOT SUPPORTED**, old-code/new-schema
  **NOT PROVEN**.

---

## 4. Cross-control interactions

These only make sense read together.

- **F-3 + F-6** — backup/restore *is* the Level-3 rollback route. `0006` being
  Class C is precisely why F-3 had to exist before F-6 could offer a rollback
  for it. Recording the backup-set ID is a pre-deploy gate item, not an
  afterthought.
- **F-4 + F-6** — **health is necessary but not sufficient.** Demonstrated
  twice: a half-reversed schema showed 7/7 healthy and 5/5 origin routes at 200
  while the application was broken; a recreated upstream showed 7/7 healthy with
  routes at 404. Release acceptance therefore requires migration-state
  verification *and* origin routing, not health alone.
- **F-5 + F-6** — operational logs support diagnosis; they are **not** release
  approval and **not** the audit trail. `AuditEvent` remains authoritative for
  regulated actions and does not depend on a log being written.
- **F-1 + F-7** — F-7 changes only a timeout budget. Deterministic Playwright
  server ownership is untouched, and the F-1 contract test still passes. F-1
  also proved itself during the F-7 investigation by refusing to attach to an
  orphaned dev server rather than testing against it silently.
- **F-3 / F-4 / F-6** — the nginx stale-upstream behaviour is documented
  identically in all three, including that it is **not** dynamic DNS
  re-resolution. No contradiction: the 404 and 502 symptoms differ only by
  whether the stale address was reused.

**No contradictions were found between the seven documents.**

---

## 5. Readiness layers

| Layer | Status | Why |
|---|---|---|
| **1 — Engineering** | **READY** | All seven findings implemented, evidenced and **merged to `regx-main`**. No engineering work is blocked. |
| **2 — Operations** | **PARTIAL** | Every technical capability exists and has been exercised. Every *policy* input is unanswered — §6. |
| **3 — Security owner** | **BLOCKED** | Both actions are external and **NOT CONFIRMED** — §7. Neither is engineering-actionable. |
| **4 — Regulatory governance** | **BLOCKED** | 0 of 20. Item 1 **PENDING** — §8. |

These are independent. Layer 1 being ready does not advance any other layer, and
no amount of engineering will.

### Engineering blockers

**Critical: 0 · Major: 0 · Minor: 0 · Engineering blockers: NONE.**

The pending items in §6, §7 and §8 are **policy, owner and governance
decisions**. None of them is a technical defect, and none is counted above.

---

## 6. Operations — pending policy

Technical capability exists for all of these. The decisions do not.

| Decision | Status | Owner |
|---|---|---|
| RPO | **PENDING** | Business / IT |
| RTO | **PENDING** | Business / IT |
| Backup retention | **PENDING** | Business / QA / IT |
| Backup scheduling | **PENDING** — script is manual, no scheduler | IT |
| Off-site / immutable storage | **PENDING** — local path only | IT |
| Backup encryption at rest | **PENDING** — not applied | IT / Security |
| Log aggregation | **PENDING** | IT / Operations |
| Operational-log retention | **PENDING** | QA / IT / Security |
| Release approver | **PENDING** | Business |
| Deployment authority | **PENDING** | Business / IT |
| Maintenance window | **PENDING** | Business / IT |
| Downtime SLA | **PENDING** | Business |
| Business acceptance authority | **PENDING** | Business |

**No centralised SIEM or log platform is configured**, and none is assumed.
Operational-log retention is a separate question from regulated audit-record
retention, which concerns `AuditEvent` rows and their backups.

Each of these thirteen is written up decision-ready — what must be decided, why
it matters, what the system can already do, the realistic options and the
trade-offs — in
[`REGX_OWNER_POLICY_DECISION_PACKAGE.md`](REGX_OWNER_POLICY_DECISION_PACKAGE.md).
**That package decides nothing**; publishing it did not change any status here.

---

## 7. Security owner actions — carried forward

| | Action | Status |
|---|---|---|
| **S-1** | GitHub Support purge of the superseded unsanitised company DB blob still fetchable by SHA after the PR #22 force-push | **NOT CONFIRMED** |
| **S-2** | Provider-side revocation of three historical OpenAI project keys and change of the historical SMTP password, all originating in the read-only company source | **NOT CONFIRMED** |

Neither is engineering-actionable, and no value is reproduced anywhere in this
repository. Removal from this repository did **not** invalidate them: they
remain in the company's own untouched source.

Required owner action and the evidence needed to close each are set out in
[`REGX_OWNER_POLICY_DECISION_PACKAGE.md`](REGX_OWNER_POLICY_DECISION_PACKAGE.md)
§D. Both remain **NOT CONFIRMED**.

---

## 8. Regulatory governance

| | |
|---|---|
| Governance approvals | **0 of 20** |
| Production questions authored | **0** |
| Production questions approved | **0** |
| Item 1 | **PENDING** |
| Production content gate | **OPEN — BLOCKED ON REGULATORY APPROVAL** |

The register's rule stands and is unchanged:

> No production regulatory checklist content may be authored, loaded or
> activated until item 20 is signed. **This count changes only when a named
> regulatory authority supplies a real approval.** It is not advanced by
> document completeness, engineering readiness or milestone progress.

**Item 1 requires corrected human regulatory input.** The register records the
dosage forms as **CANDIDATES ONLY — NOT APPROVED — ENGINEERING SELECTED
NOTHING**. No scope mapping is treated as approved, and any earlier
dosage-form scope mapping is **superseded and must not be reused**. Verified: no
`INCLUDE`/`DEFER` scope mapping for those candidates exists anywhere on
`regx-main`.

Engineering readiness reaching READY is **not** a reason to begin pilot
production content.

---

## 9. What is and is not claimed

**Implemented and tested technical capability**, in every case.

Explicitly **not** claimed anywhere: 21 CFR Part 11 compliance · validated
production disaster recovery · a validated production release process ·
regulatory approval · FDA approval · GxP validation.

A repository-wide scan found no such claim. The only `FDA APPROVED` strings on
main are members of a **forbidden-word list** that the decision engine uses to
structurally prevent constructing such a status.

Standing limitations, each stated in its own document: no atomic cross-volume
snapshot (F-3, artifacts are captured sequentially); health is per-container and
not end-to-end (F-4); redaction is best-effort and an exception message can echo
its input (F-5); no zero-downtime claim and the running system does not report
its own commit (F-6); a timeout ceiling is a margin, not a guarantee (F-7).

---

## 10. Next actions

1. **Layer 1 — complete.** All seven findings are merged. Nothing further is
   owed by engineering in this workstream.
2. **Layer 2** — the thirteen decisions in §6, each written up decision-ready in
   `REGX_OWNER_POLICY_DECISION_PACKAGE.md`. Engineering can state the
   consequence of each; it cannot make them.
3. **Layer 3** — S-1 and S-2 remain with the owner; see that package §D for the
   closure evidence each needs.
4. **Layer 4** — Item 1 awaits corrected human regulatory input. Nothing
   downstream can start until it lands.
