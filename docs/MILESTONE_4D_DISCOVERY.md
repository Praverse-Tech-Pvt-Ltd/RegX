# Milestone 4D Discovery and Design — Automated IIG/IID Checklist Execution

**Status: DESIGN ONLY. No code in this milestone. Not approved for implementation.**

This document is the discovery and design gate for Milestone 4D, requested
after the Milestone 4A–4C merge (`d9d0d13519a154bb2c0558a0aed6bbac313aa587`,
tag `regx-fda-iid-foundation-v0.4.0`) and closure-documentation merge
(`f49f4b467a12935db7103157f72ae1b634307a54`). It proposes a data model,
execution lifecycle, and API/frontend shape for an **Inactive Ingredient
Guidance (IIG) checklist execution engine** that sits on top of the
existing `fda_data`, `formulations`, and `iid_assessment` foundations —
it does not re-derive matching, unit conversion, or calculation logic;
it *consumes* `iid_assessment`'s existing `run_preview()` /
`AssessmentSnapshot` outputs as one input source among several.

Every design decision below is written to be reviewed and revised before
any implementation branch is opened. Where a decision is genuinely open
(more than one reasonable answer), it is marked **OPEN QUESTION** rather
than silently resolved.

---

## 1. Checklist definition and versioning

A **checklist definition** is a template, analogous in spirit to
`templates_registry.TemplateVersion` (Milestone 3) but purpose-built for
IIG questions rather than generic regulatory template content. It is
**not** the same table as `templates_registry` — IIG checklists have a
different question shape (typed, calculation-linked, data-source-aware)
that would force `templates_registry.TemplateItem` into an awkward
generic-JSON shape if reused. Sharing the *lifecycle* pattern (draft →
review → approve → activate → supersede/retire) is appropriate; sharing
the *table* is not.

Proposed models (new app: `iig_checklist`):

```
ChecklistDefinition
  public_id, tenant=NULL (platform-level, like fda_data — a checklist
    definition is not tenant content, only its executions are)
  code                      e.g. "iig-oral-solid-v1"
  title
  version_number             int, monotonic per code
  status                     draft | under_review | approved | active |
                              superseded | retired
  created_by, submitted_by, reviewer, approved_by  (same provenance
    pattern as fda_data mappings — HR-03 taught us not to collapse these)
  superseded_by (self-FK, nullable)
  effective_guidance_reference  free text: which FDA IIG guidance
    document/version this checklist encodes (never the guidance content
    itself — see §20 exclusions)

ChecklistSection
  checklist_definition FK
  code, title, display_order

ChecklistQuestion
  section FK
  code                        stable identifier, immutable once approved
  prompt_text
  data_source_type            see §3
  answer_type                 boolean | decimal | text | choice |
                              attachment_reference
  calculation_binding         nullable FK to a named calculation
                              (see §9) when data_source_type = SYSTEM_CALCULATED
  required                    bool
  display_order
```

Versioning rule: identical to `templates_registry` — a `ChecklistDefinition`
row is immutable once `status == approved`; a correction creates a new
`version_number` under the same `code`, never an in-place edit. This is
the same rule already enforced on `TemplateVersion` and on
`SubstanceSynonymMapping` once `APPROVED` — precedent, not a new pattern.

**OPEN QUESTION:** should `ChecklistDefinition` live in a new `iig_checklist`
app, or as new models inside `iid_assessment`? Recommendation: new app.
`iid_assessment` is a calculation/matching *engine*; a checklist is a
*governed content type* with its own review lifecycle, closer in kind to
`templates_registry`. Mixing them would blur the import-linter boundary
that currently keeps `fda_data` decoupled from tenant-scoped apps.

---

## 2. Checklist sections and questions

Covered by the model shapes above. The section/question split mirrors
`templates_registry.TemplateSection`/`TemplateItem` deliberately — same
review pattern (a reviewer reads section-by-section), same reordering
mechanism (`display_order`, no silent renumbering).

A worked example section for the paracetamol/acetaminophen case (§19):

