# Milestone 4D-4 — Reviewer Conclusion: Implementation Evidence

> **Scope:** the governed **per-response** `REVIEWER_CONCLUSION` workflow —
> `4D4-DEC-013` (strict `expected_version`), the `4D4-DEC-012` capability
> extension, and the frontend surface that completes the slice.
> **Branch:** `regx/feat/milestone-4d-4-reviewer-conclusion-completion`
> **Base:** `regx-main` `7acf167`
> **Models:** unchanged. **Migrations:** none.

---

## 1. The concept separation this slice depends on

Two different things share a name, and conflating them was the largest risk in
this slice:

| | Execution-level note | Per-response governed answer |
|---|---|---|
| Field | `ChecklistExecution.reviewer_conclusion_note` | `ChecklistResponse.raw_value` on a `REVIEWER_CONCLUSION` question |
| Written by | `approve()` — `ApproveSerializer` | `enter_reviewer_conclusion()` — `ReviewerConclusionSerializer` |
| Endpoint | `iig_checklist:execution-approve` | `iig_checklist:execution-reviewer-conclusion` |
| Effect | Closes the review; transitions the execution | Answers one question; execution stays under review |
| History | none | `ChecklistResponseHistory` row on every amendment |
| Audit | approval events | `checklist_response.reviewer_conclusion_entered` / `_updated` |
| Amendable | no | yes, with a required `correction_reason` |

**The missing engineering work was the second one.** The frontend implements it
through the dedicated endpoint. `approve()` is never used as a substitute —
answering a question must not end a review as a side effect, and doing so would
skip the per-response audit and amendment history entirely. The ordinary
response PATCH is equally unusable: `response_validation.py:285` refuses a
`reviewer_conclusion` `raw_value` on that path outright.

A frontend test asserts the negative directly
(`does not use execution approve() as a substitute`), and the wire-level test
asserts exactly one write request, to the reviewer-conclusion URL.

---

## 2. Backend — strict concurrency (`4D4-DEC-013`)

`ReviewerConclusionSerializer.expected_version` was a DRF `IntegerField`, which
**coerces**: `"1"` and `1.0` both became `1`. A malformed version silently
became a valid one on this path, while the response-update and override paths
refused it through the shared `validate_expected_version()`. One concept, two
structural rules.

**Implemented:** the serializer field is now a presence-only `JSONField`
passthrough; the value arrives at the service intact and is validated once, by
the same `calculation_execution.validate_expected_version()` the other two
governed write paths use.

### 2.1 Rejected coercive and malformed inputs

| Submitted `expected_version` | Result |
|---|---|
| `1` (correct integer) | **Accepted** |
| `"1"` | **Refused** — 400 `invalid_expected_version` |
| `1.0` | **Refused** — 400 `invalid_expected_version` |
| `"1.0"` | **Refused** — 400 `invalid_expected_version` |
| `true` / `false` | **Refused** — 400 `invalid_expected_version` |
| `null` | **Refused** — 400 `invalid_expected_version` |
| `0`, negative | **Refused** — 400 `invalid_expected_version` |
| key absent | **Refused** — 400 `expected_version_required` |
| stale but well-formed integer | **Refused** — 409 `reviewer_conclusion_stale_version` |

The last two rows are the point of the decision: **malformed is 400, stale is
409.** A client can tell "you sent nonsense" from "someone changed the row
underneath you", and only the second warrants a refetch-and-retry.

Pinned by `test_4d4_reviewer_conclusion_completion.py::TestStrictExpectedVersion`,
including `test_no_coercive_integerfield_remains` (a structural guard against
the field being restored) and `test_all_three_governed_paths_share_one_validator`.

---

## 3. Capability matrix (`4D4-DEC-012` extension)

`GET /api/regx/v1/iig-checklists/capabilities/` now returns exactly:

```json
{ "can_override_response": false, "can_enter_reviewer_conclusion": true }
```

| Role | `can_override_response` | `can_enter_reviewer_conclusion` |
|---|---|---|
| Reviewer | `true` (`PERM_OVERRIDE_EXECUTION`) | **`true`** (`PERM_REVIEW_EXECUTION`) |
| Doer | `false` | **`false`** |
| VP | `true` | per `ROLE_PERMISSIONS`, asserted against the mapping |
| Tenant Admin | per `ROLE_PERMISSIONS` | per `ROLE_PERMISSIONS` |

- Derived from `has_iig_checklist_permission()` — the same predicate the service
  enforces with, so the flag cannot disagree with the service that owns it.
- Tenant-scoped; fail-closed when no tenant context exists.
- Named flags only — no codenames, role identifiers or other authorization
  internals leak (`test_no_permission_internals_leak`).
