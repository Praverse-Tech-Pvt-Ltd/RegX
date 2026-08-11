# Milestone 4D-4 — M4D3-APP-009 Applicability Ownership: Implementation Evidence

> **Closes:** the APP-009 prerequisite only.
> **Does not close:** Milestone 4D-4. Overrides/deviations, reviewer-conclusion
> completion, controlled exports and production checklist content all remain
> outstanding, as do `4D4-DEC-004`, `-005`, `-008` and `-010`.
> **Unblocks:** `4D4-DEC-009`, the controlled-export release prerequisite.

## 1. The exposure, as it stood

`MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md:3322` recorded APP-009 as deferred and
explicitly as a **live exposure**, not a paper deferral:

> **M4D3-APP-009** — a client can still set `is_not_applicable` on a
> **rule-governed** response (measured: HTTP 200) … until it lands, the fields
> M4D3-APP-008 calls server-owned are client-writable when a rule governs them.

Reproduced before any change, against real PostgreSQL through the governed HTTP
endpoint and the domain service: **7 failed, 12 passed** in
`iig_checklist/tests/test_4d4_applicability_governance.py`. The write genuinely
landed — `test_no_field_is_written` failed with `assert True is False`, i.e. the
client's `is_not_applicable=True` was persisted on a rule-governed response.

The 12 that passed pre-change are the invariants that had to survive: manual
applicability, an ordinary answer edit, APP-011, stale-version handling.

## 2. Ownership rule

Taken from the approved specification, not invented:

- **M4D3-APP-008** — for any response whose `question.applicability_rule` is
  non-null, `is_not_applicable` and `not_applicable_reason` are server-owned;
  the governed applicability service is their only writer.
- **M4D3-APP-009** — the governed response-update service rejects a
  client-supplied value for either field on such a response with
  `error_code = "applicability_server_controlled"` and **HTTP 403**.
- **M4D3-APP-010** — where no rule governs the question, a client-declared N/A
  remains permitted.

**Mechanism:** `ChecklistQuestion.applicability_rule_id is not None`. No new
ownership model was introduced.

**Scope discipline.** `ChecklistSection` also carries an `applicability_rule`.
APP-008/009 name the *question's* rule only, so the guard is scoped to that.
Section-level governance is recorded as an open question in §9 rather than
silently included — broadening the guard beyond the documented exposure would
be a scope decision this work is not authorized to take.

**Presence, not value.** A payload naming either field at all is an attempt to
author it. `is_not_applicable=False` on an already-N/A response is a *clear*,
and is refused for the same reason: clearing is as much authorship as setting.

## 3. Domain boundary

The guard is in `update_checklist_response()` (`iig_checklist/services.py`), not
in the serializer, the view, or the frontend:

- a **direct service call** raises `ResponseUpdateApplicabilityServerControlled`
  (proved by `test_direct_service_call_is_also_rejected`);
- the **HTTP path** maps it to 403 in `ChecklistResponseUpdateView`;
- the frontend change is defence in depth and convenience, never the control.

It runs in Phase A, **before** `transaction.atomic()` opens, so a rejected
attempt cannot write, increment, cascade or audit.

## 4. Error contract

`error_code = "applicability_server_controlled"`, HTTP **403** — both fixed by
M4D3-APP-009, neither invented here.

403 matches its siblings M4D3-SVC-005 (server-controlled stored value) and
M4D3-APP-011 (reserved marker): the objection is the same in kind — the value is
owned by the server, not the caller.

**Deliberately not folded into APP-011.** `reserved_reason_prefix` is about a
*value* no client may write anywhere; this is about *ownership* of two fields on
a particular class of response. Collapsing them would report the wrong reason and
would wrongly imply a non-reserved applicability value is acceptable on a
rule-governed response. The detail string names the rule, never internals.

**Ordering, pinned by test:** payload deserialization → **APP-009 ownership** →
APP-011 reserved marker → `expected_version`. Ownership precedes the marker check
because on a rule-governed response the client may not author the field at all,
so the value it carries is never reached. A malformed payload still reports its
own fault (400) rather than being reclassified as an ownership problem.

## 5. Zero-mutation behaviour

Each proved by its own test, on a rejected attempt:

| Property | Test |
|---|---|
| No field written | `test_no_field_is_written` |
| No version increment | `test_no_version_increment` |
| No cascade | `test_no_cascade_runs` |
| No `CalculationOutcome` change | `test_no_calculation_outcome_changes` |
| No success audit | `test_no_success_audit_is_emitted` |
| No history row | `test_no_history_row_is_written` |
| Mixed payload rejected whole | `test_applicability_cannot_be_smuggled_beside_a_valid_answer_edit` |

The last matters most: a payload pairing a legitimate answer edit with an
applicability change is refused **entirely**, so the edit cannot ride along.

No denied-attempt security audit event was added — the platform has no such
standard for this path and the specification requires none. Inventing one is out
of scope.

## 6. System evaluation is not foreclosed

**There is no governed applicability writer yet.** `iig_checklist/applicability.py`
states it plainly: *"4D-1 validates and canonicalizes only. Runtime evaluation of
a condition tree against a real execution context is a later Milestone 4D
stage."* Nothing in production writes `is_not_applicable` from a rule today.

So there was no system path to preserve, and none was broken. What this work does
guarantee is that the future engine is not foreclosed: the guard is a
**client-write boundary in one service**, not a model-level ban.
`test_the_field_stays_writable_below_the_client_service` pins that the field
remains writable beneath that boundary.

The invariant delivered is *"a client cannot author rule-governed
applicability"*, not *"applicability can never change"*.

## 7. APP-011 interaction

APP-011 is untouched and independent. Combination coverage:

| Case | Result |
|---|---|
| Ungoverned + reserved marker | 403 `reserved_reason_prefix` (APP-011) |
| Rule-governed + applicability change | 403 `applicability_server_controlled` (APP-009) |
| Rule-governed + reserved marker | 403 `applicability_server_controlled` — ownership first, deterministic |

## 8. Test and gate evidence

**New:** 19 tests in `iig_checklist/tests/test_4d4_applicability_governance.py`
(pre-change 7 failed / 12 passed → post-change 19 passed).

| Gate | Result |
|---|---|
| APP-009 focused | 19 passed |
| Response-update (baseline 60) | 60 passed |
| Applicability | 15 passed |
| Cascade (baseline 140) | 140 passed |
| Response / execution / reviewer-conclusion API | 30 passed |
| Frontend unit (baseline 168) | 171 passed |
| Frontend E2E | 91 passed |

**Mutation proof.** Disabling the guard reproduced exactly the original 7
failures, with `test_no_field_is_written` failing `assert True is False` — the
client write landing again, i.e. the measured HTTP 200 exposure. Reverted and
re-verified absent.

## 9. Open and deferred, unchanged by this work

- `4D4-DEC-004` override history reason-code vocabulary
- `4D4-DEC-005` export provenance depth
- `4D4-DEC-008` `approval_metadata` schema
- `4D4-DEC-010` whether `EVIDENCE_DERIVED` / `REVIEWER_CONFIRMED` are overridable
- Production regulatory content — gate open, 0 of 20 approved
- M4D3-VER-008 (OpenAPI), M4D3-OUT-005 (broad error mapping),
  `ReviewerConclusionSerializer` coercion, durable audit outbox

**New open question raised, not resolved:** `ChecklistSection.applicability_rule`
also exists. APP-008/009 name only the question's rule, so section-governed
applicability is currently *not* covered by this guard. Whether a section rule
should confer the same ownership is a specification question for the decision
owner.

## 10. What this does not claim

This closes the APP-009 prerequisite and satisfies `4D4-DEC-009`'s condition for
controlled-export release. It does not implement exports, overrides, reviewer
conclusion, or any production content, and Milestone 4D-4 remains open.

---

## 11. Addendum — response payload interoperability defect

**Found during the independent APP-009 review. Unrelated to APP-009, and
APP-009's closure is unaffected: the guard is evaluated before any raw-value
shape concern and both were re-verified after this remediation.**

### The defect

`response_validation.py` gives every answer type an exact `raw_value` shape, and
all eight types the response editor supports require an **envelope**:
`{"value": <typed value>}`. The merged editor's `toPayloadValue()` returned bare
scalars, so every save was refused with `invalid_raw_value_shape` (400). The
editor could not save **any** answer type against a real backend.

It escaped 4D-3 because both suites mocked past the wire: the unit tests mocked
`responses.update()` and asserted only that it had been *called*, and the E2E
mocked the backend with the same incorrect shape it was itself sending. Nothing
compared the two languages. The backend APP-009 tests, which construct real
payloads, are what surfaced it.

Two errors, not one:

1. **Missing envelope** on all eight supported types.
2. **`yes_no_na` sent a boolean**, where the backend requires the closed string
   vocabulary `"yes" | "no" | "not_applicable"`.

A third trap sits next to them and is now pinned by test: `yes_no` requires a
JSON **boolean** while `yes_no_na` requires a **string** — near-synonymous names,
different inner types.

### Corrected contract

| Answer type | Payload | Inner type |
|---|---|---|
| `short_text` / `long_narrative` | `{"value": …}` | non-empty string |
| `integer` | `{"value": …}` | JSON integer (bool refused) |
| `decimal` / `percentage` | `{"value": …}` | decimal **string** — never a JS number, so no precision is lost |
| `date` | `{"value": …}` | `"YYYY-MM-DD"` |
| `yes_no` | `{"value": …}` | JSON boolean |
| `yes_no_na` | `{"value": …}` | `"yes"` / `"no"` / `"not_applicable"` |

An empty edit still clears the answer with a bare `null`, which is distinct from
declaring the response not-applicable.

`yes_no` and `yes_no_na` now use select controls: a boolean and a closed
vocabulary cannot be produced deterministically from a free-text box. The
`yes_no_na` answer value `not_applicable` is deliberately **not** collapsed into
the response-level `is_not_applicable` applicability flag — they are separate
concepts and the backend treats them separately.

### Types deliberately not offered

`quantity_with_unit`, `single_select`, `multi_select`, `fda_record_reference`,
`formulation_component_reference` and `attachment_reference` each require a shape
a single value control cannot produce (a unit, an option code, a sorted code
list, or a resolved public id). They are rendered read-only rather than given a
control whose every save would be refused. `calculated_value`,
`calculated_status` and `approval_metadata` are never client-writable, and
`reviewer_conclusion` has its own endpoint.

### Regression evidence

The fix is pinned from both sides, which is what was missing before:

- **Frontend, wire level** — 11 tests drive the real `toPayloadValue()` through
  the real `responses.update()` and read the request body off a stubbed `fetch`.
  `responses.update()` itself is **not** mocked.
- **Backend, cross-language** — 34 tests in
  `test_4d4_frontend_payload_contract.py` assert the exact payloads the frontend
  emits against the real `validate_raw_value_shape()`, and assert that the
  pre-fix bare scalars are **rejected**, so a future refactor cannot quietly
  reintroduce them.
- **Obsolete mocks corrected, not preserved** — the 4D-3 unit assertion and the
  4D-3 E2E mock both encoded the wrong shape and were updated to the real
  contract.

Gates after remediation: frontend type-check and lint clean, unit 182, E2E 91;
backend APP-009 19, payload contract 34, response-update 60, applicability 15.
