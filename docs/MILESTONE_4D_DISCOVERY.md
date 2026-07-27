# Milestone 4D Discovery and Design — Automated IIG/IID Checklist Execution

**Status: DESIGN ONLY. No code in this milestone. Not approved for implementation.**

**Revision note:** this document is the **revised** version, produced
after a first focused design-review gate (PR #7, first pass) returned
**FAIL** with a set of material, correctable design gaps — not a rejection
of the underlying architecture, but a set of omissions and
under-specifications the review found by independently grounding this
document's reuse claims against the actual `regx-main` source rather than
taking them on faith. Every gap the review identified is closed or
explicitly resolved below, each marked with which review finding it
closes (`DR-01` through `DR-08`). The full finding-by-finding traceability
— original gap, root cause, correction made, and closure status — is
recorded separately in
[MILESTONE_4D_DESIGN_REMEDIATION.md](MILESTONE_4D_DESIGN_REMEDIATION.md),
matching the same traceability-table convention already established for
[HUMAN_REVIEW_PR5_REMEDIATION.md](HUMAN_REVIEW_PR5_REMEDIATION.md). This
document is not rewritten from scratch — it is the same design, corrected.

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
any implementation branch is opened. Where a decision remains genuinely
open (more than one reasonable answer, and not resolvable by engineering
judgment alone), it is marked **DEFERRED**. Where a decision *was* open in
the first design-review pass and has since been resolved, it is marked
**DECIDED**, with the reasoning kept alongside it rather than silently
removed.

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
  help_text                   optional, supplementary guidance shown
                              alongside the question — never a substitute
                              for the prompt_text itself
  data_source_type            see §3 (five values, not four — see below)
  answer_type                 see §6a — expanded from the original four-value
                              sketch; boolean alone is not expressive enough
                              (see below)
  allowed_units                nullable list, only meaningful when
                              answer_type = decimal/integer with a physical
                              quantity (e.g. ["milligram", "gram"]) —
                              reuses the existing ControlledUnit vocabulary,
                              never a free-text unit string
  evidence_requirement        none | optional | required — distinct from
                              answer_type = attachment_reference: a
                              decimal/text question can still *require*
                              supporting evidence without itself being an
                              attachment question (see §15)
  applicability_rule          nullable, structured JSON condition (see §9a)
                              — when present and evaluates false, the
                              question becomes NOT_APPLICABLE (§3a) rather
                              than required
  calculation_binding         nullable FK to a named calculation
                              (see §9) when data_source_type = SYSTEM_CALCULATED
  criticality                 informational | standard | critical — drives
                              which escalation_rule applies; never changes
                              who may answer/confirm the question (that is
                              governed only by data_source_type)
  escalation_rule              nullable, references one of a small
                              allow-listed set of escalation identifiers
                              (e.g. "requires_vp_conclusion_note") —  never
                              a free-text rule, for the same reason
                              applicability_rule is never a free-text
                              expression (§9a)
  regulatory_reference         free text: which section/paragraph of the
                              referenced IIG guidance this question encodes
                              (distinct from ChecklistDefinition's
                              guidance-version reference — this is
                              question-level, that is checklist-level)
  required                    bool
  display_order
```

Versioning rule: identical to `templates_registry` — a `ChecklistDefinition`
row is immutable once `status == approved`; a correction creates a new
`version_number` under the same `code`, never an in-place edit. This is
the same rule already enforced on `TemplateVersion` and on
`SubstanceSynonymMapping` once `APPROVED` — precedent, not a new pattern.

**DECIDED (was OPEN QUESTION 1):** `ChecklistDefinition` lives in a new
`iig_checklist` app, not as new models inside `iid_assessment`.
`iid_assessment` is a calculation/matching *engine*; a checklist is a
*governed content type* with its own review lifecycle, closer in kind to
`templates_registry`. Mixing them would blur the import-linter boundary
that currently keeps `fda_data` decoupled from tenant-scoped apps. This
decision was open in the first design-review pass; it is resolved here
per the review's recommendation (see
[MILESTONE_4D_DESIGN_REMEDIATION.md](MILESTONE_4D_DESIGN_REMEDIATION.md),
finding DR-06).

### 1a. `ChecklistDefinition` lifecycle and activation (new — closes DR-02)

The first design-review pass found that this document specified a
`status` field with six values (`draft | under_review | approved | active
| superseded | retired`) but never wrote the transition table governing
it — an omission of exactly the kind HR-01 (Milestone 4A–4C's Critical
finding) taught this codebase to treat as unacceptable. It is closed here
by mirroring `fda_data.FDADataSourceRelease`'s release-governance pattern
exactly, since a `ChecklistDefinition` is structurally the same kind of
object: platform-governed reference content that must never silently
become authoritative.

Transition table (own table, distinct from — and simpler than —
`ChecklistExecution`'s table in §8; a definition's lifecycle governs
*content authoring*, an execution's lifecycle governs *one tenant's use
of that content*):

| Action | Legal from | Resulting status |
|---|---|---|
| `submit_review` | `draft` | `under_review` |
| `approve` | `under_review` | `approved` |
| `reject` | `draft`, `under_review` | `retired` |
| `activate` | `approved` | `active` |
| `supersede` | `active` | `superseded` |
| `retire` | `draft`, `approved`, `superseded` | `retired` |

- `approve` alone does **not** make a definition usable by new
  executions — a separate `activate` action (requiring
  `iig_checklist.approve`, the same VP-level permission as `approve`
  itself, not a lesser one) is required, identical to
  `FDADataSourceRelease.status == approved` not implying `active`.
- A DB-level `UniqueConstraint` enforces **at most one `active`
  `ChecklistDefinition` per `code`** at any time, identical in mechanism
  to `unique_active_release_per_dataset_type` on
  `FDADataSourceRelease`. Activating a new version of an already-active
  `code` must atomically supersede the prior active version in the same
  transaction — never a window where two versions of the same checklist
  are simultaneously active.
- `approved`/`active`/`superseded`/`retired` are all terminal with
  respect to content mutation: the row's questions/sections cannot change
  under any of these statuses. Only `draft` and `under_review` rows are
  mutable, and only by the segregation-of-duties rules already proven for
  `fda_data` mappings (the actor who `submit_review`s cannot `approve`).
- New executions always pin to the `active` version at the moment of
  creation (§8) — never to `approved`-but-not-yet-`active`, and never to
  `latest` by any other definition of "latest."

---

## 2. Checklist sections and questions

Covered by the model shapes above. The section/question split mirrors
`templates_registry.TemplateSection`/`TemplateItem` deliberately — same
review pattern (a reviewer reads section-by-section), same reordering
mechanism (`display_order`, no silent renumbering).

A worked example section for the paracetamol/acetaminophen case (§19),
updated to show the full five-way classification (§3), the expanded
answer-type set (§6a), and `applicability_rule`/`evidence_requirement`
usage rather than ad hoc prose ("required only when..."):

```
Section: "Excipient Identity and IID Precedent"
  Q1  "Is the excipient's identity resolved to an approved IIDIngredient
       or synonym mapping?"           [SYSTEM_CALCULATED, yes_no_na]
  Q2  "Does the proposed route match the IID precedent route exactly?"
                                       [SYSTEM_CALCULATED, yes_no_na]
  Q3  "Does the proposed dosage form match exactly?"
                                       [SYSTEM_CALCULATED, yes_no_na]
  Q4  "Proposed quantity per dosage unit"
                                       [USER_REQUIRED, decimal,
                                        allowed_units=["milligram"],
                                        prefill_source=formulation_component
                                        — see §3a]
  Q5  "Calculated % w/w for this excipient"
                                       [SYSTEM_CALCULATED, decimal]
  Q6  "Calculated daily exposure to this excipient"
                                       [SYSTEM_CALCULATED, decimal]
  Q7  "Comparison of daily exposure to the IID maximum daily exposure
       (MDE)"                         [SYSTEM_CALCULATED, decimal;
                                        applicability_rule: only applicable
                                        when Q1 resolved to a matched IID
                                        precedent at all (i.e. Q1's
                                        CalculationOutcome.status == OK) —
                                        otherwise NOT_APPLICABLE (§3a),
                                        since there is no precedent to
                                        compare against. Note this is
                                        distinct from the matched
                                        precedent simply lacking an MDE
                                        value, which is a *blocked
                                        calculation*
                                        (status=FDA_VALUE_UNAVAILABLE,
                                        §11), not a not-applicable
                                        question — the comparison is
                                        still meaningful to attempt, the
                                        source data just doesn't support
                                        it this time]
  Q8  "If MDE is unavailable or exceeded: reviewer justification for
       proceeding"                    [REVIEWER_CONFIRMED, long_narrative;
                                        applicability_rule: required only
                                        when Q7's CalculationOutcome.status
                                        != OK, or Q7's value indicates an
                                        exceedance — evaluated via the
                                        allow-listed rule mechanism, §9a,
                                        never free-text logic]
  Q9  "Certificate of analysis confirming excipient grade"
                                       [EVIDENCE_DERIVED, attachment_reference,
                                        evidence_requirement=required —
                                        see §3a, §15]
