# IID Precedent Decision Statuses

`iid_assessment/decisions.py`, `decide(...)`. Produces exactly one of a
fixed, closed set of statuses. **None of them may ever be interpreted as an
automatic safety determination or a regulatory approval** — this is
enforced structurally, not just by convention.

## The closed status set (`PrecedentDecisionStatus`)

| Status | Meaning |
|---|---|
| `PASS_WITH_IID_PRECEDENT` | Proposed amount is within the selected IID potency (and MDE, if available) precedent. |
| `REVIEW_REQUIRED` | Multiple exact matches, ambiguous ingredient identity, unusable potency, superseded source, or MDE unavailable while otherwise within potency — a human decision is required. |
| `EXCEEDS_IID_PRECEDENT` | Proposed amount per unit or daily exposure exceeds the selected IID precedent. |
| `NO_MATCH` | No exact ingredient/route/dosage-form IID precedent record exists. |
| `NOT_COMPARABLE` | Route/dosage-form mismatch, or the unit/basis could not be reconciled between the proposal and the selected record. |

`_ALLOWED_STATUSES` is this exact frozenset. `PrecedentDecision.__post_init__`
raises `ValueError` if `status` is not in that set — it is structurally
impossible to construct a decision outside this vocabulary.

## Forbidden words

`_FORBIDDEN_STATUS_WORDS = ("SAFE", "FDA APPROVED", "AUTOMATICALLY
ACCEPTABLE", "REGULATORILY CLEARED")`. `PrecedentDecision.__post_init__`
raises `ValueError` if the note text contains any of these words as an
apparent conclusion (the check exempts the literal phrase "NOT AN
AUTOMATIC", which is how the required disclaimer text below refers to them).
This means these words simply cannot exist anywhere in a constructed
`PrecedentDecision.note` as an assertion — not a lint rule, a runtime
invariant.

## Required note text on PASS

`REQUIRED_PRECEDENT_NOTE = "Within selected FDA IID precedent. This is not
an automatic safety determination or regulatory approval."` — every
`PASS_WITH_IID_PRECEDENT` decision carries exactly this note.

## Decision precedence (`decide(...)`)

In order, the first matching condition wins:

1. `match_status == NO_MATCHING_IID_PRECEDENT` → `NO_MATCH`.
2. `match_status in (ROUTE_MISMATCH, DOSAGE_FORM_MISMATCH)` →
   `NOT_COMPARABLE`.
3. Unit conversion failed, or density/basis required → `NOT_COMPARABLE`
   (`reason_codes=["UNIT_OR_BASIS_UNRECONCILED"]`).
4. `match_status == MULTIPLE_EXACT_MATCHES` (or `multiple_candidates`) →
   `REVIEW_REQUIRED`, `escalation_required=True` — a reviewer must select
   the precedent record.
5. `match_status in (INGREDIENT_AMBIGUOUS, REVIEW_REQUIRED)` →
   `REVIEW_REQUIRED`, `escalation_required=True`.
6. No usable potency value on the selected record → `REVIEW_REQUIRED`,
   `escalation_required=True`.
7. Proposed amount unavailable → `NOT_COMPARABLE`.
8. Proposed amount exceeds selected IID potency → `EXCEEDS_IID_PRECEDENT`,
   `escalation_required=True`. Justification and reviewer conclusion are
   mandatory; approval is never automatic.
9. If MDE is available and proposed daily exposure exceeds selected MDE →
   `EXCEEDS_IID_PRECEDENT`, `escalation_required=True`.
10. Source release superseded, or MDE unavailable while otherwise within
    potency → `REVIEW_REQUIRED`, `escalation_required=True`.
11. Otherwise → `PASS_WITH_IID_PRECEDENT` with the required note.

## What can never happen

No `SAFE`, `FDA APPROVED`, `AUTOMATICALLY ACCEPTABLE`, or `REGULATORILY
CLEARED` status exists in this vocabulary — there is no status that could
ever be read as such. See
`iid_assessment/tests/test_decisions.py` for coverage of all five statuses
and the structural forbidden-status/forbidden-word enforcement, and
`fda_data`/`iid_assessment` API tests for the end-to-end check that no
forbidden word ever reaches an HTTP response body.
