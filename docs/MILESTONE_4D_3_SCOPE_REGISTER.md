# Milestone 4D-3 Scope Register

**Status: DISCOVERY. Open questions unresolved. Not approved for implementation.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This register is the single authoritative list of 4D-3 scope inclusions, exclusions, and
open questions. Every entry must be resolvable before the implementation specification
is finalized.

---

## Part A — Confirmed In Scope

| ID | Feature | Authoritative source |
|---|---|---|
| S-01 | `FDA_DERIVED_DEFAULT` population at execution creation | 4D design §10; 4D-2 discovery §1 |
| S-02 | `SYSTEM_CALCULATED` computation at execution creation | 4D design §10; 4D-2 discovery §1 |
| S-03 | In-draft cascade recalculation on `enter_response()` for USER_REQUIRED/EVIDENCE_DERIVED updates | 4D design §8b; 4D-2 discovery §6d |
| S-04 | `CalculationOutcome` rows updated from DATA_REQUIRED to real values | 4D-2 implementation spec §9; models.py comment |
| S-05 | `source_assessment_snapshot_public_id` populated when snapshot is the source | 4D design §9 |
| S-06 | Applicability runtime evaluator (pure function, no eval/exec) | 4D-3 discovery §5; field_registry.py + applicability.py already validate |
| S-07 | Applicability context assembly from FormulationVersion + FDA match result | 4D-3 discovery §5a |
| S-08 | `NOT_APPLICABLE` state set for questions whose rule evaluates false | 4D design §3a; 4D-3 discovery §5c |
| S-09 | New audit event `iig_checklist.response.fda_populated` (distinct from response.entered) | 4D-3 discovery §10 |
| S-10 | Frontend: per-question display with provenance labels in execution detail | 4D-2 discovery §15; 4D-3 discovery §8 |
| S-11 | Frontend: SYSTEM_CALCULATED answer display (value + status code, no fabricated value) | 4D design §11; 4D-3 discovery §8 |
| S-12 | Frontend: recalculation feedback via server reload after PATCH, no client formula evaluation | 4D-3 discovery §8 |
| S-13 | Reuse all six calculation functions from iid_assessment.calculations verbatim | 4D design §20; IID_CALCULATION_RULES.md |
| S-14 | Reuse resolve_substance_identity() and find_iid_candidates() verbatim | 4D design §4 |
| S-15 | No new database models or migrations | 4D-3 discovery §7 |
| S-16 | full_clean() enforced on every CalculationOutcome update (AssessmentSnapshot defect must not recur) | 4D design §7/§18; 4D-2 implementation spec §3 |

---

## Part B — Confirmed Out of Scope for 4D-3

| ID | Feature | Deferred to |
|---|---|---|
| X-01 | Override/deviation workflow | 4D-4 |
| X-02 | Controlled JSON/CSV export | 4D-4 |
| X-03 | SHA-256 checksum on export | 4D-4 |
| X-04 | Promotion of _csv_safe_cell() to common | 4D-4 |
| X-05 | EVIDENCE_DERIVED attachment-confirmation enforcement at submission | 4D-4 |
| X-06 | Real regulatory checklist content (any ChecklistDefinition template) | Regulatory-content gate (pre-4D-4) |
| X-07 | PDF/Word export | Explicitly deferred beyond 4D |
| X-08 | New calculation formulas | Not in scope for any 4D stage |
| X-09 | Electronic signatures, 21 CFR Part 11 compliance | Not in scope for any 4D stage |
| X-10 | Auto-approval based on population result | Never — structural prohibition |
| X-11 | Formula logic in the frontend | Never — backend only |
| X-12 | Any modification to iid_assessment, fda_data, formulations, or documents app models | Confirmed: 4D-3 is a consumer only |
| X-13 | New calculation formulas beyond the six in iid_assessment.calculations | Not in scope |

---

## Part C — Open Questions (must resolve before implementation spec)

### OQ-1: `ChecklistAnswerSource` — functions vs. class

**What it governs:** The shape of the resolver layer that calls existing FDA/IID services
during the population pass (§4b of the discovery document).

**Option A — module-level functions:**
```
# iig_checklist/answer_sources.py
def resolve_fda_derived(question, formulation_version, context): ...
def resolve_identity_match(question, formulation_version): ...
```
Pros: simpler, no unnecessary state, consistent with how `iid_assessment.calculations`
functions are already structured. Cons: slightly harder to mock in tests (requires
`unittest.mock.patch` at the module level).

**Option B — class with injected services:**
```
class ChecklistAnswerSource:
    def __init__(self, substance_resolver, iid_matcher): ...
    def resolve(self, question, formulation_version, context): ...
```
Pros: explicit dependency injection makes unit testing without hitting the database
easier. Cons: adds an object where a function would do; the existing codebase uses
functions for calculation services, not classes.

**Recommendation (for reviewer to accept or override):** Option A, with targeted
`patch` in tests. The codebase consistently uses module-level functions for services.

**Resolution required by:** before implementation spec is written.
**Status:** OPEN

---

### OQ-2: `calculation_binding` JSON schema

**What it governs:** `ChecklistQuestion.calculation_binding` is a `JSONField` that
tells the population pass which calculation function to invoke and where to source the
numeric inputs. The 4D discovery document describes the concept (§9) but does not define
the normative JSON schema.

**Proposed schema:**
```json
{
  "function": "calculate_percentage_w_w",
  "inputs": {
    "quantity_per_unit_grams": {
      "source": "question",
      "question_code": "Q4",
      "unit_conversion": "to_grams"
    },
    "total_dosage_unit_weight_grams": {
      "source": "formulation_version",
      "field": "total_dosage_unit_weight",
      "unit_conversion": "to_grams"
    }
  }
}
```