```

---

## 3. Question data-source classification

Every question carries exactly one `data_source_type`. The first
design-review pass found the original four-way split incomplete — it
could not represent a value whose authority comes from an attached
evidence document rather than a bare user assertion (finding DR-01). A
fifth value, `EVIDENCE_DERIVED`, is added below to close that gap.

| Value | Meaning | Who can write the answer |
|---|---|---|
| `FDA_DERIVED_DEFAULT` | Pre-filled from an FDA-governed source (IID precedent, Orange Book record, approved mapping) — always labeled with `ProvenanceLabel(kind="FDA_SOURCE")`, same convention as the rest of the codebase | System writes; a reviewer may override with a required reason (see §12) |
| `USER_REQUIRED` | No FDA/system source exists; the tenant user must supply the value (e.g. proposed quantity per dosage unit) | User only |
| `EVIDENCE_DERIVED` | The value's authority comes from an attached evidence document (e.g. a vendor certificate-of-analysis number the user transcribes) — distinct from `USER_REQUIRED` because the answer is only as trustworthy as its cited attachment, and `evidence_requirement` on this question type is always `required`, never `optional` | User enters the value **and** must attach supporting evidence (§15) before the answer counts as complete |
| `SYSTEM_CALCULATED` | Derived deterministically from other answers via a named calculation (see §9) | System only — never directly editable; changes only when an upstream input answer changes |
| `REVIEWER_CONFIRMED` | A conclusion that requires a human regulatory judgment call even though inputs are known (e.g. "is this deviation acceptable") | Reviewer only, never system-generated |

This five-way split is the single most load-bearing design decision in
this document: it is what makes "no automatic safety or approval
conclusion" structurally true rather than a policy promise. Any question
whose answer_type could plausibly encode a safety/approval verdict
(`"is this excipient acceptable for use"`, `"is this formulation approved"`)
**must** be `REVIEWER_CONFIRMED`, never `SYSTEM_CALCULATED` — mirroring
`PrecedentDecisionStatus.__post_init__`'s existing hard rule that no
"SAFE"/"FDA APPROVED" status can be constructed without a
"not-an-automatic-determination" qualifier.

### 3a. Provenance sub-attributes and NOT_APPLICABLE (closes DR-01, DR-03)

Two further gaps the first design-review pass found in this classification:

**Tenant-master-derived prefill is not a sixth top-level category.** A
question whose value can be conveniently pre-filled from a tenant's own
already-entered formulation/product data (e.g. Q4 above, prefilled from
`FormulationComponent.quantity_per_dosage_unit`) remains `USER_REQUIRED`
— it is emphatically not FDA-derived and must never be labeled with
`ProvenanceLabel(kind="FDA_SOURCE")`. Rather than inventing a new
top-level `data_source_type` for this (which would fragment the
classification without changing who may edit/confirm the value — the
edit/lock/confirm semantics are identical to plain `USER_REQUIRED`), a
`ChecklistQuestion.prefill_source` metadata field (nullable, e.g.
`"formulation_component"`) records *where* a convenience prefill came
from, purely for UI/audit transparency. It has no bearing on
`data_source_type` classification or on who may edit the field.

**`NOT_APPLICABLE` is a structural response state, not a data-source
category.** Every `ChecklistQuestion` with a non-null `applicability_rule`
(§9a) can resolve to `NOT_APPLICABLE` regardless of its `data_source_type`
— a `SYSTEM_CALCULATED` question can be inapplicable (Q7 above, when no
IID precedent match exists at all — distinct from the matched precedent
merely lacking an MDE value, which is a blocked calculation, §11, not a
not-applicable question), just as a `USER_REQUIRED` or `REVIEWER_CONFIRMED`
one can. `ChecklistResponse` (§7)
therefore carries an explicit `is_not_applicable` boolean and
`not_applicable_reason` (the structured rule identifier that fired, never
free text — same "reason code, not fabricated text" principle as
`CalculationStatus`), rather than representing "not applicable" as an
overloaded blank/null value that could be confused with "not yet
answered." A question resolved `NOT_APPLICABLE` does not block
`submit_review`/`approve` even if `required=true`, but a reviewer may
override an automatic `NOT_APPLICABLE` determination only with an
explicit justification (reusing the same override machinery as §12).

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
`CalculationStatus`, and which upstream answers/records fed it. This
mirrors `AssessmentSnapshot` freezing calculation provenance — same
pattern, applied to checklist questions instead of a single preview.

**Correction from the first design-review pass (closes DR-04):** this
document originally listed only six `CalculationStatus` values. Direct
inspection of `iid_assessment/calculations.py` found a ninth distinct
value not previously listed. The full, verbatim, reused-unmodified set
is: `OK`, `ROUTE_MISMATCH`, `DOSAGE_FORM_MISMATCH`, `INGREDIENT_UNRESOLVED`,
`UNIT_MISMATCH`, `FDA_VALUE_UNAVAILABLE`, `DATA_REQUIRED`,
`NOT_COMPARABLE`, `REGULATORY_REVIEW_REQUIRED` (the last produced when the
underlying FDA release/record has since been superseded or deactivated —
directly relevant to §8a's `SUPERSEDED` execution state below). No new
status value is introduced by Milestone 4D; all nine are reused verbatim.

### 6a. Answer types (expanded — closes DR-05)

The first design-review pass found the original `answer_type` sketch
(`boolean | decimal | text | choice | attachment_reference`) too coarse
to represent the question shapes IIG checklists actually need. The full
set:

| `answer_type` | Notes |
|---|---|
| `integer` | Distinct from `decimal` — e.g. "maximum dosage units per day" |
| `decimal` | Paired with `allowed_units` when it represents a physical quantity |
| `text` | Short free text |
| `long_narrative` | Free text with a minimum-length expectation — used for justifications, deviation reasons, and the reviewer conclusion (§13); **never auto-confirmable** |
| `date` | |
| `yes_no_na` | Three-state — deliberately **not** a plain `boolean`, so "not applicable" is never conflated with "no" (see §3a) |
| `single_select` | One of a fixed, question-scoped option list |
| `multi_select` | Zero or more of a fixed, question-scoped option list |
| `fda_record_reference` | A reference to a specific `IIDPrecedentRecord`/`OrangeBookProduct`/mapping public ID — always paired with `FDA_DERIVED_DEFAULT` or the reviewer-selection case in `REVIEWER_CONFIRMED` (never freely typed) |
| `formulation_component_reference` | A reference to a specific `FormulationComponent` public ID |
| `attachment_reference` | See §15 |

Any question with `answer_type = long_narrative` used for a justification,
deviation, or conclusion, and any question with `data_source_type =
REVIEWER_CONFIRMED` regardless of `answer_type`, **must never be
auto-confirmed** — this is already guaranteed structurally by §3's
classification (only a `REVIEWER_CONFIRMED` question ever sets
`confirmed_by`), not by anything specific to the answer type itself; the
table above documents it per-type for implementation clarity, it does not
add a second enforcement mechanism.

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
  is_not_applicable            bool, default False — see §3a
  not_applicable_reason        nullable, structured rule identifier
                              (never free text), populated only when
                              is_not_applicable = True
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
  system_derived_value         nullable JSON snapshot of what the system
                              originally produced, populated only when
                              override_reason is set — see §12
```

