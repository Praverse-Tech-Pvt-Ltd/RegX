# Milestone 4D-3 Scope Register

**Status: DISCOVERY COMPLETE. All open questions resolved. Pending second adversarial review before implementation specification.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This register is the single authoritative list of 4D-3 scope inclusions, exclusions, and
open questions. All four open questions are resolved. The resolved decisions and the
additional in-scope items identified during adversarial review are documented here.

---

## Part A — Confirmed In Scope

| ID | Feature | Authoritative source |
|---|---|---|
| S-01 | `FDA_DERIVED_DEFAULT` population at execution creation | 4D design §10; 4D-2 discovery §1 |
| S-02 | `SYSTEM_CALCULATED` computation at execution creation | 4D design §10; 4D-2 discovery §1 |
| S-03 | In-draft cascade recalculation in the new governed `update_checklist_response()` service for USER_REQUIRED/EVIDENCE_DERIVED updates | 4D design §8b; 4D-2 discovery §6d |
| S-04 | `CalculationOutcome` rows updated from `"data_required"` to `"complete"` or `"error"` (via translation layer) | 4D-2 implementation spec §9; models.py comment; adversarial review CR-1 |
| S-05 | `source_assessment_snapshot_public_id` populated via live-first `run_preview()` with tenant filter | 4D design §9; OQ-4 resolved |
| S-06 | Applicability runtime evaluator — pure function, no eval/exec, returns `ApplicabilityOutcome` | 4D-3 discovery §5; field_registry.py + applicability.py |
| S-07 | Applicability context assembly from FormulationVersion + FDA match result | 4D-3 discovery §5a |
| S-08 | `NOT_APPLICABLE`, `APPLICABLE`, and `REVIEW_REQUIRED` outcome consumption from `ApplicabilityRule.outcome_if_true/false` | 4D design §3a; 4D-3 discovery §5c; adversarial review CR-10 |
| S-09 | New audit event `iig_checklist.response.fda_populated` (distinct from `response.entered`) | 4D-3 discovery §10 |
| S-10 | Frontend: per-question display with provenance labels in execution detail | 4D-2 discovery §15; 4D-3 discovery §8 |
| S-11 | Frontend: `SYSTEM_CALCULATED` answer display — `value` when `status = "complete"`, `reason_code` when `status = "error"` or `"data_required"` | 4D design §11; 4D-3 discovery §8 |
| S-12 | Frontend: recalculation feedback via server reload after PATCH, no client formula evaluation | 4D-3 discovery §8 |
| S-13 | Reuse all six calculation functions from `iid_assessment.calculations` verbatim | 4D design §20; IID_CALCULATION_RULES.md |
| S-14 | Reuse `resolve_substance_identity()` and `find_iid_candidates()` verbatim | 4D design §4 |
| S-15 | No new database models or migrations — `calculation_binding_identifier` used as registry key (existing CharField) | 4D-3 discovery §7; OQ-2 resolved |
| S-16 | `full_clean()` enforced on every `CalculationOutcome` update (AssessmentSnapshot defect must not recur) | 4D design §7/§18; 4D-2 implementation spec §3 |
| S-17 | `CalculationStatus` translation layer — maps engine result strings to `iig_checklist.enums.CalculationStatus` stored values | Adversarial review CR-1; 4D-3 discovery §4e |
| S-18 | `CALCULATION_BINDING_REGISTRY` — server-side Python dict mapping `calculation_binding_identifier` keys to function references and input resolvers | OQ-2 resolved; 4D-3 discovery §4c |
| S-19 | Registry validation at `ChecklistVersion` activation — unknown identifiers, missing dependencies, cycle detection | 4D-3 discovery §4c, §14 |
| S-20 | Dependency graph DAG validation — topological ordering, bounded depth, cycle rejection at activation | 4D-3 discovery §14; adversarial review CR-8 |
| S-21 | `generated_at` ISO string parsed to timezone-aware `datetime` before `CalculationOutcome.generated_at` assignment | Adversarial review CR-9; 4D-3 discovery §4f |
| S-22 | Read-only `CalculationOutcome` serialization nested in response-list/detail API; no generic PATCH endpoint | 4D-3 discovery §15 |
| S-23 | Module-level resolver functions in `iig_checklist/answer_sources.py` (OQ-1 resolved) | OQ-1 resolved; 4D-3 discovery §4b |
| S-24 | Synchronous in-transaction recalculation with defined lock order: execution → response rows → CalculationOutcome rows | OQ-3 resolved; 4D-3 discovery §4d |
| S-25 | Idempotency — unchanged inputs produce no duplicate history, no version increment, no misleading audit events | 4D-3 discovery §4a |
| S-26 | Non-overwrite rules — USER_REQUIRED, REVIEWER_CONCLUSION, and APPROVAL_METADATA never overwritten by population pass | 4D-3 discovery §4a |
| S-27 | T-10 threat coverage — status translation failure unit tests; blocked status never maps to `"complete"` | 4D-3 threat model T-10 |
| S-28 | Deterministic per-response formulation-component binding via a governed registry selector | 4D-3 spec Part 3A.2.2 |
| S-29 | Governed `AssessmentSnapshot` creation, one new immutable snapshot per calculation event | 4D-3 spec Part 3A.6 |
| S-30 | Transaction-scoped snapshot context carried in memory; no broad re-query | 4D-3 spec M4D3-SNO-007/008 |
| S-31 | Deterministic one-to-one resolver failure mapping to stored status and canonical reason code | 4D-3 spec M4D3-IFV-003 |

