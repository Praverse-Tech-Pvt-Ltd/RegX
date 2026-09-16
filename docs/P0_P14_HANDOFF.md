# RegX — P0–P14 Handoff

> **An index of the current integrated state, not a restatement of it.** Every
> finding below has a canonical document; this page says what is true now, what
> is blocked and on whom, and links to the record that carries the detail.
> **Measured at** `regx-main` `c75acbcb2afb38d606ff90c892f5d78016aa891f`.

## Why this document exists rather than an update to an existing one

Five readiness and release documents already exist. None could carry this
content without being rewritten into something it is not:

| Document | What it is | Why not this |
|---|---|---|
| [REGX_F1_F7_CONSOLIDATED_READINESS.md](REGX_F1_F7_CONSOLIDATED_READINESS.md) | Closure record for seven specific controls F-1…F-7 | Its §1 matrix is those seven gaps with their PRs; P0–P14 is a different axis |
| [REGX_PARALLEL_TECHNICAL_READINESS.md](REGX_PARALLEL_TECHNICAL_READINESS.md) | *"Discovery only"* — superseded by the above, by its own statement | Historical by declaration |
| [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md) | *"State at the Milestone 16 head"* | Milestone-scoped |
| [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md) | *"What was actually run against the Milestone 9–15 platform"* | Milestone 16 evidence record |
| [RELEASE_ROLLBACK_RUNBOOK.md](RELEASE_ROLLBACK_RUNBOOK.md) | Deploy / verify / rollback procedure | A runbook, not a status record |

All five are closed records pinned to past milestones and SHAs. Amending one to
describe the P0–P14 state would rewrite a record of what was true at a past
point — the exact failure P14b corrected in `SOW_SECTION_2_STATUS.md`, which had
been amended in place while still claiming to measure `0da78c8`.

## 1. Validation, measured at this SHA

Run against images **rebuilt from this source**, not the working containers that
had accumulated file copies during development. The backend production image
installs `requirements/base.txt` only, so `requirements/dev.txt` was installed
into the running container exactly as CI does before the test tooling was
invoked.

| Check | Result |
|---|---|
| Backend `pytest` (`DJANGO_SETTINGS_MODULE=regx.settings.test`) | **4033 passed, 1 skipped** |
| `ruff check` | All checks passed |
| `ruff format --check` | 550 files already formatted |
| `lint-imports` | **16 contracts kept, 0 broken** |
| `makemigrations --check --dry-run` | No changes detected |
| Frontend unit (Vitest) | **551 passed**, 22 files |
| Frontend typecheck / lint / production build | Clean · Clean · Compiled successfully |
| Playwright E2E | **257 passed** |
| Docker integrated stack | 7 services healthy; `readiness` reports `database: ok`, `cache: ok` |

**Test evidence, not validation evidence.** These are engineering checks. No
validated-system claim follows from them — see §6.

## 2. Phase disposition P0–P14

| Phase | Status | Record |
|---|---|---|
| **P0** Malware scanning hardening | **COMPLETE** | production refuses the stub scanner unless an explicit escape hatch is set |
| **P1** IIG demo execution readiness | **COMPLETE** | — |
| **P2** Audit coverage hardening | **COMPLETE** | per-event-type payload allow-lists in `iig_checklist.audit` |
| **P3** Navigation and discoverability | **COMPLETE** | — |
| **P4** Repeatable demo handoff seed | **COMPLETE** | [DEMO_ENVIRONMENT.md](DEMO_ENVIRONMENT.md) |
| **P5** FDA / Orange Book import readiness | **COMPLETE** | [ORANGE_BOOK_INGESTION.md](ORANGE_BOOK_INGESTION.md) |
| **P6** External integration verification | **COMPLETE** | tests only; no production behaviour changed |
| **P7** Governed gap analysis snapshots and UI | **COMPLETE** | one engine, two surfaces; immutable snapshots |
| **P8** Legacy chatbot removal, OpenAI search fix | **COMPLETE** | [SOW_SECTION_2_STATUS.md](SOW_SECTION_2_STATUS.md) Note 2.6 |
| **P9** Calculators | **BLOCKED** on approved formula specifications | [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) |
| **P10** Word Add-in / contextual drafting | **BLOCKED** on product/security contract | [WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md) |
| **P11** Stability/impurity; calculation provenance | **BLOCKED** / **CONFORMANT** / **NOT DETERMINED** | [STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md) |
| **P12** SOW 2.11 timeline | **N/A for engineering** — contractual scheduling item | — |
| **P13a** Legacy RATools classification | **COMPLETE** | [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) |
| **P13b** Dead-code cleanup | **COLLAPSED** — no standalone phase | dropped; only commented-out text was ever in scope |
| **P13c** Legacy approval/signature disposition | **BLOCKED** on accountable owner | [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) §4.4 |
| **P14** Final integrated verification | **COMPLETE** | this document; one defect found and fixed (§4) |