A `REVIEWER_CONFIRMED` answer with no `confirmed_by` blocks submission —
same "required field enforced at the state-transition boundary, not just
form validation" pattern as `SubstanceMappingProposalSerializer` requiring
`fda_data.import`/`fda_data.review` permission rather than relying on
frontend gating alone.

**Mutation-boundary immutability enforcement (new — closes DR-02, learned
directly from a defect this review found elsewhere in the codebase):**
the first design-review pass discovered that `AssessmentSnapshot.clean()`
already contains an immutability guard for its own model, but that guard
is **never invoked** anywhere in the actual request path — no view calls
`full_clean()`, and immutability today is incidental (there is simply no
update endpoint), not enforced defense-in-depth. `ChecklistResponse` must
not repeat this. Once its parent `ChecklistExecution.status` is
`approved`, any attempted `save()` on a `ChecklistResponse` belonging to
it must call `full_clean()` — which itself checks
`execution.status == approved` and raises `ValidationError` — and the
view/service layer that performs the save must actually invoke
`full_clean()` before `save()`, not merely define the check and leave it
unreachable. This is a required implementation-phase acceptance
criterion (see §18/4D-2), not an optional nicety.

---

## 8. Checklist execution lifecycle

```
ChecklistExecution
  public_id, tenant FK, formulation_version FK (the formulation being
    assessed), checklist_definition FK (pinned to a specific active
    version at creation time — never "latest", so a completed execution's
    meaning never silently drifts when the checklist template is revised;
    see §1a)
  status: draft → submitted_for_review → returned → approved → rejected
    → cancelled → superseded  (§8a — expanded from the original five-state
    sketch)
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
| `cancel` | `draft`, `returned` | `cancelled` |
| `supersede` | `approved` | `superseded` |

`approve` requires every `required` question to have a non-null response
or a valid `NOT_APPLICABLE` resolution (§3a), and every `SYSTEM_CALCULATED`
response whose `CalculationOutcome.status != OK` to have an accompanying
`REVIEWER_CONFIRMED` justification answer in the same section (see the
Q7/Q8 pairing in §2). `approved` is terminal for content mutation (see
§7's immutability-enforcement requirement); `rejected` and `cancelled` are
both terminal and, like `SubstanceSynonymMapping`'s `REJECTED`, cannot be
resurrected — a corrected assessment always starts a **new**
`ChecklistExecution`, never a reopening of a rejected/cancelled one.

### 8a. `CANCELLED` vs. `REJECTED`, and `SUPERSEDED` (closes DR-05, DR-07)

The first design-review pass's suggested state list included several
states (`DATA_ENTRY_COMPLETE`, `CALCULATED`, `REVIEW_COMPLETE`) this
document deliberately does not adopt: they describe *readiness*, not a
governance-relevant transition requiring its own permission gate, and are
better modeled as computed flags on a `draft`/`submitted_for_review`
execution (percentage of required questions answered, whether every
`SYSTEM_CALCULATED` question has resolved) than as formal states. Adding
them would be complexity without a corresponding governance benefit.

Two states genuinely were missing and are added here:

- **`cancelled`** — an execution abandoned before ever reaching review
  (e.g. started against the wrong formulation version). Distinct from
  `rejected`, which specifically means a reviewer examined it and
  declined it. `cancel` requires no special permission beyond the
  creator's own `draft`-state edit access.
- **`superseded`** — an already-`approved` execution whose basis has
  since changed (the FDA release it referenced was superseded, or the
  formulation version it assessed was revised). **This transition is
  never automatic.** A scheduled advisory check may *flag* an approved
  execution as referencing now-stale data, but only a human explicitly
  calling `supersede` marks it — the same principle already proven for
  `FDADataSourceRelease` and `SubstanceSynonymMapping`: superseding
  content is always a deliberate action, never a side effect of a
  background job. A superseded execution remains permanently readable
  (reproducibility, §18) but can no longer be referenced as the "current"
  assessment for its formulation version; a corrected assessment requires
  a **new** `ChecklistExecution`, never a reopening.

### 8b. Recalculation semantics (new — closes DR-08)

Not previously specified. The rule: while `status = draft`, editing a
`USER_REQUIRED`/`EVIDENCE_DERIVED` input answer immediately re-triggers
recomputation, in place, of every `SYSTEM_CALCULATED` question whose
`calculation_binding` depends on it (§9) — nothing is frozen yet, so
in-place mutation of the draft's `CalculationOutcome` rows is correct and
expected. The moment `submit_review` succeeds, every response — including
`SYSTEM_CALCULATED` ones — is locked: no further mutation, in place or
otherwise, until the execution is explicitly `return`ed back to `draft`.
This means a reviewer who finds an input needs correction cannot silently
trigger a hidden recalculation mid-review; they must `return` the
execution first, forcing the change to go through the same
submit-again/reviewed-again cycle as any other correction. **Approving an
execution never itself creates a new `ChecklistExecution` or a new
`ChecklistDefinition` version** — recalculation is strictly an
intra-execution, pre-submission concept; a change needed after approval
always means starting a new execution (§8a).

Segregation of duties: the actor who `submitted_review` cannot `approve`
their own execution — same self-approval check already proven in
`_MappingActionViewBase`, reused verbatim rather than reinvented.

---

## 9. Checklist response storage and calculation-to-question mapping

`CalculationOutcome` wraps exactly one call into the **existing**
`iid_assessment.calculations` module — it does not duplicate formula
logic. **Correction from the first design-review pass (closes DR-04):**
the function names below now carry their actual `calculate_` prefix
(the original sketch dropped it), and `CalculationOutcome` is expanded to
mirror the fields `CalculationResult` (the dataclass these functions
already return) genuinely carries, rather than re-deriving a thinner
subset of them:

```
CalculationOutcome
  public_id
  calculation_name       one of: percentage_w_w | daily_exposure |
                          percentage_of_potency | difference_from_potency |
                          percentage_of_mde | difference_from_mde
                          (exact 1:1 match to calculate_percentage_w_w,
                          calculate_daily_exposure,
                          calculate_percentage_of_potency,
                          calculate_difference_from_potency,
                          calculate_percentage_of_mde,
                          calculate_difference_from_mde in
                          iid_assessment/calculations.py — no new formulas)
  formula_version         copied verbatim from CalculationResult.formula_version
                          (today a single global FORMULA_VERSION string
                          shared by all six functions, not independently
                          versioned per formula — a pre-existing property
                          of iid_assessment, not something 4D changes;
                          if iid_assessment later moves to per-formula
                          versioning, this field already has the room to
                          carry it without a schema change)
  status                 iid_assessment.calculations.CalculationStatus value
                          — the full nine-value set, see §6
  value                   Decimal, nullable
  unit
  rounding_rule           copied verbatim from CalculationResult.rounding_rule
  reason_code             copied verbatim from CalculationResult.reason_code
  input_provenance        copied verbatim from CalculationResult.input_provenance
                          (which upstream answers/records fed the
                          calculation — the mechanism this document
                          originally described in prose is already a named
                          field on the type being reused)
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