```
Section: "Excipient Identity and IID Precedent"
  Q1  "Is the excipient's identity resolved to an approved IIDIngredient
       or synonym mapping?"                         [SYSTEM_CALCULATED]
  Q2  "Does the proposed route match the IID precedent route exactly?"
                                                      [SYSTEM_CALCULATED]
  Q3  "Does the proposed dosage form match exactly?"  [SYSTEM_CALCULATED]
  Q4  "Proposed quantity per dosage unit and unit"     [USER_REQUIRED]
  Q5  "Calculated % w/w for this excipient"            [SYSTEM_CALCULATED]
  Q6  "Calculated daily exposure to this excipient"    [SYSTEM_CALCULATED]
  Q7  "Does daily exposure exceed the IID maximum daily exposure (MDE)?"
                                                      [SYSTEM_CALCULATED]
  Q8  "If exceeded: reviewer justification for proceeding"
                                                      [REVIEWER_CONFIRMED,
                                                       required only when
                                                       Q7 = true]
```

---

## 3. Question data-source classification

Every question carries exactly one `data_source_type`:

| Value | Meaning | Who can write the answer |
|---|---|---|
| `FDA_DERIVED_DEFAULT` | Pre-filled from an FDA-governed source (IID precedent, Orange Book record, approved mapping) — always labeled with `ProvenanceLabel(kind="FDA_SOURCE")`, same convention as the rest of the codebase | System writes; a reviewer may override with a required reason (see §12) |
| `USER_REQUIRED` | No FDA/system source exists; the tenant user must supply the value (e.g. proposed quantity per dosage unit) | User only |
| `SYSTEM_CALCULATED` | Derived deterministically from other answers via a named calculation (see §9) | System only — never directly editable; changes only when an upstream input answer changes |
| `REVIEWER_CONFIRMED` | A conclusion that requires a human regulatory judgment call even though inputs are known (e.g. "is this deviation acceptable") | Reviewer only, never system-generated |

This four-way split is the single most load-bearing design decision in
this document: it is what makes "no automatic safety or approval
conclusion" structurally true rather than a policy promise. Any question
whose answer_type could plausibly encode a safety/approval verdict
(`"is this excipient acceptable for use"`, `"is this formulation approved"`)
**must** be `REVIEWER_CONFIRMED`, never `SYSTEM_CALCULATED` — mirroring
`PrecedentDecisionStatus.__post_init__`'s existing hard rule that no
"SAFE"/"FDA APPROVED" status can be constructed without a
"not-an-automatic-determination" qualifier.

---

## 4. FDA-derived defaults

`FDA_DERIVED_DEFAULT` questions are populated by a `ChecklistAnswerSource`
resolver that calls **existing, unmodified** services:
- `fda_data.substance_matching.resolve_substance_identity()` for ingredient
  identity questions,
- `iid_assessment.matching.find_iid_candidates()` for precedent-route/
  dosage-form questions,
- `formulations` model fields directly for user-entered formulation data
  that happens to already exist (e.g. `FormulationComponent.quantity_unit`).

No new FDA-data-reading logic is introduced by Milestone 4D — it is
strictly a consumer of the Milestone 4A–4C read APIs/services. This keeps
the import-linter contract (`fda-data-is-platform-level-not-coupled-to-
tenant-formulations`) intact: `iig_checklist` may import from `fda_data`
and `iid_assessment` read-side services, but `fda_data` must never import
`iig_checklist`.

---

## 5. User-required inputs

Stored on `ChecklistResponse` (see §7) as a typed value plus
`entered_by`/`entered_at`. A `USER_REQUIRED` question left blank blocks
checklist submission for review (see §8) — it is never silently defaulted
to zero, `None`-as-pass, or an inherited prior-execution value.

---

## 6. System-calculated answers

A `SYSTEM_CALCULATED` answer is **never stored as a bare value** — it is
stored as a `CalculationOutcome` (see §9) containing the value, its
`CalculationStatus` (reusing `iid_assessment.calculations.CalculationStatus`
verbatim: `OK`, `ROUTE_MISMATCH`, `UNIT_MISMATCH`, `FDA_VALUE_UNAVAILABLE`,
`DATA_REQUIRED`, `NOT_COMPARABLE`), and which upstream answers/records fed
it. This mirrors `AssessmentSnapshot` freezing calculation provenance —
same pattern, applied to checklist questions instead of a single preview.

---

## 7. Reviewer-confirmed answers