- **The key set is exact, not a subset.** `assert set(resp.data) == {...}` — an
  unapproved third key fails the contract test. That assertion was extended, not
  weakened.

---

## 4. §13 interpretation — the numeric minimum

§13 requires the conclusion to be **free text, required, minimum length
enforced**, and specifies **no numeric minimum**.

**No numeric minimum was invented.** No 3-, 5- or 10-character rule exists
anywhere in this slice. Inventing a threshold the source withholds would be
engineering authoring a regulatory rule.

The enforced requirement is **meaningful non-empty**:

| Input | Disposition |
|---|---|
| missing `raw_value` / non-string `value` | refused — `reviewer_conclusion_invalid_payload` |
| `""` | refused — `reviewer_conclusion_empty` |
| `"   "`, `"\t\n"` | refused — `reviewer_conclusion_empty` |
| `"Y"` (one meaningful character) | **accepted** |
| 4000 characters | accepted (boundary) |
| 4001 characters | refused — `reviewer_conclusion_too_long` |

The maximum is the pre-existing `MAX_REVIEWER_CONCLUSION_CHARS = 4000`,
unchanged by this slice.

Pinned on **both** sides so neither can drift:

- `test_4d4_reviewer_conclusion_completion.py::TestConclusionTextRequirements`
- `test_4d4_frontend_payload_contract.py::test_a_meaningful_one_character_conclusion_is_accepted`
- `reviewer-conclusion-ui.test.tsx` — *"accepts a meaningful one-character
  conclusion — §13 sets no numeric minimum"*

The one-character tests are deliberately the guard against a future invented
minimum: adding one would fail three tests in two languages.

---

## 5. Frontend workflow

**Client** — `iigChecklists.executions.responses.reviewerConclusion()`.

Payload, exactly:

```ts
{ raw_value: { value: string }, expected_version: number, correction_reason?: string }
```

- `correction_reason` is **omitted entirely** on first entry; the service wants
  it only when amending.
- `expected_version` is the loaded response's `version`, sent as a JSON integer.
  A test asserts this against the serialized body, so `"3"` or `3.0` would fail.
- **Never sent:** reviewer identity, timestamps, `confirmed_by`, `confirmed_at`,
  `version`, history, `data_source_type_snapshot`, `override_reason`. All of it
  is derived server-side from the authenticated actor, and the serializer
  refuses each one as `unknown_field` — asserted per-field in the backend
  contract test.
- Text is sent **as typed**, not trimmed: trimming would silently alter a
  regulated record. The backend strips only to decide emptiness.

**UI** — inside the existing `ChecklistResponses` component and its patterns.

| Requirement | Implementation |
|---|---|
| Display existing conclusion | `reviewer-conclusion-current-*`, always rendered, ungated |
| "Enter Reviewer Conclusion" when none exists | button label switches on `rawValue === null` |
| "Amend Reviewer Conclusion" where governed | same switch; correction-reason input appears only when amending |
| Gate on capability | `can_enter_reviewer_conclusion`, default `false` |
| Never gate on role names | no role string exists in the component |
| Lifecycle | `submitted_for_review` only |
| Answer-type restriction | `reviewer_conclusion` only; branch precedes classification |
| Meaningful non-empty | `reviewerConclusionError()` — refused before any request |
| Whitespace-only refused | same, via `.trim()` |
| Maximum enforced | `maxLength={4000}`, and re-checked in the handler |
| No invented minimum | no `minLength`, asserted by test |
| Integer `expected_version` | straight from the loaded response |
| Stale conflict | 409 → refetch **first**, then report the server's reason |
| Governed errors | 400 detail surfaced verbatim; 403 as a permission refusal |
| Authoritative refetch | full response list re-read after success |
| Unauthorized Doer | sees the conclusion, never the action |
| No clear/delete | none offered — §AC.4 defers it |

**Fail-closed:** the capability defaults to `false` and a failed capability
fetch leaves it `false`, so a network error cannot reveal a reviewer action to a
Doer. This is presentation only — `PERM_REVIEW_EXECUTION` is enforced by the
service regardless, and a client that ignores the flag receives the same 403.

A 409 refetches **before** reporting, because it means our picture is stale. It
reports the server's own detail rather than guessing between
`reviewer_conclusion_stale_version` and `reviewer_conclusion_invalid_state` —
`ApiError` carries only status and detail, so inferring the code from prose
would be a fabrication.

---

## 6. Lifecycle

`enter_reviewer_conclusion()` accepts **only** `submitted_for_review`, and
re-checks it under `select_for_update()` inside the transaction, so an execution
that leaves review mid-write is refused rather than half-written. Any other
status returns 409 `reviewer_conclusion_invalid_state`.