---

## Part B — Confirmed Out of Scope for 4D-3

| ID | Feature | Deferred to |
|---|---|---|
| X-01 | Override/deviation workflow | 4D-4 |
| X-02 | Controlled JSON/CSV export | 4D-4 |
| X-03 | SHA-256 checksum on export | 4D-4 |
| X-04 | Promotion of `_csv_safe_cell()` to common | 4D-4 |
| X-05 | `EVIDENCE_DERIVED` attachment-confirmation enforcement at submission | 4D-4 |
| X-06 | Real regulatory checklist content (any `ChecklistDefinition` template) | Regulatory-content gate (pre-4D-4) |
| X-07 | PDF/Word export | Explicitly deferred beyond 4D |
| X-08 | New calculation formulas | Not in scope for any 4D stage |
| X-09 | Electronic signatures, 21 CFR Part 11 compliance | Not in scope for any 4D stage |
| X-10 | Auto-approval based on population result | Never — structural prohibition |
| X-11 | Formula logic in the frontend | Never — backend only |
| X-12 | New or altered `iid_assessment`, `fda_data`, `formulations`, or `documents` **model classes**, and any direct model write into those apps by `iig_checklist` | See the X-12 clarification below |
| X-13 | New calculation formulas beyond the six in `iid_assessment.calculations` | Not in scope |
| X-14 | Asynchronous calculation execution | The `CalculationStatus.CALCULATING` value is reserved; 4D-3 uses synchronous computation only |
| X-15 | New database field for calculation binding JSON schema | Not required — `calculation_binding_identifier` CharField is the approved approach |
| X-16 | Arbitrary formula builder / user-authored calculation logic | Never — tenant users cannot inject executable logic |
| X-17 | Manual override of calculated values | 4D-4 |
| X-18 | Staleness-avoidance logic for existing `AssessmentSnapshot` records | Eliminated by OQ-4 live-first design |
| X-19 | New model for `REVIEW_REQUIRED` state persisted representation | Deferred to implementation spec; must use existing fields where possible |
| X-20 | Generic `PATCH`/`PUT` endpoint for `CalculationOutcome` | Never — write path is server-controlled only |
| X-21 | Automatic creation or expansion of checklist questions for every formulation component | Never in 4D-3 — dynamic question generation is out of scope |
| X-22 | New execution-to-component join model or field | Never in 4D-3 — binding is per response via the registry selector |
| X-23 | Per-component child execution model | Never in 4D-3 |
| X-24 | Aggregate multi-component calculation in a single response | Never |
| X-25 | `AssessmentSnapshot` uniqueness migration | Not in 4D-3 — determinism achieved by transaction-scoped creation |
| X-26 | Generic snapshot deduplication framework | Not in 4D-3 |

---

### X-12 clarification — governed snapshot creation

The earlier "4D-3 is a consumer only" gloss was ambiguous: it could be read as forbidding
the governed `AssessmentSnapshot` creation that Milestone 4D-3 requires. The precise
boundary is:

- 4D-3 shall **not** add new `iid_assessment` model classes, nor alter existing ones, nor
  create any migration in that app.
- `iig_checklist` shall **not** import or write `iid_assessment` model classes directly.
- 4D-3 **may** call an approved `iid_assessment` service or helper to create a governed
  `AssessmentSnapshot`, and adding that service inside `iid_assessment` is within 4D-3's
  implementation surface.
- This remains a governed consumer relationship with the `iid_assessment` domain API.
- The import direction stays one-way; no reverse import is introduced, and the existing
  import-linter contract forbidding `iid_assessment → iig_checklist` remains unchanged.

See `docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md` Part 15 (M4D3-SNP-001 … M4D3-SNP-007)
and Part 3A.6 for the normative requirements.

