# Final Engineering Closure Audit

> **What this is:** an audit of what is merged, what currently passes, and what
> remains — separating completed engineering, executable engineering work, and
> externally blocked owner decisions.
> **What this is not:** a validation certificate, a regulatory approval, or a
> production-readiness claim. **It approves nothing and activates nothing.**
> **Audited at** `regx-main` `0ea8e1fd364e54708c47f3160fab01da2b88ad43`.
> **Every test result below was run during this audit against this tip.** No
> historical figure is restated as current.
> **Companions:** [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md),
> [REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md](REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md)

> ## Engineering closure status
>
> # ENGINEERING COMPLETE — EXTERNAL DECISIONS OUTSTANDING
>
> **Qualified, so the reader can judge it.** No product, test or infrastructure
> work remains executable. §B contains two repository-hygiene items: one is
> performed in this change, the other is stale-branch cleanup that the task
> commissioning this audit explicitly deferred. Neither affects product
> behaviour, and neither is blocked on anyone.
>
> **This is a statement about engineering only.** It is **not** a statement that
> the product may be used for production regulatory work — see §D.

## 1. Validation run during this audit

**Environment:** Docker compose stack, 7 services healthy. Backend executed
inside `regx-backend-1`. The container's baked-in backend source was verified
**byte-identical** to this tip by content hash over all 550 first-party `.py`
files before any test was trusted.

### 1.1 Backend

| Check | Command | Result |
|---|---|---|
| pytest | `DJANGO_SETTINGS_MODULE=regx.settings.test pytest --no-cov -q` | **4033 passed, 1 skipped**, 5 warnings, **exit 0**, 17m54s |
| ruff check | `ruff check --cache-dir /tmp/ruffcache .` | **PASS** |
| ruff format | `ruff format --check` | **550 files already formatted** |
| import-linter | `lint-imports --no-cache` | **16 contracts kept, 0 broken** |
| migrations | `makemigrations --check --dry-run` | **No changes detected** |

> **One honest note on how that number was reached.** The first two attempts at
> the suite were killed mid-run by the harness, leaving a `test_regx` database
> behind. The next run reported *3989 passed, 1 skipped, 44 errors* — every error
> being `psycopg.errors.DuplicateDatabase: database "test_regx" already exists`
> at **setup**, not a test assertion. The leftover database was dropped and the
> suite re-run clean, giving the result above. **The 44 errors were an artifact
> of the interrupted runs, not a regression**, and 3989 + 44 = 4033 accounts for
> every test either way.

### 1.2 Frontend

| Check | Command | Result |
|---|---|---|
| Unit | `npm run test` | **555 passed, 23 files**, exit 0 |
| Typecheck | `npm run type-check` | Clean, exit 0 |
| Lint | `npm run lint` | **No ESLint warnings or errors**, exit 0 |
| Production build | `npm run build` | **Compiled successfully**, 29/29 static pages, exit 0 |
| Playwright E2E | `npm run test:e2e` | **257 passed**, exit 0 |

> A first lint attempt using `npx eslint .` reported 5063 errors. That was the
> wrong command — the project lints via `next lint`, and the bare invocation
> linted build output and vendored directories. The CI command is clean. Recorded
> because a 5063-error figure would otherwise look like a finding.

### 1.3 Integrated origin

The Docker workflow's own steps, extracted from
`.github/workflows/docker-integration.yml` and executed verbatim against
`http://localhost:8080`.

| Check | Result |
|---|---|
| Services | **7 of 7 healthy** |
| Every `(regx)` page route frontend-served | **17 enumerated segments, all correct**, exit 0 |
| `/signin`, `/mfa` | frontend-served |
| Company boundary `/`, `/ratools/`, `/adminmaster/login/` | company-served |
| Unrouted-path sentinel | falls through to company 404 |
| API / health | `/api/regx/v1/health/`, `/api/regx/v1/readiness/`, `/healthz`, plus 4 leaf pages — **all 200**, exit 0 |

## 2. Security and boundary checks, run against current code