The UI mirrors this: the action is hidden in `draft`, `returned`, `approved`,
`rejected` and `cancelled` — all five asserted.

---

## 7. History, audit, export

**History.** An amendment writes one append-only `ChecklistResponseHistory` row
carrying prior/new `raw_value`, prior/new version, prior actor and timestamp,
`correction_reason`, `amended_by` and the source-classification snapshot. First
entry writes **no** history row — there is no prior state to record.
`ChecklistResponse.save()` permits update only for reviewer conclusions, and
only through this service (`models.py:654`).

**Audit.** Emitted post-commit: `checklist_response.reviewer_conclusion_entered`
on first entry, `..._updated` on amendment. The payload carries execution,
response and question public IDs, prior and new response version, execution
status, and `correction_reason_present` — never the conclusion text itself.

**Controlled export.** Reviewer amendments reach the checksum-covered payload as
the allow-listed `reviewer_amendments` group (`4D4-DEC-005`), and flow through
to the CSV rendering. Adding an amendment, or changing any exported amendment
field, changes the checksum — both asserted. Mutation F below proves the
coverage is real rather than incidental.

---

## 8. Tests

### Backend

| Suite | Result |
|---|---|
| `test_4d4_reviewer_conclusion_completion.py`, `test_reviewer_conclusion_api.py`, `test_4d4_approval_capabilities.py` | **61 passed** |
| `test_4d4_overrides.py`, `test_4d4_controlled_export.py`, `test_4d3_response_update.py`, `test_platform_authorization.py`, `test_execution_api.py`, `test_response_api.py` | **231 passed** |
| `test_4d4_frontend_payload_contract.py` (extended this slice) | **50 passed** |

Covers reviewer conclusion, strict `expected_version`, permissions, tenant
isolation, reviewer amendment history, audit, controlled export and checksum
coverage. **0 failed.**

The cross-language contract file was extended with the reviewer-conclusion
payload the frontend actually emits, asserted against the real
`ReviewerConclusionSerializer` — the same guarantee the existing block gives the
ordinary editor, which previously had no counterpart for this endpoint.

### Frontend

| File | Tests |
|---|---|
| `tests/unit/reviewer-conclusion-api.test.ts` | 10 — wire-level, only `fetch` stubbed |
| `tests/unit/reviewer-conclusion-ui.test.tsx` | 30 — component behaviour |

The wire file mocks nothing above `fetch`, so it asserts the real request body.
Mocking the client would prove only that a function was called.

All nineteen required coverage points are present: capability typed; exact
payload; authorized reviewer sees the action; unauthorized user does not;
lifecycle gating (five statuses); answer-type gating; current conclusion
displayed; Enter; Amend; empty refused; whitespace-only refused; one meaningful
character accepted; maximum enforced; integer `expected_version`; stale conflict;
governed validation error; authoritative refetch; `approve()` not used; no
server-controlled fields.

---

## 9. Mutation proofs

Each mutation was applied alone, measured, then reverted. **Residual mutations:
NONE** — the working tree was verified clean after each revert.

| | Mutation | Expected | Observed |
|---|---|---|---|
| **A** | Restore coercive `IntegerField` `expected_version` | strict tests fail | **5 failed** — `[str_1]`, `[float_1_0]`, `[str_1_0]`, `[bool_true]`, `test_no_coercive_integerfield_remains` |
| **B** | Bypass the reviewer permission gate | unauthorized test fails | **1 failed** — `TestPermissionAndLifecycle::test_doer_is_refused` |
| **C** | Remove meaningful-non-empty enforcement (serializer + service) | whitespace-only test fails | **7 failed** — 3 whitespace/empty cases backend, 3 in the cross-language pin, plus `test_empty_value_rejected` |
| **D** | Frontend ignores `can_enter_reviewer_conclusion` | unauthorized visibility test fails | **3 failed** — unauthorized Doer, fail-closed on fetch error, capability-not-role |
| **E** | Remove the authoritative frontend refetch | refetch test fails | **1 failed** — *refetches authoritative state after success* |
| **F** | Drop reviewer-amendment provenance from the checksum-covered export | export/checksum regression fails | **6 failed** — including `test_adding_an_amendment_changes_the_checksum` and `test_changing_an_exported_amendment_field_changes_the_checksum` |

C failing on **both** sides of the wire is the useful detail: the §13 reading is
pinned in two languages, so a one-sided regression cannot pass.

---

## 10. Gate results