### 9a. Applicability-rule evaluation mechanism (new — closes DR-03)

The first design-review pass found that `ChecklistQuestion.applicability_rule`
(§1) was named as a field but its evaluation mechanism was never designed
— a genuine gap, not a deferred detail, since the wrong answer here (a
free-text expression interpreted dynamically) would reopen exactly the
"arbitrary executable content in governed data" risk this codebase has
consistently closed elsewhere (no `eval`, no stored executable
expressions, allow-listed calculation bindings only — §7/§9 of the
original document already state this principle for calculations; it must
apply identically to applicability).

`applicability_rule` is a structured JSON condition tree, not a string:

```json
{
  "all": [
    {"field": "route", "op": "eq", "value": "oral"},
    {"field": "iid_precedent.mde", "op": "exists"}
  ]
}
```

- A fixed, small operator vocabulary: `eq`, `in`, `exists`, `not_exists`,
  composed only via `all` (AND) / `any` (OR) — no arbitrary boolean
  expression language, no string-based comparisons beyond simple
  equality/membership.
- `field` values are drawn from a fixed, allow-listed field set exposed
  by the execution's own formulation-version/FDA-precedent context
  (`route`, `dosage_form`, `release_type`, `iid_precedent.mde`,
  `iid_precedent.match_status`, etc.) — never an arbitrary Python
  attribute path, and never anything client-supplied.