```
ChecklistResponse
  execution FK (see §8)
  question FK
  data_source_type_snapshot   frozen at answer time (defends against a
                              question definition being edited later)
  raw_value                   JSON — shape depends on answer_type
  calculation_outcome          nullable FK, populated only when
                              data_source_type = SYSTEM_CALCULATED
  entered_by, entered_at
  confirmed_by, confirmed_at   set only for REVIEWER_CONFIRMED and for
                              FDA_DERIVED_DEFAULT overrides (§12) — never
                              set for plain USER_REQUIRED/SYSTEM_CALCULATED
                              answers, to avoid a reviewer-confirmation
                              audit trail that doesn't actually reflect
                              a reviewer decision
  override_reason              nullable text, required whenever
                              confirmed_by differs from what the system
                              would have derived
```

A `REVIEWER_CONFIRMED` answer with no `confirmed_by` blocks submission —
same "required field enforced at the state-transition boundary, not just
form validation" pattern as `SubstanceMappingProposalSerializer` requiring
`fda_data.import`/`fda_data.review` permission rather than relying on
frontend gating alone.

---

## 8. Checklist execution lifecycle

```
ChecklistExecution
  public_id, tenant FK, formulation_version FK (the formulation being
    assessed), checklist_definition FK (pinned to a specific approved
    version — never "latest", so a completed execution's meaning never
    silently drifts when the checklist template is revised)
  status: draft → submitted_for_review → returned → approved → rejected
  created_by, submitted_by, reviewer, approved_by, rejected_by,
    returned_by   — same six-actor provenance split as HR-03, applied
    from day one rather than retrofitted
```

Transition table (same pattern as `fda_data/mapping_transitions.py` —
**one shared authoritative table, not per-view checks**):

| Action | Legal from | Resulting status |
|---|---|---|
| `submit_review` | `draft`, `returned` | `submitted_for_review` |
| `approve` | `submitted_for_review` | `approved` |
| `reject` | `draft`, `submitted_for_review` | `rejected` |
| `return` | `submitted_for_review` | `returned` |

`approve` requires every `required` question to have a non-null response,
and every `SYSTEM_CALCULATED` response whose `CalculationOutcome.status
!= OK` to have an accompanying `REVIEWER_CONFIRMED` justification answer
in the same section (see the Q7/Q8 pairing in §2). `approved` and
`rejected` are terminal, identical in spirit to `SubstanceSynonymMapping`.

Segregation of duties: the actor who `submitted_review` cannot `approve`
their own execution — same self-approval check already proven in
`_MappingActionViewBase`, reused verbatim rather than reinvented.

---

## 9. Checklist response storage and calculation-to-question mapping

`CalculationOutcome` wraps exactly one call into the **existing**
`iid_assessment.calculations` module — it does not duplicate formula
logic:

```
CalculationOutcome
  public_id
  calculation_name       one of: percentage_w_w | daily_exposure |
                          percentage_of_potency | difference_from_potency |
                          percentage_of_mde | difference_from_mde
                          (exact 1:1 match to the six functions already in
                          iid_assessment/calculations.py — no new formulas)
  status                 iid_assessment.calculations.CalculationStatus value
  value                   Decimal, nullable
  unit
  source_assessment_snapshot   nullable FK to iid_assessment.AssessmentSnapshot
                          — when a checklist question's answer is exactly
                          "what did the IID assessment preview say," it
                          points at the frozen snapshot rather than
                          re-running the calculation, so a later formulation
                          edit cannot retroactively change a completed
                          checklist answer (same immutability guarantee
                          AssessmentSnapshot already provides for the
                          preview/assessment feature)
```

`ChecklistQuestion.calculation_binding` declares which `calculation_name`
a `SYSTEM_CALCULATED` question uses and which other question codes supply
its inputs (e.g. Q5 "% w/w" binds to `percentage_w_w`, sourced from Q4's
`USER_REQUIRED` quantity plus the formulation's
`total_dosage_unit_weight`). This binding is data (a JSON mapping table
row), not code — adding a new checklist question that reuses an existing
calculation requires no deployment, only a new `ChecklistQuestion` row in
a new (or revised) `ChecklistDefinition` version.

---

## 10. Automatic draft-answer generation

When a `ChecklistExecution` is created, the system performs one pass:
- every `FDA_DERIVED_DEFAULT` question is populated from the current
  governed FDA data (§4);
- every `SYSTEM_CALCULATED` question whose inputs are already answered
  (because they're `FDA_DERIVED_DEFAULT` or already-supplied
  `USER_REQUIRED` from a prior formulation-version step) is computed;
- every other question is left blank.