| Gate | Result |
|---|---|
| Full backend suite | **2018 passed, 0 failed** (901.63s) |
| Backend coverage | **94.87%** (23121 statements, 1185 missed) |
| Frontend unit | **238 passed, 0 failed** across 12 files |
| Type-check (`tsc --noEmit`) | **PASS** — no errors |
| Lint (`next lint`) | **PASS** — no warnings or errors |
| Playwright / E2E | **91 passed, 0 failed** |
| `manage.py check` | **PASS** — no issues (0 silenced) |
| `makemigrations --check --dry-run` | **PASS** — no changes detected |
| `migrate --check` | **PASS** |
| `ruff check .` | **PASS** — all checks passed |
| `ruff format --check .` | **PASS** — 279 files formatted |
| `lint-imports` | **PASS** — 7 contracts kept, 0 broken |

Prior trustworthy baseline was 1976 passed at 94.82%. This slice adds tests and
no failures; coverage moves to 94.87%.

**Models unchanged. Migrations: none.** Confirmed by
`makemigrations --check --dry-run` reporting no changes.

### 10.1 E2E disposition

**PASS — 91 of 91, no failures, no new regressions.**

`fda-iid.spec.ts` has a documented history of parallel-execution instability and
is the known baseline flake. It did **not** fail in this run, so there is nothing
to attribute to either the baseline or this branch. No unrelated FDA-IID code was
modified — making E2E green by touching it was explicitly out of bounds, and was
not necessary.

### 10.2 Process discipline

No two pytest processes ran concurrently — the test PostgreSQL database is
shared, and a previous session produced invalid results by violating this. Every
backend suite ran serially.

One deviation is recorded rather than hidden: `ruff format` reformatted a new
backend test file while a full-coverage run was in flight, which is exactly the
"no backend edits during coverage measurement" rule. **That run was discarded**
and the full suite was re-run from a clean, committed tree with no concurrent
pytest and no edits during the run. The 2018/94.87% figures above are from that
clean re-run.

---

## 11. Milestone 4D closure reassessment

`MILESTONE_4D_CLOSEOUT_STATUS.md` §5 (on the preserved closeout branch
`regx/chore/milestone-4d-closeout`, `ebc09da`) lists four remaining engineering
items. Re-read against the repository after this slice:

| # | Item as recorded | Classification now |
|---|---|---|
| 1 | Reviewer-conclusion **frontend surface** — "the governed service, its dedicated endpoint and its export projection all exist; the UI does not… no client calls the per-response reviewer-conclusion endpoint" | **IMPLEMENTED** — typed client, UI, 40 frontend tests; the per-response endpoint now has a real caller |
| 2 | Reviewer-conclusion **minimum-length enforcement** — "confirm min-length enforcement matches §13" | **IMPLEMENTED / RESOLVED** — confirmed: §13 specifies **no numeric minimum**. Meaningful non-empty is enforced and documented (§H.1); no threshold invented |
| 3 | `ReviewerConclusionSerializer.expected_version` **coercion — disposition OPEN**, "a governance decision, not a free fix" | **IMPLEMENTED** — registered and approved as `4D4-DEC-013`, then implemented. Three governed write paths, now one contract |
| 4 | **Override clearing** — deferred by §AC.4 | **APPROVED-DEFERRED** — unchanged; no clear path, no `ANSWER_OVERRIDE_CLEARED` code, no route, and no clear action offered for reviewer conclusions either |

Additional items outside that list:

| Item | Classification |
|---|---|
| `ControlledExportError` | **MINOR TECHNICAL DEBT — DEFERRED** |
| Production regulatory content | **PRODUCTION-CONTENT-GATED — 0 of 20** |
| `fda-iid.spec.ts` parallel instability | known baseline test debt; did not reproduce this run |

**Critical: 0. Major: 0. Blocking: none.**

Items 1–3 were the required engineering work and are complete. Item 4 is
approved-deferred by an existing decision, not an omission. On that basis:

> **Engineering Milestone 4D: READY FOR CLOSEOUT.**

This is deliberately **not** marked COMPLETE here. Closure is recorded on the
preserved closeout branch `regx/chore/milestone-4d-closeout` (`ebc09da`), which
carries the roadmap correction and `MILESTONE_4D_CLOSEOUT_STATUS.md` and is kept
separate from this feature branch. Production regulatory content remains a
separate gate at 0 of 20 and is **not** satisfied by any result in this document.

## 12. Remaining deferred items

| Item | Classification |
|---|---|
| Override **clearing** | **APPROVED-DEFERRED** — §AC.4 defers it; no clear/delete action is offered for reviewer conclusions either |
| `ControlledExportError` | **MINOR-DEFERRED** — technical debt, not a governed gap |
| Production regulatory content | **SEPARATE GATE — 0 of 20** — regulatory authorship, not engineering |
| E2E `fda-iid.spec.ts` parallel instability | known baseline flake, unrelated to this slice |

None is a Critical or Major engineering item, and none blocks the
reviewer-conclusion workflow.