- Evaluated by a small, pure Python interpreter with no `eval`/`exec` and
  no dynamic attribute access — a fixed dispatch table keyed by `op`.
- Versioned alongside the `ChecklistDefinition` it belongs to (§1a) —
  since a definition version is immutable once approved, its questions'
  applicability rules are frozen with it.
- Every `NOT_APPLICABLE` resolution (§3a) stores exactly which rule
  fired, as the structured condition-tree fragment that evaluated false
  (or a stable identifier for it), never a free-text explanation
  standing in for the actual logic — the same "reason code, not
  fabricated text" principle `CalculationStatus` already establishes.

This mechanism is deliberately minimal for Milestone 4D's scope — it is
sized to express the kinds of conditions in §16/§9 of the review's
findings (route/dosage-form/release-type/precedent-availability
conditions), not a general-purpose rules engine. Expanding the operator
vocabulary later is additive (new dispatch-table entries), never a
redesign.

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

**Decided:** an override is never allowed on a `SYSTEM_CALCULATED` answer
(only on `FDA_DERIVED_DEFAULT`) — a calculation is arithmetic on
already-confirmed inputs; if a reviewer disagrees with a calculated
result, the correct action is to challenge the *input* answer (which is
either `USER_REQUIRED` and editable, or `FDA_DERIVED_DEFAULT` and
overridable), not to hand-edit a derived number. Allowing direct override
of calculated values would reopen exactly the "can a human silently
override a formula result" gap this system is designed to prevent.