This is explicitly a **draft-generation pass, not an auto-completion or
auto-approval pass** — the resulting execution is always created in
`status=draft`, never `approved`, and a human must explicitly
`submit_review` and a *different* human must explicitly `approve`,
identical in spirit to "no mapping is ever auto-approved" and "no release
is ever auto-activated," which are two of the oldest, most consistently
enforced rules in this codebase (see `FDA_DATA_GOVERNANCE.md` and
`FDA_TERMINOLOGY_MAPPING.md`).

---

## 11. Blocked and not-comparable states

Reuses `iid_assessment.calculations.CalculationStatus` and
`iid_assessment.matching.MatchStatus` verbatim inside
`CalculationOutcome.status` — **no new status vocabulary is introduced.**
A `SYSTEM_CALCULATED` question with `status != OK` renders in the
frontend the same way `iid-assessments/preview` already renders a blocked
calculation: the reason code, not a fabricated value (`FDA_VALUE_UNAVAILABLE`
instead of `0`, `DATA_REQUIRED` instead of skipping the field silently).

A blocked/not-comparable `SYSTEM_CALCULATED` answer does **not** by itself
block checklist approval — it forces the paired `REVIEWER_CONFIRMED`
justification question (§2, §8) to become required, so a human explicitly
records why the execution is proceeding despite the gap, rather than the
checklist being unable to reach a conclusion at all for a legitimately
incomplete-data scenario (e.g. an ingredient with `FDA_VALUE_UNAVAILABLE`
MDE, which is common and not itself disqualifying).

---

## 12. Deviations and overrides