| Check | Result |
|---|---|
| Production malware scanning fail-closed | **Yes** — `DOCUMENT_SCANNER_ALLOW_STUB` defaults `False`; production raises `ImproperlyConfigured` on the stub backend |
| Stub opt-out documented as local-only | **Yes** — *"For local development only"* in the raised message |
| Tenant isolation enforced | **Yes** — header-resolved, per-app, **27 tenancy tests** |
| Audit architecture centralized | **Yes** — exactly **1** `AuditEvent` model class; 13 domain event modules feed it |
| Duplicate audit subsystem introduced | **No** |
| SSO implementation | **None** — 0 first-party files matching SAML/OIDC/OpenID |
| Office Add-in artifact | **None** — 0 `manifest.xml` |
| AI generation backend | **None** — 0 provider imports |
| Seventh calculation identifier | **No** — registry holds exactly **6** |
| CSV formula-injection guard | **Present in production code** — `iig_checklist/controlled_export.py:700` |
| RATools modified | **No** — 0 files changed under `company_site/` |
| Synthetic audit history added | **No** |
| Production regulatory content activated | **No** |
| Approval register factual | **Yes** — 20 items, 20 PENDING, 0 APPROVED |
| Gate count | **OPEN — 0 of 20** |
| nginx route-coverage test protects flat `(regx)` routes | **Yes** — `frontend/tests/unit/nginx-route-coverage.test.ts` present and passing |
| Docker workflow self-triggers on its own YAML | **Yes** — listed in both `push` and `pull_request` paths |

## 3. Merged work, P0 through current tip

Reconstructed from git. **Docs-only preparation is not described as feature
implementation.**

| PR | Merge SHA | Kind | Subject | Engineering remaining |
|---|---|---|---|---|
| #51 | `c29f0f3` | **executable** | P0 malware scanning | none |
| #52 | `de15742` | **executable** | P1 IIG demo readiness | none |
| #53 | `6118ee9` | **executable** | P2 audit coverage | none |
| #54 | `f003d0d` | **executable** | P3 navigation / discoverability | none |
| #55 | `0c4f65d` | **executable** | P4 repeatable demo handoff | none |
| #56 | `642766d` | **executable** | P5 FDA / Orange Book import readiness | none |
| #57 | `fff12fd` | **executable** | P6 external-integration verification | none |
| #58 | `fd57b52` | **executable** | P7 gap analysis | none |
| #59 | `cf2452e` | **executable** | P8 legacy chatbot removal | none |
| #60 | `d323084` | docs-only | P9 calculator **gap report** | blocked (§C) |
| #61 | `4644759` | docs-only | P10 Word Add-in **gap report** | blocked (§C) |
| #62 | `7545661` | docs-only | P11 stability/impurity **gap report** | blocked (§C) |
| #63 | `edb1ce2` | docs-only | P13a RATools classification | blocked (§C) |
| #64 | `aa501ef` | **executable** | P14a nginx integrated routing fix | none |
| #65 | `c75acbc` | docs-only | P14b documentation consistency | none |
| #66 | `e483ec4` | docs-only | P14 handoff index | none |
| #67 | `a34d654` | **executable** | P15 integrated-origin smoke coverage | none |
| #68 | `4218d57` | **executable** | Docker workflow PR-trigger fix | none |
| #69 | `eb6aa76` | docs-only | P15 handoff update | none |
| #70 | `bbfaa10` | docs-only | External blocker readiness | blocked (§C) |
| #71 | `0c7c2bb` | docs-only | P9 calculator specification **intake** | blocked (§C) |
| #72 | `6cdeeae` | docs-only | P10 Word Add-in contract **intake** | blocked (§C) |
| #73 | `7798f41` | docs-only | P11 assistant feasibility **intake** | blocked (§C) |
| #74 | `d7d4978` | docs-only | P13c RATools disposition **intake** | blocked (§C) |
| #75 | `80661f3` | docs-only | Approval Register 13/14 package | blocked (§C) |
| #76 | `0ea8e1f` | docs-only | Full 20-item gate package | blocked (§C) |

**P12 (SOW 2.11 submission timeline)** produced no PR. It was closed by
inspection as a contractual scheduling item, **N/A for engineering** — no
milestone model, timeline UI, agency clock or statutory deadline logic was built,
and none is owed.

**Every PR listed above is merged**, each as a normal two-parent merge, verified
against `git log --merges` on this tip.

## 4. Open PRs, branches and working tree

**Open PRs: 0.**

Eight remote branches are ahead of `regx-main`. **Seven contain docs-only
commits.** The eighth needed checking:

| Branch | Ahead | Non-docs files | Classification |
|---|---:|---:|---|
| `origin/regx/feat/final-validation-release` | 1 | **1** (`infra/nginx/nginx.conf`) | **Superseded** |
| `origin` | 13 | 0 | historical |
| `origin/docs/setup-and-sow-status` | 9 | 0 | historical |
| `origin/fix/backend-wiring-and-deploy-hardening` | 9 | 0 | historical |
| `origin/fix/claude-md-db-setup-instruction` | 12 | 0 | historical |
| `origin/regx/chore/milestone-4d-closeout` | 1 | 0 | historical |
| `origin/regx/design/milestone-4d-2-discovery` | 14 | 0 | historical |
| `origin/regx/feat/milestone-4d-3-discovery` | 20 | 0 | historical |