**Who may override, and how many approvals an override needs (closes a
gap the first design-review pass flagged as ambiguous):** overriding any
answer requires at minimum `iig_checklist.review` — a Doer-equivalent
actor holding only creation-level access can never override a
`FDA_DERIVED_DEFAULT` value, matching the floor already required for
every override-capable action elsewhere in this codebase (mapping
submit-review, reject, and return all require `fda_data.review`, never
plain `fda_data.import`). There is exactly **one approval point for every
override an execution contains**: the single execution-level `approve`
action (§8) ratifies the execution as a whole, including every override
recorded within it. There is no separate, granular per-override approval
routing — an execution is approved or it is not; an approver who is not
comfortable with a specific recorded override should `return` the
execution rather than approve it with reservations.

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

Fully specified by §8/§8a's `ChecklistExecution` transition table
(submit → review → approve/reject/return/cancel/supersede) and, entirely
separately, §1a's `ChecklistDefinition` transition table
(submit → review → approve → activate → supersede/retire) — two tables
for two distinct concerns, not one combined workflow layer. Both follow
the same shape already established by `fda_data`/`templates_registry`:
segregation of duties, structured 400 on illegal transitions, no bypass
through an alternate endpoint. `ChecklistExecution` actions share one
`_ChecklistActionViewBase`, mirroring `_MappingActionViewBase`'s proven
shape; `ChecklistDefinition` actions share their own equivalent base view
following the identical pattern (§1a).

---

## 15. Evidence attachments

`ChecklistResponse.attachment_reference` (for `answer_type =
attachment_reference` questions, and for every `EVIDENCE_DERIVED`
question per §3/§3a) points at a `documents`-app-managed file via
`storage_key` indirection — **reusing the existing `documents` app's
storage/tenant-isolation machinery rather than building a second
file-upload path.** An attachment passes through whatever scan gate the
`documents` app is currently configured to run before it can be
referenced by an approved checklist response.

**Correction from the first design-review pass — mandatory disclosure,
not an implementation detail (closes DR-05):** direct inspection of
`documents/scanner.py` and `regx/settings/base.py` found that
`DOCUMENT_SCANNER_BACKEND` defaults to `"stub"` in every configuration
present in this repository, and `StubScanner` is explicitly documented in
its own source as a development/test stub that "marks every file as
clean without performing any real malware analysis." `ClamAVScanner`
exists and appears functionally complete, but is wired to a live clamd
service nowhere in this repository. **Milestone 4D does not resolve
this gap — it inherits it unchanged from Milestone 2/3.** Evidence
attachments accepted by the checklist engine carry exactly the same
scanning assurance as document uploads anywhere else in this platform
today: none, unless and until a real scanner backend is deployed and
configured. This document must not be read as claiming evidence-upload
malware scanning is production-ready; production use of checklist
evidence attachments requires the same pre-existing, cross-cutting
scanner-deployment work as any other document upload in this platform,
and that work is out of scope for Milestone 4D.

Retention: an attachment referenced by an `approved` `ChecklistExecution`
is delete-blocked, following the same "cannot delete something a governed
conclusion depends on" pattern already enforced for approved
`SubstanceSynonymMapping` rows.

