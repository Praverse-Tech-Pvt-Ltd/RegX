# Milestone 4D-4 Discovery — Overrides/Deviations, Reviewer Conclusion, Controlled Exports, and Production Checklist Content

> **Status:** DISCOVERY — no implementation authorized by this document.
> **Predecessor:** Milestone 4D-3, merged to `regx-main` as `a0ca3a5` (PR #11).
> **Blocking gate:** production regulatory content approval (§E, §J) is required
> *before* 4D-4 implementation begins, per `MILESTONE_4D_DISCOVERY.md` Open
> Question 4. See `MILESTONE_4D_4_CONTENT_APPROVAL.md`.

This document exists because 4D-1, 4D-2 and 4D-3 each had a discovery document
before implementation and 4D-4 did not. It is assembled **only** from statements
already made in the repository. Where the repository does not decide something,
this document records that as an open decision rather than inventing a rule —
particularly for anything that would constitute a regulatory interpretation.

---

## A. Purpose

Close the final governed gaps in checklist execution: let a reviewer record a
justified deviation from an FDA-derived default, complete the reviewer
conclusion, emit a tamper-evident controlled export of an approved execution,
and run all of it against approved production checklist content instead of
synthetic fixtures.

## B. Scope

The authoritative sub-milestone definition is
`MILESTONE_4D_2_DISCOVERY.md:39`:

> **4D-4 (not started):** Overrides/deviations, reviewer conclusion, controlled
> exports, and production checklist content.

Four workstreams, detailed in §G–§J.

## C. Explicit exclusions

- **Draft-answer generation, `FDA_DERIVED_DEFAULT` population,
  `SYSTEM_CALCULATED` computation, recalculation** — these were **4D-3** and are
  merged. `MILESTONE_4D_3_DISCOVERY.md` is titled *"Draft-Answer Generation,
  FDA-Derived Population, and Calculation"*. 4D-4 must not re-open them.
- **PDF and Word export** — "explicitly deferred beyond Milestone 4D"
  (`MILESTONE_4D_DISCOVERY.md:879`). JSON/CSV only.
- **Per-override approval routing** — explicitly decided against (§G).
- **Override of `SYSTEM_CALCULATED`** — explicitly decided against (§G).
- **New calculation functions, async calculation, dashboards, notifications.**
- **Redesign of any 4D-3 contract.**

## D. Dependencies

| Dependency | State |
|---|---|
| 4D-1 definition governance | CLOSED |
| 4D-2 execution/response/outcome foundation | CLOSED |
| 4D-3 calculation automation | CLOSED (`a0ca3a5`) |
| Production regulatory content approval | **OPEN — blocking** |
| `documents` app (evidence attachments, §15) | exists |
| `templates_registry` CSV-safety helper | exists, not yet promoted |

## E. Regulatory-content dependency

`MILESTONE_4D_DISCOVERY.md:1089` (Open Question 4, *RESOLVED BY CONTROLLED
DEFERRAL*):

> The exact set of built-in `ChecklistDefinition` templates to ship … is a
> **regulatory-content decision, not an engineering one** … **route it through a
> separate, dedicated regulatory-content approval gate**, owned by whoever holds
> IIG guidance interpretation authority, **required before 4D-4 begins**. No real
> regulatory checklist template exists in 4D-1 through 4D-3 … implementation
> **must never silently invent real regulatory questions** in the absence of that
> separate approval.

This is a governance restriction on *content*, not on engineering generally.

**Scope resolved — `4D4-DEC-001`, approved 2026-08-11:** the gate blocks the
**production-content workstream only**. Generic 4D-4 engineering may proceed on
synthetic fixtures. Production regulatory checklist content remains blocked in
full until the content-approval package is signed off. See §AB for the allowed
and not-allowed lists, and `MILESTONE_4D_4_CONTENT_APPROVAL.md` for the gate
itself.

## F. Existing reusable capabilities

**Already implemented (no new work):**

| Capability | Location |
|---|---|
| `override_reason` field | `iig_checklist/models.py:631` (`TextField(blank=True)`) |
| `system_derived_value` field | `iig_checklist/models.py:632` (`JSONField(null=True)`) |
| Override integrity rule | `models.py:678` — `override_reason` required when `system_derived_value` is set |
| Reviewer-conclusion service | `services.py:604` `enter_reviewer_conclusion()` + 10 typed exceptions |
| Reviewer-conclusion API | `ChecklistReviewerConclusionView`, 7 API tests |
| Governed response update, `expected_version`, cascade | 4D-3, merged |
| Append-only response history | `ChecklistResponseHistory` |
| Audit on `on_commit` | `iig_checklist/audit.py` |
| CSV formula-injection helper | `templates_registry/reconciliation.py:30` `_csv_safe_cell()` |
| Tenant isolation (`visible_to`) | throughout |
| Frontend response editing surface | `ChecklistResponses.tsx` |

**Notably absent:** `iig_checklist.export_checklist` permission; audit events for
`overridden` / `exported`; any export code; any promoted `common` CSV helper.

## G. Overrides / deviations

Source: `MILESTONE_4D_DISCOVERY.md` §12 (L715–754). Normative and unusually
complete — this section is *decided*, not open.

**Per-classification matrix**, derived strictly from §12:

| | `USER_REQUIRED` (MANUAL) | `FDA_DERIVED_DEFAULT` | `SYSTEM_CALCULATED` |
|---|---|---|---|
| User may edit directly | YES (ordinary answer) | NO — override path only | **NO** |
| Override permitted | n/a (it is the answer) | **YES** | **NO — decided** |
| Minimum permission | `edit_execution` | **`iig_checklist.review`** | n/a |
| Justification required | no | **YES — `override_reason`** | n/a |
| Original value retained | n/a | **YES — `system_derived_value`** | n/a |
| Effective value | `raw_value` | **`raw_value` holds the override** | outcome only |
| Approval | execution-level | **execution-level `approve`, one point** | n/a |
| Audit event | `response.entered/updated` | **`iig_checklist.answer.overridden`** | `response.calculated` |
| History append-only | YES | YES | YES |

Direct quotations for the two strongest rules:

> **Decided:** an override is never allowed on a `SYSTEM_CALCULATED` answer (only
> on `FDA_DERIVED_DEFAULT`) — a calculation is arithmetic on already-confirmed
> inputs; if a reviewer disagrees with a calculated result, the correct action is
> to challenge the *input* answer … not to hand-edit a derived number. (L732)

> overriding any answer requires at minimum `iig_checklist.review` … There is
> exactly **one approval point for every override an execution contains**: the
> single execution-level `approve` action … There is no separate, granular
> per-override approval routing. (L741–754)

Enforcement bar: `override_reason` is "enforced at the transition boundary, not
just serializer validation" (L718). The audit event must carry "old/new value,
actor, and reason" (L727).

**Open decisions (not determined by repository evidence):**
1. `expected_version` semantics for the override path — 4D-3 mandates it for
   ordinary updates; §12 predates 4D-3 and is silent. **Recommendation:** reuse
   the shared `validate_expected_version()`; requires confirmation.
2. Lifecycle states in which an override may be recorded — §12 is silent;
   `EDITABLE_EXECUTION_STATUSES` (`draft`, `returned`) is the obvious analogue
   but is not stated for overrides.
3. Whether an override may itself be revised or withdrawn, and what history
   reason code that carries.
4. Whether `EVIDENCE_DERIVED` and `REVIEWER_CONFIRMED` classifications are
   overridable — §12 names only `FDA_DERIVED_DEFAULT`. **Read conservatively:
   not overridable** until stated.

## H. Reviewer conclusion

Source: `MILESTONE_4D_DISCOVERY.md` §13 (L758–765).

> A `ChecklistExecution`'s `approve` action requires … a top-level
> `reviewer_conclusion_note` (free text, required, min length enforced) — the
> reviewer's own summary statement. This note is stored verbatim and is **never**
> used to derive or influence any system status.

**Already exists:** `enter_reviewer_conclusion()`, the per-response
`REVIEWER_CONCLUSION` answer-type path, `expected_version` handling, empty /
too-long / correction-reason guards, `reviewer_conclusion_note` on the execution,
approve-time requirement, and audit events.

**Remaining for 4D-4:** confirm min-length enforcement matches §13; frontend
surface for entering and displaying conclusions; inclusion in export (§I).

**`ReviewerConclusionSerializer.expected_version` coercion:**
`MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md:3342` records it keeps
`IntegerField(min_value=1)` and "retains the same coercion divergence". No 4D-4
source requires closing it.

**Disposition: OPEN** — not *required* by 4D-4's authoritative scope, but 4D-4 is
the milestone that touches reviewer conclusion, making it the natural place to
close a known divergence from the governed
`validate_expected_version()` contract. Recommend closing; requires approval.

## I. Controlled exports

Source: `MILESTONE_4D_DISCOVERY.md` §17 (L858–901). Also decided, not open.

- **Trigger state:** a **completed (`approved`)** execution only (L860).
- **Formats:** JSON **or** CSV (L861). PDF/Word deferred beyond 4D (L879).
- **CSV safety:** every cell through the existing formula-injection-safe writer;
  "No new CSV-safety code is written" (L865).
- **Helper disposition — decided (was Open Question 3):** promote
  `templates_registry.reconciliation._csv_safe_cell()` to `common` **now, not
  duplicated**; make it public (drop the underscore); update
  `templates_registry`'s import so there is "exactly one implementation
  platform-wide" (L867–877). *Answering §5 of the task: **promote**, do not
  duplicate.*
- **Tamper evidence:** SHA-256 checksum over the canonical serialized payload at
  generation time, stored alongside the audit event (L888).
- **Permission:** a **new** dedicated `iig_checklist.export_checklist`, "not
  implicit from `view`" (L896).
- **Audit:** `iig_checklist.execution.exported` with full decision detail (L899).
- **Reproducibility (§18):** the export must be reconstructable from stored rows
  plus the pinned definition version — it must **never** re-query live
  FDA/formulation data (L907).

**Payload content — partly open.** §18 requires "full per-question provenance",
but 4D-3 deliberately keeps `input_provenance` out of the API projection. These
are different audiences (a regulatory export vs. a UI read model) and the tension
is **not** resolved by the repository.

| Field | Include? | Basis |
|---|---|---|
| Execution + definition identity, `version_number` | YES | §18 pinned version |
| Public UUIDs only, no DB IDs | YES | platform invariant |
| Per-question answer, applicability state | YES | §17 report intent |
| Override: effective value, original, reason, actor | YES | §12 audit intent |
| Reviewer conclusion | YES | §13 |
| `CalculationOutcome` value / status / unit / `reason_code` | YES | §11, 4D-3 projection |
| `input_provenance` / `inputs` | **OPEN** | §18 says provenance; 4D-3 excludes it |
| `generated_at`, SHA-256 checksum | YES | §17 |
| Tenant scoping | YES | platform invariant |

## J. Production checklist content

Governed entirely by the approval gate in §E. **This document defines no
regulatory questions and proposes none.** The full list of what must be approved
is `MILESTONE_4D_4_CONTENT_APPROVAL.md`.

## K. Audit and history

New audit events required (neither exists today in `iig_checklist/audit.py`):

- `iig_checklist.answer.overridden` — old value, new value, actor, reason (§12)
- `iig_checklist.execution.exported` — full decision detail + checksum (§17)

History remains append-only. **Open:** whether an override writes a
`ChecklistResponseHistory` row and under which `ALLOWED_HISTORY_REASON_CODES`
entry — the current closed vocabulary is `APPLICABILITY_REEVALUATED` and
`COMPONENT_REBOUND`, neither of which describes an override. A new code would be
a governed vocabulary change.

## L. Tenant isolation

Unchanged: object lookup through `visible_to(tenant)` first, so a cross-tenant id
is 404 and never 403. Export must be tenant-scoped and must not leak
platform-master content across tenants.

## M. Permissions and roles

| Action | Permission | Exists? |
|---|---|---|
| Record override | `iig_checklist.review` (minimum, §12) | YES |
| Reviewer conclusion | `iig_checklist.review_execution` | YES |
| Approve execution | `iig_checklist.approve_execution` | YES |
| **Export** | **`iig_checklist.export_checklist`** | **NO — new** |

## N. Lifecycle / state restrictions

- Export: `approved` only (§17).
- Override: **OPEN** (§G open decision 2).
- Reviewer conclusion: existing execution lifecycle.
- Post-approval immutability: §18 requires `full_clean()` actually invoked at
  every save attempt once `approved` — explicitly contrasted with
  `AssessmentSnapshot`'s guard, which "is never actually invoked anywhere in the
  request path" (L915). **4D-4 must not copy that unreachable pattern.**

## O. Optimistic concurrency / `expected_version`

4D-3 established one structural `validate_expected_version()` across three write
paths. Overrides are a fourth governed write. §12 predates 4D-3 and is silent.
**Recommendation: reuse the same validator; confirm before implementing.**
Exports are read-only and need none.

## P. Data-integrity requirements

- Original system value preserved beside the override (§12) — field exists.
- `override_reason` non-empty whenever `system_derived_value` set — enforced at
  `models.py:678`; §12 additionally requires enforcement at the transition
  boundary.
- Export checksum over a **canonical** serialization — canonical form must be
  defined so the checksum is reproducible (key order, decimal rendering,
  timestamp format). 4D-3's `format_decimal_plain()` is the established
  plain-notation renderer and should be reused.
- No DB IDs, no live re-query (§18).

## Q. Frontend requirements

- Override entry on `FDA_DERIVED_DEFAULT` responses: reason required, original
  value shown beside the override.
- `SYSTEM_CALCULATED` must remain read-only with **no** override affordance
  (§12) — current behaviour already correct; must not regress.
- Reviewer-conclusion surface.
- Export trigger + download, gated on the new permission and `approved` state.
- Reuse `ProvenanceLabel`, the paginated `responses.list`, `expected_version`
  plumbing and 409 handling from 4D-3.

## R. API / read/write contracts

- Override: **OPEN** — dedicated action endpoint vs. an extension of the governed
  response PATCH. §12 does not say. A dedicated action better matches the
  transition-boundary enforcement requirement and the existing
  `_ChecklistActionViewBase` pattern.
- Export: new read endpoint(s), format-selecting, permission-gated.
- Read model: the 4D-3 `ChecklistResponse` representation is the base; override
  fields already serialize (`override_reason`, `system_derived_value`).

## S. Export security

Permission not implicit from `view`; tenant-scoped; `approved` only; no DB IDs;
no live data re-query; checksum recorded in audit; full decision detail in the
audit payload.

## T. CSV formula-injection protection

Reuse only. Promote `_csv_safe_cell` to `common`, make public, repoint
`templates_registry` (§I). Every exported cell passes through it. **Do not
duplicate**; a second copy is the specific risk L871 warns about.

## U. Error vocabulary

M4D3-OUT-005 (broad external error mapping) remains deferred; `CascadeGraphInvalid`
still surfaces as HTTP 500. 4D-4 adds structured errors for override rejection
and export refusal, following the existing `error_code` + `detail` convention.
Whether 4D-4 closes OUT-005 generally: **OPEN**, no evidence either way.

## V. Approval metadata

`approval_metadata` is **an `AnswerType`**, not a model field
(`MILESTONE_4D_1_IMPLEMENTATION_SPEC.md:353`). Its compatibility floor is fixed:
`REVIEWER_CONFIRMED` only — "never `USER_REQUIRED`, `FDA_DERIVED_DEFAULT`" (L491),
so a tenant user can never author their own approval field.
`MILESTONE_4D_2_DISCOVERY.md:529` records it as `null` in 4D-2 with "shape defined
in 4D-4".

No repository source defines that shape. Therefore:

> **PROPOSED — REQUIRES APPROVAL (not normative).** A JSON object recording the
> approving actor's public identity, approval timestamp, the execution version
> approved, and the reviewer-conclusion reference — no DB IDs, no free-form
> extension. Shape, required keys and mutability must be approved before
> implementation.

**Mutability:** should be write-once at approval and immutable thereafter, by
analogy with §18's post-approval immutability requirement — **requires
confirmation.** Likely JSON-schema validation rather than a model migration,
since the field is an answer `raw_value` shape, not a new column — **TBD**.

## W. Testing strategy

Mirror 4D-3: real PostgreSQL, no mocked DB; per-classification override matrix
(§G) as a parametrized test; negative test that `SYSTEM_CALCULATED` override is
refused; audit-event assertions including old/new/actor/reason; CSV-injection
tests reusing the promoted helper's existing cases; checksum reproducibility
test; permission tests proving export is not implicit from `view`; tenant
isolation 404-before-403; `expected_version` conflict tests if §O is confirmed.

## X. E2E scenarios

1. Reviewer overrides an `FDA_DERIVED_DEFAULT`, reason required, original still
   visible, audit recorded.
2. Override attempt on `SYSTEM_CALCULATED` — no UI affordance, server refuses.
3. Approve with reviewer conclusion; approval blocked without it.
4. Export an approved execution as JSON and CSV; checksum recorded; a formula-
   injection payload in an answer is neutralized in the CSV.
5. Export refused without `export_checklist`, and refused for a non-`approved`
   execution.

## Y. Migration implications

- `override_reason` / `system_derived_value` already exist — **no migration**.
- New audit event **constants** are code, not schema — **no migration**.
- New permission: depends on how permissions are seeded — **TBD**.
- `approval_metadata` shape: likely JSON validation, not a column — **TBD**.
- Production checklist content is **data**, not schema — loaded as governed
  content, not a migration.

**Net expectation: no new models and no migrations for the engineering scope**,
pending the `approval_metadata` and permission-seeding decisions.

## Z. Deferred items and open questions

**Carried forward from 4D-3, unchanged:**
- **M4D3-APP-009** — client can still set `is_not_applicable` on a rule-governed
  response (measured HTTP 200); recorded as a **live exposure**, not a paper
  deferral (`..._EVIDENCE.md:3322`). See the interaction warning below.
- **M4D3-VER-008** — `expected_version` absent from the generated OpenAPI schema.
- **M4D3-OUT-005** — broad error mapping.
- `ReviewerConclusionSerializer` coercion (§H).
- Same-value re-submission re-runs the cascade.
- Durable audit outbox (audit remains `on_commit`).
- Repeating-decimal `DecimalField` observation.

### APP-009 × controlled-export interaction (release-gate language)

Stated as facts, with the decision left open.

1. **Current behaviour.** Per 4D-3 evidence (`..._EVIDENCE.md:3322`), a client
   can set `is_not_applicable` on a **rule-governed** response (measured HTTP
   200). This is recorded there as a live exposure, not a paper deferral.
2. **What §17 would add.** A controlled export of an `approved` execution
   persists applicability state into a governed export artifact and seals it with
   a SHA-256 checksum recorded in the `iig_checklist.execution.exported` audit
   event (L888).
3. **Therefore.** Controlled-export *implementation and release* must not proceed
   until APP-009 is **explicitly dispositioned** by the decision owner. The two
   facts above interact; that interaction is not resolved anywhere in the
   repository, and 4D-3 dispositioned APP-009 without an export surface existing.

**Dispositioned — `4D4-DEC-009`, approved 2026-08-11.** The project owner
selected **closure**: APP-009 must be closed before controlled exports are
released. The two alternatives considered — excluding the affected applicability
state from the export payload, or an alternative governed control such as
recording applicability provenance — are recorded here for traceability and are
**no longer live options**.

Scope: the block applies to the controlled-export **release** only. Export
infrastructure may be built beforehand; it may not ship. No other 4D-4 slice is
blocked by APP-009. See §AB.

> **SATISFIED — APP-009 closed and merged (PR #12, `regx-main` `1c6bd16`).**
> Points 1–3 above describe the exposure as it stood; they are retained as the
> record of *why* the decision was taken, not as a current statement of
> behaviour. A client can no longer set `is_not_applicable` or
> `not_applicable_reason` on a rule-governed response: the governed
> response-update service refuses it with `applicability_server_controlled` and
> HTTP 403, with no write, no version increment, no cascade, no outcome change
> and no success audit. Implementation evidence is in
> `MILESTONE_4D_4_APP_009_EVIDENCE.md`, on `regx-main`.
>
> The `4D4-DEC-009` precondition on controlled-export **release** is therefore
> met. **This does not make controlled exports implemented** — none of §I exists
> yet, and the export payload still depends on the open `4D4-DEC-005`.

**Inconsistency recorded, not silently reconciled:** `docs/ROADMAP.md` stated
*"Milestone 4D (regulatory checklist execution): NOT STARTED"* while 4D-1, 4D-2
and 4D-3 were merged to `regx-main`. Corrected in a separate commit on this
branch; the roadmap remains a status record, never a scope authority — where it
conflicts with a milestone document, the milestone document governs.

---

## AA. Decision register

The authoritative list of what must be decided before 4D-4 engineering.
Six decisions were **approved by the project owner on 2026-08-11**; four remain
open. Status is `APPROVED`, `OPEN` (no repository evidence decides it) or
`PENDING APPROVAL` (a specific human authority must sign off).

An `OPEN` item may not be treated as approved because a recommendation appears
beside it elsewhere in this repository or in a task report.

| ID | Decision / question | Why required | Repository evidence | Owner | Status | Blocks | Resolution |
|---|---|---|---|---|---|---|---|
| **4D4-DEC-001** | Does regulatory-content approval block **all** 4D-4 engineering, or only the production-content workstream? | L1089 says the gate is required "before 4D-4 begins", but 4D-1…4D-3 proceeded on synthetic content. The two readings give different sequencing. | `MILESTONE_4D_DISCOVERY.md:1089`; 4D-1…4D-3 synthetic usage | Project owner | **APPROVED** 2026-08-11 | — (unblocked) | **Content workstream only.** Synthetic engineering content may be used for generic 4D-4 engineering before content approval. Production regulatory content stays blocked. See §AB. |
| **4D4-DEC-002** | `expected_version` semantics for the override write path | 4D-3 made optimistic concurrency mandatory on governed writes; §12 predates it and is silent. An override is a fourth governed write. | §12 (L715–754); 4D-3 `validate_expected_version()` | Project owner | **APPROVED** 2026-08-11 | — | Override writes **reuse the shared `validate_expected_version()`**. No second structural rule. |
| **4D4-DEC-003** | Lifecycle states in which an override may be recorded | §12 does not state them. `EDITABLE_EXECUTION_STATUSES` (`draft`, `returned`) is the analogue but is not stated for overrides. | §12; `services.py` `EDITABLE_EXECUTION_STATUSES` | Project owner | **APPROVED** 2026-08-11 | — | Override permitted **only in the existing editable execution states: `draft` and `returned`** — i.e. exactly `EDITABLE_EXECUTION_STATUSES`. |
| **4D4-DEC-004** | History reason-code vocabulary for override/deviation | `ALLOWED_HISTORY_REASON_CODES` is a closed vocabulary holding only `APPLICABILITY_REEVALUATED` and `COMPONENT_REBOUND`; neither describes an override. Adding one is a governed vocabulary change. | `governed_vocabularies.py`; M4D3-HST-005 | Eng lead + Regulatory | **OPEN** | Slice 2 | — |
| **4D4-DEC-005** | Export payload provenance depth | §18 requires "full per-question provenance"; 4D-3 deliberately excludes `input_provenance` from the API projection. Different audiences, unresolved tension. | §17 (L887); §18; 4D-3 projection | Regulatory + Eng lead | **OPEN** | Slice 1 | — |
| **4D4-DEC-006** | Canonical export serialization + checksum contract | §17 mandates a SHA-256 over the "canonical serialized export payload" but does not define canonical form (key order, decimal rendering, timestamp format). Without it the checksum is not reproducible. | §17 (L888); 4D-3 `format_decimal_plain()` | Project owner | **APPROVED** 2026-08-11 | — | Canonical form: **deterministic key ordering; `format_decimal_plain()` for decimals; UTC ISO-8601 timestamps; stable UTF-8 bytes.** |
| **4D4-DEC-007** | Override API shape — dedicated action endpoint vs. extension of the governed response PATCH | §12 requires enforcement "at the transition boundary, not just serializer validation", which suggests an action; the repository does not decide. | §12 (L718); `_ChecklistActionViewBase` pattern | Project owner | **APPROVED** 2026-08-11 | — | **Dedicated governed action endpoint**, not the ordinary response PATCH. |
| **4D4-DEC-008** | `approval_metadata` schema and mutability | 4D-2 records it as `null` with "shape defined in 4D-4". No source defines the shape. §V holds a **PROPOSED, non-normative** sketch only. | `MILESTONE_4D_2_DISCOVERY.md:529`; `4D_1_..._SPEC.md:353` | Regulatory + Eng lead | **PENDING APPROVAL** | Slice 2/3 | — |
| **4D4-DEC-009** | APP-009 disposition before controlled exports are released | At the time of the decision a client could set `is_not_applicable` on a rule-governed response, and §17 would seal applicability state into a checksummed export. | `..._EVIDENCE.md:3322`; §17 (L888) | Project owner | **APPROVED** 2026-08-11 · **SATISFIED** (PR #12, `1c6bd16`) | — (precondition met) | **APP-009 must be closed before controlled exports are released.** Closed and merged; the governed service now refuses client-supplied applicability on a rule-governed response with `applicability_server_controlled` / 403. Export release is no longer blocked by APP-009 — exports remain **unimplemented**. |
| **4D4-DEC-010** | Are `EVIDENCE_DERIVED` and `REVIEWER_CONFIRMED` responses overridable? | §12 names only `FDA_DERIVED_DEFAULT`. Read conservatively as *not* overridable, but the exclusion is inferred rather than stated. | §12 (L717, L732) | Regulatory | **OPEN** | Slice 2 | — |

**Sequencing consequence.** With `4D4-DEC-001` approved, generic 4D-4 engineering
on synthetic content is unblocked. Slice 2 (overrides) still requires
`4D4-DEC-004` and `4D4-DEC-010`. Slice 1's *release* precondition —
`4D4-DEC-009`'s closure of APP-009 — is now **met** (PR #12, `1c6bd16`); its
payload shape still requires `4D4-DEC-005`, which remains open, and no export
code exists yet. Production regulatory content remains blocked in full by the
content-approval package.

---

## AB. Approved governance position (2026-08-11)

### Synthetic vs. production content — `4D4-DEC-001`

**Approved:** synthetic engineering content **MAY** be used for generic 4D-4
engineering before production regulatory-content approval. Production regulatory
checklist content remains **BLOCKED** until the separate content-approval package
is approved.

| Allowed before content approval | Not allowed before content approval |
|---|---|
| Generic override/deviation infrastructure | Authoring production regulatory checklist questions |
| Reviewer-conclusion completion | Loading production regulatory templates |
| Controlled-export infrastructure | Activating production regulatory templates |
| Unit / integration / E2E on synthetic fixtures | Shipping production regulatory checklist content |
| API and frontend engineering containing no real regulatory questions | |

This preserves L1089's actual purpose — that implementation "must never silently
invent real regulatory questions" — while allowing the engineering that does not
touch regulatory content, exactly as 4D-1 through 4D-3 proceeded.

### APP-009 and controlled exports — `4D4-DEC-009` — **SATISFIED**

**Approved:** APP-009 **must be closed before controlled exports are released.**
Controlled exports persist and checksum applicability state, so exporting a
rule-governed applicability value that remains client-mutable is not acceptable.

Scope of the block: the **controlled-export release** only. APP-009 does not
block override infrastructure, reviewer-conclusion completion, or any other 4D-4
slice, and export infrastructure may be built before APP-009 closes — it may not
be *released*.

The alternatives previously listed in §Z (excluding applicability state from the
payload; an alternative governed control) are **no longer live options**: the
owner selected closure.

**Condition met.** APP-009 was implemented, independently reviewed twice and
merged to `regx-main` as PR #12 (`1c6bd16`). Ownership is enforced at the
governed domain service on `question.applicability_rule`, so a direct domain call
is bound identically to an HTTP request; rejection is inert. See
`MILESTONE_4D_4_APP_009_EVIDENCE.md`.

Controlled-export release is therefore **no longer blocked by APP-009**. It
remains unimplemented, and its payload shape still depends on `4D4-DEC-005`,
which stays open.

### Approved engineering conventions

| ID | Convention |
|---|---|
| `4D4-DEC-002` | Override writes reuse the shared `validate_expected_version()` — one structural rule across all governed writes. |
| `4D4-DEC-003` | Override permitted only in `draft` and `returned` (`EDITABLE_EXECUTION_STATUSES`). |
| `4D4-DEC-006` | Checksum canonical form: deterministic key ordering, `format_decimal_plain()` decimals, UTC ISO-8601 timestamps, stable UTF-8 bytes. |
| `4D4-DEC-007` | Override uses a dedicated governed action endpoint, not the ordinary response PATCH. |

None contradicts repository evidence: `4D4-DEC-002` extends 4D-3's single-validator
principle; `4D4-DEC-003` matches the existing constant; `4D4-DEC-006` reuses
4D-3's established decimal renderer; `4D4-DEC-007` matches §12's
transition-boundary requirement and the existing `_ChecklistActionViewBase`
pattern.

### Gate status

Current as of `regx-main` `1c6bd16` (PR #12 merged).

| Gate | Status |
|---|---|
| Engineering may start | **YES** — synthetic content only |
| Production content may start | **NO** |
| APP-009 prerequisite (`4D4-DEC-009`) | **SATISFIED** — closed and merged, PR #12 |
| Controlled export **release** | **NOT BLOCKED BY APP-009.** Still **NOT IMPLEMENTED**; payload shape depends on open `DEC-005` |
| Override implementation | **PARTIALLY READY** — `DEC-002/003/007` approved; `DEC-004`, `DEC-010` open |
| Reviewer conclusion | **PARTIALLY READY** — service exists; serializer-coercion disposition open |
| Production checklist content | **BLOCKED** — content-approval package, **0 of 20** production-content items approved |

Only `4D4-DEC-009` changed state. `DEC-004`, `DEC-005`, `DEC-008` and `DEC-010`
remain open and are untouched by the APP-009 merge.

**Already decided by repository evidence — recorded here so they are not
re-litigated as open questions:** override is permitted only on
`FDA_DERIVED_DEFAULT` and never on `SYSTEM_CALCULATED` (§12); the minimum
override permission is `iig_checklist.review` (§12); there is exactly one
approval point per execution, with no per-override routing (§12);
`_csv_safe_cell` is promoted to `common` rather than duplicated (§17, former Open
Question 3); PDF/Word export is deferred beyond 4D (§17); export requires a
dedicated `iig_checklist.export_checklist` permission (§17); and no new
calculation status vocabulary is introduced (§11).