> **The one branch with executable content carries no unmerged work.** Its
> `nginx.conf` is an earlier form of the same routing fix P14a landed. Compared
> prefix-by-prefix: the branch declares **21** frontend prefixes, `regx-main`
> declares **21**, and the sets are identical in both directions. Nothing on that
> branch is missing from `regx-main`.

**Working tree:** six untracked PDF checklists in the repository root
(`Quality_System_Checklist-v2.0.pdf` and five siblings). **Scratch — not
repository work**, not tracked, and not touched by this audit. The generator and
verifier scripts used for the 20-item package live in the session scratchpad and
are likewise untracked.

---

# A. Engineering complete

Supported by the evidence in §1–§3.

| Area | Evidence |
|---|---|
| Malware scanning, fail-closed in production | §2; #51 |
| Audit coverage and immutability | §2; #53 |
| Navigation and discoverability | #54 |
| Demo handoff seed | #55 |
| FDA / Orange Book import readiness | #56 |
| External-integration verification | #57 |
| Gap analysis engine, snapshots and UI | #58 |
| Legacy chatbot removal and AI call-site cleanup | #59; §2 confirms 0 provider imports |
| Integrated nginx routing | #64; §1.3 |
| Integrated-origin smoke coverage | #67; §1.3 |
| CI self-trigger on workflow changes | #68; §2 |
| Backend, frontend, E2E and integration suites | §1 — all green at this tip |

# B. Engineering work still executable now

**Neither item is blocked on anyone, and neither affects product behaviour.**

| Task | Evidence | Priority | Why not externally blocked | Status |
|---|---|---|---|---|
| **Handoff index is stale** — [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md) claimed tip `4218d57` and PRs #51–#68, and linked none of the seven blocker/intake documents | Measured in this audit | Low | Pure documentation consistency | **Done in this change** (§5) |
| **Stale branch cleanup** — 8 branches ahead of `regx-main`, all superseded or historical per §4 | §4 | Low | Repository hygiene only | **Deferred** — the task commissioning this audit said not to delete branches |

**No product, test, infrastructure or security work is outstanding.**

# C. Externally blocked

**None of these is an engineering defect, and none can be closed by writing
code.** Each has a completed intake document waiting on a named owner.

| Blocker | Required input | Owner | Status | Intake | Engineering must NOT |
|---|---|---|---|---|---|
| **P9 — SOW 2.3 calculators** | Approved formula specification **and** separately approved engineering scope | Client / regulatory content owner; scope authority | BLOCKED | [CALCULATOR_SPECIFICATION_INTAKE.md](CALCULATOR_SPECIFICATION_INTAKE.md) | Derive a formula from guidance, or add a seventh registry function |
| **P10 — Word Add-in** | 13 product/security contract decisions | Product, security, regulatory owners | BLOCKED | [WORD_ADDIN_CONTRACT_INTAKE.md](WORD_ADDIN_CONTRACT_INTAKE.md) | Weaken CSP/CORS/session, or build a content API before item 3 is decided |
| **P11 — stability/impurity assistant** | Feasibility determination, then product specification | Client / SOW owner; product; regulatory | BLOCKED | [STABILITY_IMPURITY_ASSISTANT_INTAKE.md](STABILITY_IMPURITY_ASSISTANT_INTAKE.md) | Build any generative path, or define "zero hallucination" itself |
| **P13c — RATools disposition** | Record-authority and disposition decision per category | Accountable business / data owner | BLOCKED | [LEGACY_RATOOLS_DISPOSITION_INTAKE.md](LEGACY_RATOOLS_DISPOSITION_INTAKE.md) | Delete, rewrite or migrate anything; backfill synthetic audit history |
| **Approval Register 13/14** | Which calculation binds to which question, with citation | Named regulatory authority (joint with engineering) | PENDING | [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md) | Choose a binding; treat OQ-8 as resolved |
| **20-item production regulatory gate** | All 20 items approved **and** Item 20 signed | Named regulatory authority | **OPEN — 0 of 20** | [REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md](REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md) | Activate production regulatory content |
| **S-1 — GitHub Support purge** | Confirmation that superseded PR #22 objects are purged | Repository owner via GitHub Support | **NOT CONFIRMED** | [REGX_F1_F7_CONSOLIDATED_READINESS.md](REGX_F1_F7_CONSOLIDATED_READINESS.md) §S-1 | Represent the blob as unreachable |
| **S-2 — key / SMTP rotation** | Provider-side revocation of three historical OpenAI keys and the historical SMTP password | Credential owners | **NOT CONFIRMED** | [DEPLOYMENT_BOUNDARIES.md](DEPLOYMENT_BOUNDARIES.md) §6 | Assume rotation happened |
| **13 owner policy decisions** | Operational policy decisions | Owners named in the package | **13 PENDING** | [REGX_OWNER_POLICY_DECISION_PACKAGE.md](REGX_OWNER_POLICY_DECISION_PACKAGE.md) | Adopt a default in place of a decision |