**Decided (was OPEN QUESTION 2):** an evidence attachment does not have
its own independent governance lifecycle (it cannot be superseded or
retracted separately from its parent execution) — it is immutable the
moment its parent response is written into an `approved` execution. A
second, independent lifecycle for evidence would let a governed
conclusion's basis be silently altered after the fact without a new
execution, repeating exactly the pattern this codebase has consistently
rejected elsewhere (approved releases, approved mappings, approved
template versions are all correction-via-new-version, never
correction-via-in-place-edit).

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
read-only **JSON or CSV** report, following the same neutralization
pattern already shipped for `templates_registry`'s reconciliation CSV
export (Milestone 3's Major-finding remediation): every cell is passed
through the existing formula-injection-safe CSV cell writer before
serialization. No new CSV-safety code is written.

**Decided (was OPEN QUESTION 3):** `templates_registry.reconciliation`'s
private `_csv_safe_cell()` helper is promoted to `common` now, not
duplicated. Direct inspection confirmed it is small (~10 lines),
dependency-free, and has zero coupling to `templates_registry` models —
the "wait for a third consumer" caution doesn't meaningfully reduce risk
here, while a single shared implementation does meaningfully reduce the
risk of one consumer's copy silently drifting out of sync with a future
CSV-injection-safety fix. Promotion requires making the function public
(dropping the leading underscore) and updating `templates_registry`'s own
import to point at the promoted `common` version, so there is exactly one
implementation platform-wide, not two that happen to agree today.

**PDF and Word export formats are explicitly deferred beyond Milestone
4D**, not included in initial scope. No generated-document pipeline
exists anywhere in this repository today — the `documents` app handles
uploaded files, not system-generated ones — and building one is
non-trivial net-new surface area that should be scoped on its own once
JSON/CSV export is proven in production use, not bundled into 4D's
already-substantial scope.

Every export includes, in addition to the full per-question provenance
already described in §18: a **SHA-256 checksum** computed over the
canonical serialized export payload at generation time, stored alongside
the `iig_checklist.execution.exported` audit event. This lets a later
dispute verify a previously-issued export was not altered after the fact
— the same kind of tamper-evidence property `AuditEvent`'s append-only,
DB-trigger-enforced immutability already provides for the audit trail
itself, applied to the export artifact.

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
*intent* `AssessmentSnapshot` already provides for a single preview,
extended to a whole checklist — with one correction from the first
design-review pass that this design must not repeat (see §7's
mutation-boundary requirement): `AssessmentSnapshot`'s own immutability
guard (`clean()`) is, today, never actually invoked anywhere in the
request path — no view calls `full_clean()` on it, and its immutability
in practice comes only from the absence of an update endpoint, not from
an enforced check. `ChecklistResponse`/`ChecklistExecution` reproduce the
*intent* (frozen, reconstructable state) but must implement the
*enforcement* properly — `full_clean()` actually invoked at every save
attempt once `approved`, per §7 — rather than copying the unreachable
pattern verbatim.

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
4. Draft generation (§10): Q1 (`SYSTEM_CALCULATED` — it is a computed
   match-status, not a raw FDA field, so it is classified
   `SYSTEM_CALCULATED` per §3, sourced from an `FDA_DERIVED_DEFAULT`
   input underneath) resolves via
   `resolve_substance_identity(normalized_name="ACETAMINOPHEN")` → finds
   an `APPROVED` `SubstanceSynonymMapping` (or a direct `IIDIngredient`
   exact match) → `EXACT_MATCH`. Q2/Q3 (`SYSTEM_CALCULATED`, same
   reasoning) compare the proposed oral/tablet route+dosage-form against
   the matched IID precedent record → both match. **Q4
   (`USER_REQUIRED`, `prefill_source=formulation_component` — §3a
   correction from the first design-review pass)** is left blank by the
   draft-generation pass itself, but the frontend separately pre-populates
   it from `FormulationComponent.quantity_per_dosage_unit` as a pure UI
   convenience. This prefill is recorded via `prefill_source`, not any
   `FDA_DERIVED_DEFAULT`-adjacent mechanism — Q4 remains `USER_REQUIRED`,
   remains user-editable, and is never labeled with
   `ProvenanceLabel(kind="FDA_SOURCE")`, since the value did not come
   from FDA-governed data at all, only from the tenant's own
   already-entered formulation record.
5. Q5 (`SYSTEM_CALCULATED`, `percentage_w_w`) computes
   `500mg / 650mg = 76.9%` — status `OK`.
6. Q6 (`SYSTEM_CALCULATED`, `daily_exposure`) computes
   `500mg × 6 = 3000mg/day` — status `OK`.
7. Q7 (`SYSTEM_CALCULATED`, `difference_from_mde`) is applicable (Q1
   resolved `EXACT_MATCH`, §3a/§9a) and compares 3000mg against the IID
   precedent's `iid_mde` for acetaminophen at this route/dosage-form. If
   the precedent's MDE field is genuinely absent in the source data, this
   returns `FDA_VALUE_UNAVAILABLE` (never a fabricated pass, and not
   `NOT_APPLICABLE` — the comparison is meaningful, the source data just
   doesn't support it) — and Q8 becomes required: a `REVIEWER_CONFIRMED`
   justification for proceeding without an MDE comparison, exactly the
   §11 blocked-state handling.
8. Q9 (`EVIDENCE_DERIVED`) requires the reviewer to attach a vendor
   certificate of analysis confirming excipient grade before this
   question counts as answered — the attachment goes through the
   `documents` app's existing storage/tenant-isolation path (§15,
   including the disclosed scanner-status caveat).
9. The reviewer completes Q8, adds the top-level `reviewer_conclusion_note`
   (§13), and calls `submit_review`. A different, VP-permissioned actor
   reviews and calls `approve`.
10. At no point does any system output read "acetaminophen is safe at this
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
- **No production-ready malware scanning of evidence attachments.** As
  disclosed in §15, `DOCUMENT_SCANNER_BACKEND` defaults to the
  non-production `StubScanner` in every configuration in this repository
  today; Milestone 4D inherits this pre-existing gap unchanged and does
  not resolve it. Real scanner deployment is a separate, cross-cutting
  infrastructure item.
- No electronic-signature mechanism beyond standard authenticated-action
  logging (`approved_by`/`approved_at`, identical in strength to every
  other approval action in this codebase) — no 21 CFR Part 11 e-signature
  claim is made.
- No automatic reassessment. A formulation-version edit or an FDA-release
  supersession never automatically reopens, mutates, or invalidates an
  approved `ChecklistExecution` (§8a) — a corrected assessment is always a
  new execution, and a human always decides when to start one.
- No real FDA data ingestion, no real client formulation data, no
  Milestone-4D implementation code. This document defines the shape only.

---

## Summary of new components (implementation-phase scope, not built here)

- New Django app `iig_checklist`: `ChecklistDefinition`, `ChecklistSection`,
  `ChecklistQuestion` (expanded field set, §1), `ChecklistExecution`
  (with `cancelled`/`superseded`, §8a), `ChecklistResponse` (with
  `is_not_applicable`/`not_applicable_reason`, §3a/§7), `CalculationOutcome`
  (expanded to mirror `CalculationResult`, §9).
- A `definition_transitions.py` transition table for `ChecklistDefinition`
  governance (§1a) and a separate `execution_transitions.py` table for
  `ChecklistExecution` (§8) — both structurally identical to
  `fda_data/mapping_transitions.py`, kept as two tables because a
  definition's lifecycle (content authoring) and an execution's lifecycle
  (one tenant's use of that content) are genuinely different concerns,
  same reasoning `fda_data` already applies by keeping release governance
  and mapping governance as separate transition tables rather than one
  combined one.
- A small, allow-listed applicability-rule evaluator (§9a) — no eval, no
  stored executable expressions, a fixed operator dispatch table.
- A `_ChecklistActionViewBase`, structurally identical to
  `_MappingActionViewBase`.
- New audit events (§16), new permissions
  (`iig_checklist.review`/`.approve`/`.export_checklist`, following the
  existing `fda_data` permission-codename convention).
- Promotion of `templates_registry`'s private CSV-safety helper to a
  public function in `common` (§17), with `templates_registry` updated to
  import the promoted version.
- Frontend: a checklist execution screen (section-by-section, matching
  the existing mapping-review page's confirmation-dialog pattern), an
  evidence-attachment upload reusing the `documents` upload component,
  and a read-only export view (including the export checksum, §17).
- Import-linter contract addition: `iig_checklist` may depend on
  `fda_data`, `formulations`, `iid_assessment`, and `documents` (read
  paths only); none of those four may depend back on `iig_checklist`.

## Open questions requiring a decision before implementation

**Status after the first design-review pass:** four of the original five
questions below are now **decided** (see the "Decided" markers throughout
this document, and
[MILESTONE_4D_DESIGN_REMEDIATION.md](MILESTONE_4D_DESIGN_REMEDIATION.md)
for the full finding-by-finding traceability). One — the exact set of
checklist templates to ship — is explicitly **deferred**, not decided, per
the review's own recommendation: it is a regulatory-content decision that
should not be resolved unilaterally by engineering judgment.

1. **RESOLVED** — New app vs. extending `iid_assessment` for `ChecklistDefinition` (§1). **Decision: new app** (`iig_checklist`), for the reasons given in §1.
2. **RESOLVED** — Whether evidence attachments need an independent lifecycle (§15). **Decision: no** — frozen with the parent execution the moment it is written into an `approved` execution.
3. **RESOLVED** — Promote CSV-safety helper to `common` now vs. duplicate (§17). **Decision: promote now**, made public, `templates_registry` updated to import the promoted version.
4. **DEFERRED — regulatory-content decision, not an engineering one.** Exact set of built-in `ChecklistDefinition` templates to ship (oral solid, oral liquid, parenteral, topical?) — not addressed in this document, needs a separate content-scoping conversation with whoever owns the IIG guidance interpretation. This does not block 4D-1 through 4D-3 (schema/execution/calculation-binding need no specific content), only 4D-4 onward (draft-answer generation needs at least one real or synthetic checklist definition to exercise). The paracetamol/acetaminophen worked example (§19) can serve as the synthetic test fixture regardless of which real template ships first, so engineering is not blocked by the content-scoping timeline.
5. **RESOLVED** — Whether a `ChecklistExecution` can span multiple `FormulationVersion`s (e.g. one checklist per excipient across a whole formulation) or is strictly one-per-version (§8). **Decision: strictly one-per-version.** This is consistent with how `AssessmentSnapshot`/`FormulationComponent` already scope everything to a single `FormulationVersion` at a time everywhere else in this codebase; breaking that pattern only for checklists would be an inconsistency, not a feature, and would materially complicate §8's foreign-key shape and §18's reproducibility guarantee for no clear benefit. This was the most structurally load-bearing of the five original questions — a wrong choice here would have forced a breaking migration once execution-model implementation (4D-2) began, so it is resolved now rather than left open into implementation.
