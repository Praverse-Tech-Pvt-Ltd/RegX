# RegX — Owner and Policy Decision Package

**This document decides nothing.** It states, for each open non-engineering
item, what has to be decided, why it matters, what the system can already do,
and what the realistic options are — so that a decision can be made quickly by
the people entitled to make it.

Prepared against `regx-main` `c79cf0717b53c454ab645750587a7609549ecb3c`.

**Engineering has not selected any option, proposed any value, or nominated any
person.** Where a role is suggested it is a role category only.

---

## How to use this

Each entry is self-contained. To close one, record the choice, the deciding
role and the date **in your own governance record** — not here. This page is the
question, not the answer.

Technical detail lives in the canonical runbooks and is not repeated: see
[`BACKUP_RESTORE_DR.md`](BACKUP_RESTORE_DR.md),
[`OPERATIONAL_LOGGING.md`](OPERATIONAL_LOGGING.md),
[`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md). Status across all
seven findings is in
[`REGX_F1_F7_CONSOLIDATED_READINESS.md`](REGX_F1_F7_CONSOLIDATED_READINESS.md).

**Nothing here is a regulatory decision.** Production regulatory content remains
governed by Milestone 5A and is untouched by any choice on this page.

---

# A. F-3 — Backup and disaster-recovery policy

## 1. RPO — recovery point objective

| | |
|---|---|
| **Decision required** | How much recently-written data the business accepts losing in a disaster. |
| **Why it matters** | RPO is the gap between the last good backup and the failure. It sets backup frequency; everything else in this section follows from it. |
| **Current capability** | `scripts/backup.sh` produces a verified, restorable set on demand. **No schedule exists**, so today the effective RPO is "since whenever someone last ran it" — which is not a policy, it is the absence of one. |
| **Options** | Near-real-time / very low loss tolerance · hourly · several hours · daily. |
| **Trade-offs** | A tighter RPO normally increases operational complexity and storage cost: more runs, more sets retained, more I/O against a live system, and continuous methods beyond the current scripted approach. A looser RPO is cheaper and simpler and loses more work. |
| **Owner role** | Business, with IT |
| **Reference** | `BACKUP_RESTORE_DR.md` §7 |
| **Status** | **PENDING** |

**No RPO value is proposed, and the current tooling is not claimed to achieve
any particular one.** Meeting a chosen RPO requires the scheduling decision (4)
to be made and implemented.

## 2. RTO — recovery time objective

| | |
|---|---|
| **Decision required** | How long the business accepts being down while the system is restored. |
| **Why it matters** | RTO drives whether restore stays a manual runbook or needs standby infrastructure, and it sets the expectation an operator is working against during an incident. |
| **Current capability** | Restore has been **technically rehearsed end to end** on disposable synthetic data — database, document storage, company database, integrated routing and document-checksum integrity all verified. |
| **Options** | Under 1 hour · several hours · same business day · next business day. |
| **Trade-offs** | Restore duration scales with `document_storage` size, plus the time to obtain deployment secrets through the secret-management process. A short RTO may require pre-staged infrastructure rather than a manual restore. |
| **Owner role** | Business, with IT |
| **Reference** | `BACKUP_RESTORE_DR.md` §7, `RELEASE_ROLLBACK_RUNBOOK.md` §10 |
| **Status** | **PENDING** |

**A rehearsed restore is not an approved RTO.** The mechanics work; no target
has been set, and none is proposed here.

## 3. Backup retention

| | |
|---|---|
| **Decision required** | How long backup sets are kept, and how many. |
| **Why it matters** | Retention determines how far back a recovery can reach, and it is the main cost driver — a full set is the database dump plus the evidence tree, considerably larger with company media. |
| **Current capability** | Each run writes its own timestamped directory, so rotation is possible. **No retention period is applied and nothing is deleted automatically.** |
| **Options** | Short operational retention (recent sets only) · monthly or quarterly historical points · longer business or regulated retention. These can be combined in tiers. |
| **Trade-offs** | Longer retention costs storage and widens the window in which a set could be mishandled; shorter retention limits how far back you can recover. |
| **Owner role** | Business, with QA and IT |
| **Reference** | `BACKUP_RESTORE_DR.md` §7 |
| **Status** | **PENDING** |

> **Backup retention is not regulated audit-record retention.** They are
> different questions about different data. The regulated audit trail is
> `AuditEvent` rows in the database; how long those must be kept is a
> QA/regulatory determination that this decision neither sets nor satisfies.
> **No GMP or regulatory retention duration is proposed here.**

## 4. Backup scheduling

| | |
|---|---|
| **Decision required** | Whether backups run automatically, and how often. |
| **Why it matters** | An unscheduled backup is one someone has to remember. The chosen RPO (1) is unreachable without a matching schedule. |
| **Current capability** | The scripts provide the **capability**; there is **no production scheduler** — no cron entry, no timer, no orchestrated job. Verified: nothing in `scripts/`, `compose.yaml` or CI schedules a backup. |
| **Options** | Manual only · scheduled daily · scheduled more frequently · event-triggered before a risky release · a combination. |
| **Trade-offs** | Automation removes human error and adds a component to operate and monitor. Event-triggered runs protect releases specifically but leave ordinary days uncovered. |
| **Owner role** | IT / Operations |
| **Reference** | `BACKUP_RESTORE_DR.md` §7, `RELEASE_ROLLBACK_RUNBOOK.md` §3 |
| **Status** | **PENDING** |

Note the release runbook already requires a backup **before** a risky
deployment, so an event-triggered run is a procedural expectation today even
though no scheduler enforces it.

## 5. Off-site backup storage

| | |
|---|---|
| **Decision required** | Where backup sets are stored, and whether a copy leaves the host. |
| **Why it matters** | A backup on the same host as the system it protects does not survive the loss of that host. |
| **Current capability** | Sets are written to a **local path only** (`./backups` by default). No replication, no remote copy, no immutability. |
| **Options** | Same-host only · a secondary site · cloud or object storage · an offline or air-gapped copy where the risk profile justifies it. |
| **Trade-offs** | Moving copies off-host protects against site loss and introduces transfer, access-control and confidentiality obligations for data in motion and at rest. Immutable or air-gapped copies resist tampering and ransomware at the cost of convenience. |
| **Owner role** | IT / Operations, with Security |
| **Reference** | `BACKUP_RESTORE_DR.md` §7 |
| **Status** | **PENDING** |

**No vendor or product is named**, and none is implied.

## 6. Backup encryption

| | |
|---|---|
| **Decision required** | Whether backup artifacts are encrypted, and at which points. |
| **Why it matters** | A backup set contains the full application database and every uploaded evidence file. Its confidentiality requirement is the same as production's, wherever the set happens to sit. |
| **Current capability** | **Backup artifacts are not encrypted.** Verified against `scripts/backup.sh` — no encryption step of any kind. Deployment secrets are never captured in a set (`"secrets": "none"` in the manifest), which is a separate protection and not a substitute. |
| **Options** | Three distinct questions, decidable separately: **at rest** (artifacts encrypted where they are stored) · **in transit** (protection while a set is copied off-host — only relevant once (5) is decided) · **exported artifacts** (a set handed to a third party or moved between environments). |
| **Trade-offs** | Encryption introduces key management, and a lost key makes a set unrecoverable — the same failure mode already documented for `MFA_ENCRYPTION_KEY`. Encrypting nothing keeps recovery simple and leaves the data readable to anyone who reaches the file. |
| **Owner role** | Security, with IT |
| **Reference** | `BACKUP_RESTORE_DR.md` §7 |
| **Status** | **PENDING** |

---

# B. F-5 — Operational logging policy

## 7. Log aggregation

| | |
|---|---|
| **Decision required** | Whether operational logs are collected anywhere beyond the container's stdout. |
| **Why it matters** | Logs that live only in a container are lost when it is replaced, and cannot be searched across services during an incident. Request correlation exists (`X-Request-ID`) but only pays off if the records are somewhere searchable. |
| **Current capability** | Structured JSON, one event per line, to **stdout/stderr**. **No aggregation, no collector, no SIEM is configured**, and none is assumed. Whatever the container runtime retains is all there is. |
| **Options** | Local stdout only (status quo) · a centralized log collector · SIEM integration where security monitoring is required. |
| **Trade-offs** | Aggregation makes incidents diagnosable across services and creates a second location holding operational data, which then needs its own access control and retention. SIEM adds security detection and cost. |
| **Owner role** | IT / Operations |
| **Reference** | `OPERATIONAL_LOGGING.md` §10 |
| **Status** | **PENDING** |

**No vendor or product is named.**

## 8. Operational-log retention

| | |
|---|---|
| **Decision required** | How long operational logs are kept, who may read them, and how they are deleted. |
| **Why it matters** | Too short and an incident cannot be reconstructed; too long and diagnostic data accumulates indefinitely somewhere with weaker controls than the database. |
| **Current capability** | Docker retains only the last portion of container output. There is **no defined retention, no defined access control and no deletion lifecycle** for logs. |
| **Options** | Three parts to settle: **diagnostic retention** (how long) · **access controls** (which roles may read) · **deletion lifecycle** (how expiry is enforced and evidenced). |
| **Trade-offs** | Longer retention aids investigation and enlarges the surface holding operational data. Strict access control protects it and slows incident response if too narrow. |
| **Owner role** | QA, IT and Security jointly |
| **Reference** | `OPERATIONAL_LOGGING.md` §10 |
| **Status** | **PENDING** |

> **Operational logs are not the regulated audit trail.** `AuditEvent` rows are
> the authoritative record for regulated actions, they do not depend on logging,
> and their retention is a separate question this decision does not touch.
> Deleting operational logs under this policy does not affect the audit trail.

---

# C. F-6 — Release and deployment policy

Throughout this section, **technical execution** and **authorization** are
deliberately separated. `scripts/release_verify.sh` answers whether a deployment
is technically healthy. It does not decide whether the release may happen, or
whether the business accepts the result.

## 9. Release approver

| | |
|---|---|
| **Decision required** | Which role **authorizes a release to production**. |
| **Why it matters** | Without a named authorizing role, either nobody approves releases or whoever is at the keyboard effectively does. |
| **Current capability** | The pre-deploy gate produces objective inputs — CI state at the exact commit, environment pre-flight, migration classification, current health, chosen rollback target. It produces no authorization. |
| **Options** | Engineering · Business / Product · QA · a defined combination. |
| **Trade-offs** | A single approver is fast and concentrates responsibility; multiple approvers add assurance and latency. |
| **Owner role** | Business, with QA |
| **Reference** | `RELEASE_ROLLBACK_RUNBOOK.md` §3, §12 |
| **Status** | **PENDING** |

**CI green is not authorization.** It reports that the code builds and the tests
pass.

## 10. Deployment authority

| | |
|---|---|
| **Decision required** | Which role is **permitted to execute** a deployment. |
| **Why it matters** | Execution requires production access and the deployment secrets; who holds that is an access-control decision as much as a process one. |
| **Current capability** | Deployment is entirely manual and operator-driven. Nothing enforces who may run it. |
| **Options** | Engineering · IT / Operations · a defined on-call role. |
| **Trade-offs** | Restricting execution to a small group improves control and can slow response; widening it does the reverse. |
| **Owner role** | IT / Operations, with Business |
| **Reference** | `RELEASE_ROLLBACK_RUNBOOK.md` §6, §12 |
| **Status** | **PENDING** |

### The distinction between 9 and 10

**Release approver** authorizes that a release *should* go to production.
**Deployment authority** is the role permitted to *carry it out*.

**These may be the same role or different roles** — that is a company policy
choice. **Segregation is not assumed to be mandatory here**, and engineering
takes no position on whether it should be. If a governance framework the company
is subject to requires separation of duties, that requirement governs; nothing
in RegX imposes it.

## 11. Maintenance window

| | |
|---|---|
| **Decision required** | Whether deployments happen inside a defined window, and when. |
| **Why it matters** | Deployment is **not zero-downtime** here — see below — so there is a real interruption to place somewhere. |
| **Current capability** | Single instance per service, no rolling deploy. New code on an old schema is **NOT SUPPORTED** (observed, not inferred) and old code on a new schema is **NOT PROVEN**, so the runbook sequences deliberately and accepts a controlled interruption. |
| **Options** | No defined window · a recurring low-traffic window · scheduled per release · emergency exception path. |
| **Trade-offs** | A fixed window contains user impact and delays fixes; deploying at will is responsive and exposes users to the interruption. |
| **Owner role** | Business, with IT |
| **Reference** | `RELEASE_ROLLBACK_RUNBOOK.md` §5, §6, §12 |
| **Status** | **PENDING** |

## 12. Downtime SLA

| | |
|---|---|
| **Decision required** | What availability, if any, is committed to users. |
| **Why it matters** | An SLA constrains RTO (2), maintenance windows (11) and the infrastructure needed to honour them. |
| **Current capability** | **No availability commitment exists** and none is implied by any control delivered so far. Healthchecks are local per-container signals — they are not monitoring, not alerting and not SLA measurement, and nothing currently measures availability. |
| **Options** | No formal SLA · an internal target · a contractual commitment. |
| **Trade-offs** | A committed SLA requires measurement, alerting and probably redundancy — none of which exists today. |
| **Owner role** | Business |
| **Reference** | `SERVICE_HEALTH.md` §9, `RELEASE_ROLLBACK_RUNBOOK.md` §12 |
| **Status** | **PENDING** |

## 13. Business acceptance authority

| | |
|---|---|
| **Decision required** | Which role confirms the deployed system is **acceptable for business use** once technical checks pass. |
| **Why it matters** | Technical checks confirm the system is running as built. They cannot confirm it does what the business needs, and treating them as if they could is how a technically perfect deployment of the wrong thing gets accepted. |
| **Current capability** | `release_verify.sh` reports technical pass/fail and prints, verbatim, "technical checks only, not business acceptance". |
| **Options** | Business / Product · QA · a defined joint sign-off. |
| **Trade-offs** | A formal acceptance step adds assurance and time; no acceptance step means technical success is silently treated as business success. |
| **Owner role** | Business / Product, with QA |
| **Reference** | `RELEASE_ROLLBACK_RUNBOOK.md` §7, §12 |
| **Status** | **PENDING** |

> **A passing smoke test is not business approval.** 42 of 42 technical checks
> green means the stack is healthy and behaving as built. It is not a statement
> that the release is fit for business use, and it must not be recorded as one.

---

# D. Security owner actions

Neither is engineering-actionable. Both concern material originating in the
company's read-only source, which remains untouched.

## S-1 — GitHub historical object purge

| | |
|---|---|
| **Status** | **NOT CONFIRMED** |
| **Background** | A superseded, unsanitised company database blob remained fetchable by object SHA after the PR #22 force-push. Removal from the branch did not remove the object from GitHub's storage. |
| **Required owner action** | Confirm that GitHub Support has completed a **permanent purge** of the historical unsanitised database/blob object. |
| **Evidence required for closure** | A GitHub Support ticket reference or written confirmation, or equivalent confirmation from an authorized repository owner. Record the reference — not the object contents. |
| **Owner role** | Repository owner / Security |
| **Reference** | `DEPLOYMENT_BOUNDARIES.md` §6, `BACKUP_RESTORE_DR.md` §6 |

**This is not claimed to be done.** Until confirmation exists, assume the object
is still retrievable by SHA.

## S-2 — Credential rotation and revocation

| | |
|---|---|
| **Status** | **NOT CONFIRMED** |
| **Scope** | Three OpenAI project keys and one SMTP password, all originating in the copied company source. |
| **Required owner action** | Rotate or revoke the exposed credentials **at the providers**. |
| **Evidence required for closure** | Provider-side confirmation: a revocation record for the old credentials and issuance of replacements. **Record the fact and the date, never the values.** |
| **Owner role** | Security, with the credential owners |
| **Reference** | `DEPLOYMENT_BOUNDARIES.md` §6, `BACKUP_RESTORE_DR.md` §6 |

**No credential value is reproduced anywhere in this repository**, and none
appears in this document. Removal from this repository did **not** invalidate
them — they remain in the company's own untouched source, and they stay valid
until rotated at the provider.

---

# E. Owner matrix

| ID | Decision / action | Category | Suggested owner role | Status | Eng. dependency? | Evidence needed to close |
|---|---|---|---|---|:-:|---|
| **1** | RPO | F-3 backup/DR | Business + IT | PENDING | NO | Recorded target, with deciding role and date |
| **2** | RTO | F-3 backup/DR | Business + IT | PENDING | NO | Recorded target, with deciding role and date |
| **3** | Backup retention | F-3 backup/DR | Business + QA + IT | PENDING | NO | Recorded period and set count |
| **4** | Backup scheduling | F-3 backup/DR | IT / Operations | PENDING | NO¹ | Recorded cadence |
| **5** | Off-site storage | F-3 backup/DR | IT / Ops + Security | PENDING | NO¹ | Recorded destination and access model |
| **6** | Backup encryption | F-3 backup/DR | Security + IT | PENDING | NO¹ | Recorded scope (rest / transit / export) and key-custody model |
| **7** | Log aggregation | F-5 logging | IT / Operations | PENDING | NO¹ | Recorded destination, or an explicit decision to stay local |
| **8** | Operational-log retention | F-5 logging | QA + IT + Security | PENDING | NO¹ | Recorded period, access controls, deletion lifecycle |
| **9** | Release approver | F-6 release | Business + QA | PENDING | NO | Recorded role |
| **10** | Deployment authority | F-6 release | IT / Ops + Business | PENDING | NO | Recorded role and access model |
| **11** | Maintenance window | F-6 release | Business + IT | PENDING | NO | Recorded window, or explicit "none" |
| **12** | Downtime SLA | F-6 release | Business | PENDING | NO² | Recorded commitment, or explicit "no formal SLA" |
| **13** | Business acceptance authority | F-6 release | Business / Product + QA | PENDING | NO | Recorded role |
| **S-1** | GitHub historical object purge | Security owner action | Repo owner / Security | **NOT CONFIRMED** | NO | Support ticket reference or owner confirmation |
| **S-2** | Credential rotation / revocation | Security owner action | Security | **NOT CONFIRMED** | NO | Provider-side revocation and reissue record, values excluded |

¹ **The decision has no engineering dependency.** Implementation work follows
some choices — a scheduler (4), a copy mechanism (5), an encryption step (6), a
collector (7), a retention mechanism (8) — but that work is small, well
understood and blocked only by the decision itself, not the reverse.

² **No engineering dependency to decide**, but honouring a committed SLA would
require measurement, alerting and probably redundancy, none of which exists.

---

# F. Priority

Priority here is **urgency of action**, not defect severity. None of these is a
software defect, and none is an engineering blocker.

| Priority | Items | Basis |
|---|---|---|
| **P1 — owner action** | **S-1, S-2** | Exposure is **ongoing and time-dependent**. The credentials stay valid until rotated and the historical object stays retrievable until purged, so every day of delay is additional exposure. Neither depends on any other item, and neither needs engineering. |
| **P2 — policy decision** | **1–13** | These do not create new exposure. They gate **production operational authorization** — without them there is no approved recovery objective, no retention, no release authority. Item 4 (scheduling) and item 1 (RPO) are coupled: an RPO without a schedule is aspirational. |
| **P3 — governance follow-up** | Milestone 5A, Item 1 | Tracked separately and **not part of this package**. |

**P3 does not mean least important.** Item 1 is the root gate for all production
regulatory content — nothing downstream can begin until it lands. It is ranked
separately because it belongs to a different track with different decision
makers, not because it can wait.

The security items outrank the policy decisions on urgency because their cost
grows with time, while an undecided policy has a fixed cost that is paid when
production authorization is sought.

---

# G. Explicit non-decisions

For the avoidance of doubt, this document does **not**:

- select any RPO, RTO, retention period, schedule, storage location, encryption
  scheme, aggregation target, window or SLA value;
- nominate any person, or record any name, signature, approval or date;
- claim any credential has been rotated, or that the GitHub purge has occurred;
- assert that segregation of release approval from deployment execution is
  required;
- treat technical verification as business acceptance;
- change any regulatory governance state.

**Governance approvals remain 0 of 20. Production questions remain 0. Item 1
remains PENDING. Production regulatory content remains BLOCKED.**

No Part 11 claim, no validated disaster-recovery claim, and no validated release
process claim is made or implied by anything on this page.