---

## Part C — Open Questions (all resolved)

### OQ-1: `ChecklistAnswerSource` — functions vs. class

**RESOLVED — module-level functions.**

Rationale: functions are sufficient for deterministic source resolution; dependencies can
be passed explicitly; this matches existing service-layer conventions; it avoids
unnecessary state and lifecycle complexity.

Implementation: new module `iig_checklist/answer_sources.py` with module-level
resolver functions. See `docs/MILESTONE_4D_3_DISCOVERY.md §4b`.

**Status: RESOLVED**

---

### OQ-2: `calculation_binding` binding approach

**RESOLVED — `ChecklistQuestion.calculation_binding_identifier` stores a short registry key;
server-side `CALCULATION_BINDING_REGISTRY` contains function and input mapping; no
migration required.**

The field `ChecklistQuestion.calculation_binding_identifier` is an existing
`CharField(max_length=100, blank=True)`. It stores a short, governed identifier string
(e.g. `"percentage_w_w"`) that the population pass resolves against the server-side
`CALCULATION_BINDING_REGISTRY`. It is not a `JSONField` and does not store a JSON
calculation schema. The previous discovery description of this field as a `JSONField`
was incorrect and has been removed.

The `CALCULATION_BINDING_REGISTRY` is defined in server-side version-controlled Python
code (not a database table). See `docs/MILESTONE_4D_3_DISCOVERY.md §4c` for the registry
design requirements.

No new field, no new model, no migration is required.

**Status: RESOLVED**

---

### OQ-3: Cascade recalculation — in-transaction vs. post-commit

**RESOLVED — synchronous recalculation in the same database transaction.**

Rationale: the six calculation functions are pure, fast, and Decimal-only. Transaction
duration is not a concern. Consistency is paramount.

Required lock order: `ChecklistExecution` → affected `ChecklistResponse` rows → `CalculationOutcome`
rows (in stable pk order within each tier). All writes in a single `transaction.atomic()` block.
Audit events via `transaction.on_commit()`.

See `docs/MILESTONE_4D_3_DISCOVERY.md §4d`.

**Status: RESOLVED**

---

### OQ-4: `AssessmentSnapshot` source — snapshot-first vs. live-first

**RESOLVED — live-first source resolution followed by persisted snapshot.**

At population time, the system always calls `run_preview()` against the currently active
FDA release. The result is frozen as an `AssessmentSnapshot` (reusing an existing exact
match for this `(FormulationComponent, active_release)` tuple if one exists). Any
`AssessmentSnapshot` lookup must filter by `tenant = execution.tenant`. Historical
approved and terminal executions are never automatically recalculated.

See `docs/MILESTONE_4D_3_DISCOVERY.md §6`.

**Status: RESOLVED**

---

## Part D — Dependency Map

```
4D-3 depends on (must be present, unchanged):
  iig_checklist (4D-1, 4D-2)
    ChecklistDefinition / ChecklistVersion / ChecklistSection / ChecklistQuestion
    ChecklistExecution / ChecklistResponse / CalculationOutcome (4D-2 models)
    execution_transitions.py / create_execution() / transition_execution() /
      enter_reviewer_conclusion() services
    ChecklistResponseUpdateView.patch() -- the current ordinary-response write path;
      no enter_response() service exists (4D-3 introduces update_checklist_response())
    applicability.validate_condition_json() / field_registry.py (4D-1)
    iig_checklist.enums.CalculationStatus (4 values: data_required, calculating, complete, error)
  iid_assessment (4A-4C)
    calculations.py (six functions, CalculationResult, CalculationStatus engine class)
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
  deviation path assumes CalculationOutcome.status and reason_code are set
```

---

## Part E — Acceptance Criteria (for implementation specification)

The 4D-3 implementation specification may be written when:

1. OQ-1 through OQ-4 are formally resolved — **DONE** (see Part C above).
2. The `CalculationStatus` translation layer (S-17) is specified exhaustively — the
   implementation spec must include the full mapping table from §4e of the discovery
   document and must include tests for every engine status string.
3. The `CALCULATION_BINDING_REGISTRY` design (S-18) satisfies all requirements in
   `docs/MILESTONE_4D_3_DISCOVERY.md §4c`.
4. No new database models or migrations are required (confirmed for the registry-key
   approach — S-15 satisfied).
5. A human reviewer with domain authority has read this register and the discovery
   document and confirmed scope boundaries.
6. No item from Part B (Out of Scope) has been silently added to any proposed
   implementation description.
7. The second adversarial discovery review passes with no Critical or Major findings.