`source` values: `"question"` (from another `ChecklistResponse.raw_value`) or
`"formulation_version"` (from a `FormulationVersion` field). `unit_conversion` is
optional; when present, names a conversion function from `iid_assessment.unit_conversion`.

**Concerns:**
- Unit conversion logic lives in `iid_assessment.unit_conversion`. The binding schema
  must reference a controlled vocabulary of conversion identifiers, not arbitrary
  function names.
- `question_code` must be validated at `ChecklistVersion` activation time to confirm
  the referenced question exists in the same version.
- Cross-version references (a binding that references a question in a different version)
  must be rejected.

**Recommendation:** Adopt the proposed schema with the controlled `unit_conversion`
vocabulary defined in the implementation spec. A reviewer must confirm the schema is
expressive enough to represent all six calculation formulas against IIG checklist
question shapes before the implementation spec is written.

**Resolution required by:** before implementation spec is written.
**Status:** OPEN

---

### OQ-3: Cascade recalculation — in-transaction vs. post-commit

**What it governs:** When `enter_response()` writes a `USER_REQUIRED` answer on a
`draft` execution, every dependent `SYSTEM_CALCULATED` answer must be recomputed.
The question is whether this cascade runs inside the same `transaction.atomic()` block
as the response write, or deferred to `transaction.on_commit()`.

**Option A — in-transaction (same atomic block):**
- Pros: atomic consistency; a reader always sees `USER_REQUIRED` and `SYSTEM_CALCULATED`
  in sync; simpler error handling (rollback covers everything).
- Cons: longer transactions; if the calculation itself calls external services
  (it does not — all six functions are pure and Decimal-only), it could block the
  transaction.

**Option B — post-commit (deferred):**
- Pros: shorter transactions; `USER_REQUIRED` write commits fast.
- Cons: a window exists where the execution is committed with the new `USER_REQUIRED`
  value but stale `CalculationOutcome` rows; a concurrent reader in that window would see
  an inconsistent state; error handling for failed recalculation after commit is
  significantly more complex.

**Recommendation:** Option A. The six calculation functions are pure, fast, and Decimal-
only (no I/O, no external calls). Transaction duration is not a concern. Consistency is
paramount.

**Resolution required by:** before implementation spec is written.
**Status:** OPEN

---

### OQ-4: `AssessmentSnapshot` source — snapshot-first vs. live-first

**What it governs:** When the population pass computes `SYSTEM_CALCULATED` answers that
mirror an IID assessment result, should it prefer an existing `AssessmentSnapshot` for
the `FormulationComponent` or always call `run_preview()` live and freeze a new snapshot?

**Option A — snapshot-first:**
Find the most recent non-stale `AssessmentSnapshot` for the `FormulationComponent` /
`FormulationVersion` combination. Use its frozen values if found. Call `run_preview()`
only if no suitable snapshot exists. Set `source_assessment_snapshot_public_id` to the
found or newly created snapshot.

Pros: avoids redundant computation; reuses already-verified assessment data.
Cons: introduces a "freshness" question — what makes an existing snapshot "non-stale"?
An existing snapshot may reference a superseded FDA release. Requires a staleness check
against the current active release, adding complexity.

**Option B — live-first (always create a new snapshot):**
Always call `run_preview()` at population time against the currently active FDA release.
Freeze the result as a new `AssessmentSnapshot` if none exists for this `(FormulationComponent,
active_release)` tuple, or reuse an existing exact match. Set
`source_assessment_snapshot_public_id` unconditionally.

Pros: population always uses the current active release; `source_assessment_snapshot_public_id`
is always set; reproducibility is unconditional; no staleness logic needed.
Cons: creates a new snapshot per execution creation if no matching one exists; slightly
more expensive at population time.

**Recommendation:** Option B. Reproducibility should be unconditional. The cost of one
`run_preview()` call per execution creation is negligible versus the risk of silently
using a stale snapshot. Staleness avoidance code is a maintenance liability.

**Resolution required by:** before implementation spec is written.
**Status:** OPEN

---

## Part D — Dependency Map

```
4D-3 depends on (must be present, unchanged):
  iig_checklist (4D-1, 4D-2)
    ChecklistDefinition / ChecklistVersion / ChecklistSection / ChecklistQuestion
    ChecklistExecution / ChecklistResponse / CalculationOutcome (4D-2 models)
    execution_transitions.py / enter_response() service
    applicability.validate_condition_json() / field_registry.py (4D-1)
  iid_assessment (4A-4C)
    calculations.py (six functions, CalculationResult, CalculationStatus)
    matching.find_iid_candidates()
    assess.run_preview()
    AssessmentSnapshot model
  fda_data (4A-4C)
    substance_matching.resolve_substance_identity()
    IIDIngredient / IIDPrecedentRecord / SubstanceSynonymMapping (read-only)
  formulations (4A-4C)
    FormulationVersion / FormulationComponent (read-only)

4D-4 depends on 4D-3:
  override/deviation workflow assumes calculation answers are populated
  export assumes CalculationOutcome.value is non-null for approved executions
```

---

## Part E — Acceptance Criteria (for design review)

The 4D-3 design is ready for implementation specification when:

1. OQ-1 through OQ-4 are formally resolved with a single chosen option and documented
   rationale.
2. The `calculation_binding` JSON schema (OQ-2) has been confirmed expressive enough to
   represent all six calculation formula bindings for at least the synthetic
   paracetamol/acetaminophen worked example (4D design §19).
3. No new database models or migrations are required (confirmed: all needed columns exist
   in 4D-2).
4. A human reviewer with domain authority has read this register and the discovery
   document and confirmed scope boundaries.
5. No item from Part B (Out of Scope) has been silently added to any proposed
   implementation description.