## 3. Current capabilities

Built, tested and reachable on the integrated origin. Each links to its own
record rather than being described twice.

* **Document platform** — versioning, SHA-256 duplicate detection, malware
  scanning that fails closed in production, quarantine.
  [DOCUMENT_PLATFORM.md](DOCUMENT_PLATFORM.md)
* **IIG checklist engine** — governed definitions and versions, runtime
  applicability evaluation, six approved calculations, controlled export.
  [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §2
* **Gap analysis** — one deterministic engine behind the on-demand read and
  immutable `GapAnalysis` snapshots; factual counts, **no score**.
* **FDA data** — IID ingestion, Orange Book import, terminology mapping,
  deficiency corpora (ANDA and Major CR).
  [FDA_IID_INGESTION.md](FDA_IID_INGESTION.md),
  [ORANGE_BOOK_INGESTION.md](ORANGE_BOOK_INGESTION.md)
* **Workflows** — Doer / Reviewer / VP with append-only transitions.
  [WORKFLOW_ENGINE.md](WORKFLOW_ENGINE.md)
* **Dossiers, packages, operations** — blueprints, instantiation, frozen
  packages, a read-model dashboard that owns no data.
  [SUBMISSION_OPERATIONS_DASHBOARD.md](SUBMISSION_OPERATIONS_DASHBOARD.md)
* **External integrations** — outbound HTTPS connectors with SSRF defence:
  HTTPS only, ports {443, 8443}, every DNS answer classified, connection pinned
  to the checked address, redirects refused rather than followed.
  [EXTERNAL_INTEGRATIONS.md](EXTERNAL_INTEGRATIONS.md)
* **Audit** — one centralized `AuditEvent`, append-only at two layers.
  [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)
* **Tenancy** — header-resolved, fail-closed.
  [TENANCY.md](TENANCY.md)

## 4. Architecture and security invariants, re-verified

| Invariant | Evidence at this SHA |
|---|---|
| Tenant isolation fail-closed | 404 unknown tenant, 403 no-tenant-no-auth; covered by `test_no_tenant_header_no_auth_returns_403` and `test_fail_closed_when_no_tenant_set` |
| Audit immutability | ORM guard raises on update and delete; Postgres triggers `no_update_audit_event`, `no_delete_audit_event` |
| Malware scanning | `DOCUMENT_SCANNER_ALLOW_STUB` defaults `False`; production raises `ImproperlyConfigured` on the stub |
| SSRF / DNS | `ALLOWED_SCHEMES={https}`, `ALLOWED_PORTS={443,8443}`, `resolve_destination` intact |
| No hardcoded secrets | No key, token or private-key pattern anywhere in tracked source |
| No JWT / OAuth / SSO claim | None implemented; the only matches are guards asserting absence |
| No synthetic audit backfill | Every match asserts the opposite, including `test_historical_rows_are_not_backfilled` |
| No legacy approval semantics in REGX | `controlled_correspondence` ports template content only — zero approval fields |

**One defect was found in P14 and fixed.** Six RegX page prefixes were missing
from the nginx location list, so `/regulatory-cases`, `/dossier-blueprints`,
`/submission-operations`, `/external-integrations`, `/submission-dossiers` and
`/submission-packages` answered 404 on the integrated origin while serving
correctly on the frontend container's own port. Four sidebar links pointed into
that set. Fixed; all six verified 200 at this SHA. See §5 for why nothing caught
it.

## 5. Open engineering risk — integrated-origin smoke coverage

**Recorded, deliberately not implemented during handoff.**

Nothing in the test suite exercises the integrated nginx origin. Playwright
drives its own Next.js server on port 3100; the container checks cover `/`,
`/healthz`, the health endpoints and `/ratools/` — not the feature paths. The
defect in §4 sat exactly between those two layers, which is why a complete green
suite coexisted with six unreachable pages.

The fix added a comment marking the location list as load-bearing. That helps a
person reading the file; it catches nothing automatically. **A page added
tomorrow without its location entry would fail the same way and pass every
test.**

Closing this means an integrated-origin smoke check — a focused change with its
own design decisions about what to assert and where it runs. It is not folded
into this handoff.

## 6. Blocked and deferred — none of it is blocked on engineering

| Item | Blocked on | Default until then |
|---|---|---|
| **SOW 2.3 calculators** | Client-supplied approved formula specifications, **and** separately approved engineering scope — `SCOPE-OUT-18` caps the registry at six formulas | Not built |
| **SOW 2.7 Word Add-in** | 13 product/security contract items, including a Word-compatible authentication flow and a governed content-retrieval API | Not built |
| **SOW 2.9 stability/impurity assistant** | Feasibility and product specification; the SOW itself is recorded as marking it feasibility-TBD | Not built |
| **Approval Register Items 13 and 14** | A named regulatory authority. The register stands at **0 of 20 approved** and states the count advances only on a real approval | Content not activated |
| **P13c — legacy approval states and signature images** | An accountable business or data owner | **Retain-and-freeze** |

**On P13c specifically.** Authority status is unresolved: the codebase cannot
establish whether legacy RATools approval states or stored signature images
remain authoritative records for any client or process. Until an accountable
owner determines their disposition they are treated as potentially
authoritative and are **not deleted, rewritten, or silently replaced by REGX
workflow records**. The absence of centralized audit coverage in legacy RATools
is a documented governance exposure; it is **not** evidence that historical
approvals are invalid, and it does **not** justify fabricating audit history. No
synthetic audit event shall be backfilled for any past approval change or
signature upload.

## 7. What is not claimed

Three standing non-claims. They are not softened anywhere in this document and
must not be softened in any summary of it.

1. **No 21 CFR Part 11 compliance claim.** The codebase declines it explicitly
   in `backend/workflows/models.py`, [DOSSIER_BLUEPRINTS.md](DOSSIER_BLUEPRINTS.md)
   and [DOSSIER_UPGRADES.md](DOSSIER_UPGRADES.md). An immutable audit mechanism
   is not compliance.
2. **No validated-production claim for the calculation engine.** The six
   formulas are governed by an approved *engineering* specification, not by a
   traceable external regulatory source, and the 279 calculation tests are
   engineering evidence rather than validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** The gap reports record what
   the repository contains and what is missing. They determine no regulatory
   status, and P11 explicitly leaves Part 11 sufficiency **NOT DETERMINED**.

Further standing limitations, each stated in its own document, are listed in
[REGX_F1_F7_CONSOLIDATED_READINESS.md](REGX_F1_F7_CONSOLIDATED_READINESS.md) §9.

## 8. Repository state

* **Head:** `c75acbcb2afb38d606ff90c892f5d78016aa891f`
* PRs **#51–#65** merged, every one a normal two-parent merge.
* No open pull requests at the time of writing.
* No P-phase branch carries unmerged commits. Five older branches do; each was
  checked and is superseded or historical.
* `company_site` remains a separate Django project against its own SQLite
  database, sharing a repository and compose stack with REGX but no code.
  [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md)