Any `FDA_DERIVED_DEFAULT` answer may be overridden by a reviewer, but:
- `override_reason` is required (enforced at the transition boundary, not
  just serializer validation — same "structured 400, not a client-side-
  only check" principle as HR-01's transition table);
- the original system-derived value is preserved alongside the override
  (`raw_value` holds the override; a new `system_derived_value` snapshot
  field holds what the system originally produced) so an audit can always
  see both;
- overriding an `FDA_DERIVED_DEFAULT` answer emits a dedicated audit event
  (`iig_checklist.answer.overridden`) distinct from the plain
  `answer.entered` event, carrying old/new value, actor, and reason —
  matching the audit-completeness bar `templates_registry`'s Milestone 3
  remediation already established (full decision detail in every
  governance-relevant audit event, not just a status field).

**OPEN QUESTION:** should an override be allowed on a `SYSTEM_CALCULATED`
answer (not just `FDA_DERIVED_DEFAULT`)? Recommendation: no — a
calculation is arithmetic on already-confirmed inputs; if a reviewer
disagrees with a calculated result, the correct action is to challenge
the *input* answer (which is either `USER_REQUIRED` and editable, or
`FDA_DERIVED_DEFAULT` and overridable), not to hand-edit a derived number.
Allowing direct override of calculated values would reopen exactly the
"can a human silently override a formula result" gap this system is
designed to prevent.

---

## 13. Reviewer conclusion

A `ChecklistExecution`'s `approve` action requires, in addition to the
per-question completeness checks in §8, a top-level
`reviewer_conclusion_note` (free text, required, min length enforced) —
the reviewer's own summary statement. This note is stored verbatim and is
**never** used to derive or influence any system status; it is a human
record attached to a human decision, read-only to the system.

---

## 14. Approval workflow

Fully specified by §8's transition table. No additional workflow layer is
needed beyond what `fda_data`/`templates_registry` already established:
submit → review → approve/reject/return, segregation of duties,
structured 400 on illegal transitions, no bypass through an alternate
endpoint (one shared `_ChecklistActionViewBase`, mirroring
`_MappingActionViewBase`'s proven shape).

---

## 15. Evidence attachments

`ChecklistResponse.attachment_reference` (for `answer_type =
attachment_reference` questions) points at a `documents`-app-managed file
via `storage_key` indirection — **reusing the existing `documents` app's
storage/malware-scan/tenant-isolation machinery rather than building a
second file-upload path.** An attachment is subject to the same
malware-scan gate already enforced for all document uploads (Milestone 2)
before it can be referenced by an approved checklist response.

**OPEN QUESTION:** does an evidence attachment need its own governance
lifecycle (e.g. can it be superseded/retracted independently of the
checklist execution), or is it sufficient that it's immutable once the
parent `ChecklistExecution` reaches `approved`? Recommendation: the
latter — treat it as frozen the moment its parent response is written
into an approved execution, avoiding a second independent lifecycle to
reason about.

---

## 16. Audit trail

New `IigChecklistEvent` event types, following the exact naming and
payload-safety conventions already established in
`fda_data/audit_events.py` and `templates_registry`'s remediation
(HR-03/full decision detail):

```
iig_checklist.definition.created / .submitted_for_review / .approved /
  .activated / .superseded / .retired
iig_checklist.execution.created / .submitted_for_review / .approved /
  .rejected / .returned
iig_checklist.answer.entered / .overridden / .confirmed
```

Every event carries: execution/definition public ID, actor, before/after
status (for lifecycle events), a correlation ID (reusing the existing
`correlation_id` convention from `fda_data`/`documents`), and safe
metadata only — never a raw attachment file, never a full formulation
record dump. This mirrors the `SUBSTANCE_MAPPING_CANDIDATE_CREATED`
event's "safe metadata" bar exactly (mapping public ID, method, actor —
never the raw FDA row).

---

## 17. Controlled exports

A completed (`approved`) `ChecklistExecution` can be exported as a
read-only JSON or CSV report, following the same neutralization pattern
already shipped for `templates_registry`'s reconciliation CSV export
(Milestone 3's Major-finding remediation): every cell is passed through
the existing formula-injection-safe CSV cell writer before serialization.
No new CSV-safety code is written — the existing `csv_safe_cell()`-style
helper from `templates_registry` is reused or promoted to a shared
utility if `iig_checklist` needs it and `templates_registry` doesn't want
a direct dependency (**OPEN QUESTION:** promote to a `common` shared
utility module now, or duplicate the ~10-line function and accept minor
duplication until a third consumer appears? Recommendation: promote to
`common` — this is exactly the "rule of three" boundary, and CSV-injection
safety is exactly the kind of logic that should never be duplicated by
hand).

Export access requires the same `fda_data.export_reconciliation`-style
dedicated permission pattern (a new
`iig_checklist.export_checklist` permission, not implicit from `view`),
and every export emits `iig_checklist.execution.exported` with a full
decision-detail payload — matching the audit-completeness bar Milestone
3's remediation set for `RECONCILIATION_EXPORTED`.

---

## 18. Reproducibility

A completed execution must be fully reconstructable from its stored
`ChecklistResponse` rows plus the pinned `checklist_definition` version —
it must **never** need to re-query live FDA/formulation data to redisplay
correctly, because live data can change after approval (a release can be
superseded, a mapping can be corrected). This is the same reproducibility
guarantee `AssessmentSnapshot` already provides for a single preview,
extended to a whole checklist:

- `ChecklistResponse.calculation_outcome` freezes the calculated value
  and its source `AssessmentSnapshot` public ID (§9);
- `ChecklistResponse.data_source_type_snapshot` freezes the question's
  data-source classification at answer time, so a later
  `ChecklistDefinition` revision changing a question from
  `FDA_DERIVED_DEFAULT` to `USER_REQUIRED` cannot retroactively reclassify
  an already-approved answer's provenance;
- `checklist_definition` FK is to a specific `version_number`, never
  "latest."

---

## 19. Worked example — paracetamol (acetaminophen)

Concrete walk-through to sanity-check the model against a real ingredient
already used as a fixture-naming convention elsewhere in this repo's
tests (`Synthetic Proposal Ingredient` fixtures reference
acetaminophen-shaped data).

1. A tenant creates `ProductDevelopmentRecord` "Acetaminophen ER Tablet"
   and a `FormulationVersion` with `total_dosage_unit_weight=650mg`,
   `maximum_dosage_units_per_day=6`.
2. A `FormulationComponent` row: `ingredient_name="Acetaminophen"`,
   `quantity_per_dosage_unit=500mg`.
3. A reviewer starts a `ChecklistExecution` against the approved
   "iig-oral-solid-v1" `ChecklistDefinition`, pinned to that formulation
   version.
4. Draft generation (§10): Q1 (`FDA_DERIVED_DEFAULT`) resolves via
   `resolve_substance_identity(normalized_name="ACETAMINOPHEN")` → finds
   an `APPROVED` `SubstanceSynonymMapping` (or a direct `IIDIngredient`
   exact match) → `EXACT_MATCH`. Q2/Q3 (`FDA_DERIVED_DEFAULT`) compare
   the proposed oral/tablet route+dosage-form against the matched IID
   precedent record → both match. Q4 (`USER_REQUIRED`) is left blank —
   it duplicates `FormulationComponent.quantity_per_dosage_unit`, so in
   practice the frontend pre-populates it from that field as a
   convenience (still user-editable, still not FDA-derived).
5. Q5 (`SYSTEM_CALCULATED`, `percentage_w_w`) computes
   `500mg / 650mg = 76.9%` — status `OK`.
6. Q6 (`SYSTEM_CALCULATED`, `daily_exposure`) computes
   `500mg × 6 = 3000mg/day` — status `OK`.
7. Q7 (`SYSTEM_CALCULATED`, `difference_from_mde`) compares 3000mg
   against the IID precedent's `iid_mde` for acetaminophen at this
   route/dosage-form. If the precedent's MDE field is genuinely absent in
   the source data, this returns `FDA_VALUE_UNAVAILABLE` (never a
   fabricated pass) — and Q8 becomes required: a `REVIEWER_CONFIRMED`
   justification for proceeding without an MDE comparison, exactly the
   §11 blocked-state handling.
8. The reviewer completes Q8, adds the top-level `reviewer_conclusion_note`
   (§13), and calls `submit_review`. A different, VP-permissioned actor
   reviews and calls `approve`.
9. At no point does any system output read "acetaminophen is safe at this
   dose" or "this formulation is FDA approved" — the closest the system
   ever states is `PASS_WITH_IID_PRECEDENT` (reused verbatim from
   `iid_assessment.decisions.PrecedentDecisionStatus`) with its existing
   mandatory "not an automatic safety determination" qualifier, applied
   identically inside the checklist context.

---

## 20. What this milestone explicitly does not do

- **No automatic safety or approval conclusion.** `ChecklistExecution`
  has no `status` value meaning "safe" or "approved-for-use" — only
  `approved` in the workflow-governance sense (this checklist execution
  record itself was reviewed and signed off), identical in spirit to how
  `FDADataSourceRelease.status = approved` never means "this data is
  scientifically correct," only "this import was reviewed."
- No new calculation formulas — all six from `iid_assessment.calculations`
  are reused unmodified.
- No new matching logic — `resolve_substance_identity()` and
  `find_iid_candidates()` are reused unmodified.
- No FDA guidance-document *content* is stored or reproduced — only a
  free-text reference to which guidance version a checklist encodes
  (matching the existing rule that no 483/warning-letter content is ever
  baked into governed-domain data).
- No real FDA data ingestion, no real client formulation data, no
  Milestone-4D implementation code. This document defines the shape only.

---

## Summary of new components (implementation-phase scope, not built here)

- New Django app `iig_checklist`: `ChecklistDefinition`, `ChecklistSection`,
  `ChecklistQuestion`, `ChecklistExecution`, `ChecklistResponse`,
  `CalculationOutcome`.
- A `checklist_transitions.py` transition table, structurally identical
  to `fda_data/mapping_transitions.py`.
- A `_ChecklistActionViewBase`, structurally identical to
  `_MappingActionViewBase`.
- New audit events (§16), new permissions
  (`iig_checklist.review`/`.approve`/`.export_checklist`, following the
  existing `fda_data` permission-codename convention).
- Frontend: a checklist execution screen (section-by-section, matching
  the existing mapping-review page's confirmation-dialog pattern), an
  evidence-attachment upload reusing the `documents` upload component,
  and a read-only export view.
- Import-linter contract addition: `iig_checklist` may depend on
  `fda_data`, `formulations`, `iid_assessment`, and `documents` (read
  paths only); none of those four may depend back on `iig_checklist`.

## Open questions requiring a decision before implementation

1. New app vs. extending `iid_assessment` for `ChecklistDefinition` (§1) — recommend new app.
2. Whether evidence attachments need an independent lifecycle (§15) — recommend no, freeze with parent execution.
3. Promote CSV-safety helper to `common` now vs. duplicate (§17) — recommend promote.
4. Exact set of built-in `ChecklistDefinition` templates to ship (oral solid, oral liquid, parenteral, topical?) — not addressed in this document, needs a separate content-scoping conversation with whoever owns the IIG guidance interpretation.
5. Whether a `ChecklistExecution` can span multiple `FormulationVersion`s (e.g. one checklist per excipient across a whole formulation) or is strictly one-per-version — this document assumes one-per-version; a multi-version model would change §8's foreign key shape materially.