# D. Non-claims and unresolved governance

**Preserved exactly. Nothing in this audit weakens any of them.**

1. **No 21 CFR Part 11 compliance claim.** An immutable audit mechanism is not
   compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source. The calculation tests are engineering evidence,
   **not validation evidence in the regulated sense**.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
4. **No production regulatory content is activated**, and none may be until the
   gate closes.
5. **S-1 purge: NOT CONFIRMED.** No evidence has changed.
6. **S-2 rotation: NOT CONFIRMED.** No evidence has changed.
7. **13 operational policy decisions remain PENDING.**

> **A green test suite is not regulatory readiness.** §1 shows the system does
> what engineering specified. It says nothing about whether the content it would
> carry has been approved — which is §C, and which is nobody's engineering task.

---

# 5. Completion criteria

| Criterion | Evidence | Result | Blocking? | Owner | Next action |
|---|---|---|---|---|---|
| Backend verification | §1.1 | **4033 passed, 1 skipped** | No | Engineering | — |
| Frontend verification | §1.2 | 555 unit, build clean | No | Engineering | — |
| E2E verification | §1.2 | **257 passed** | No | Engineering | — |
| Integrated-origin verification | §1.3 | 17 routes + boundary, exit 0 | No | Engineering | — |
| Migrations clean | §1.1 | No changes detected | No | Engineering | — |
| Security boundary checks | §2 | All pass | No | Engineering | — |
| No open engineering PR | §4 | **0 open** | No | Engineering | — |
| No unmerged engineering branch | §4 | 0 (one superseded, verified) | No | Engineering | — |
| Production regulatory gate | §C | **OPEN — 0 of 20** | **Yes** | Named regulatory authority | Complete the 20-item package |
| P9 calculators | §C | BLOCKED | **Yes** | Client / regulatory | Return the intake form |
| P10 Word Add-in | §C | BLOCKED | **Yes** | Product / security / regulatory | Decide the 13 contract items |
| P11 assistant | §C | BLOCKED | **Yes** | Client / product / regulatory | Determine feasibility |
| P13c RATools | §C | BLOCKED | **Yes** | Business / data owner | Decide record authority |
| S-1 purge | §C | **NOT CONFIRMED** | **Yes** | Repository owner | Obtain GitHub Support confirmation |
| S-2 rotation | §C | **NOT CONFIRMED** | **Yes** | Credential owners | Rotate and confirm |
| Standing non-claims | §D | Intact | n/a | — | Preserve |

# 6. Source-of-truth map

One authoritative document per subject. **No competing source is created.**

| Subject | Authoritative document |
|---|---|
| Engineering closure and current validation | **this document** |
| External blockers, consolidated | [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md) |
| Integrated state across phases P0–P15 | [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md) |
| P9 calculator specification intake | [CALCULATOR_SPECIFICATION_INTAKE.md](CALCULATOR_SPECIFICATION_INTAKE.md) |
| P10 Word Add-in contract intake | [WORD_ADDIN_CONTRACT_INTAKE.md](WORD_ADDIN_CONTRACT_INTAKE.md) |
| P11 assistant feasibility intake | [STABILITY_IMPURITY_ASSISTANT_INTAKE.md](STABILITY_IMPURITY_ASSISTANT_INTAKE.md) |
| P13c RATools disposition intake | [LEGACY_RATOOLS_DISPOSITION_INTAKE.md](LEGACY_RATOOLS_DISPOSITION_INTAKE.md) |
| Approval Register Items 13/14 | [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md) |
| Full 20-item regulatory gate | [REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md](REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md) |
| Legacy RATools surface classification | [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) |
| Approval register itself (the record) | [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md) |

**Note on [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md):** its §1 validation figures are
deliberately pinned to `c75acbc`, the SHA they were measured at. **This audit
does not restate them as current.** Current figures are §1 here, measured at
`0ea8e1f`.
