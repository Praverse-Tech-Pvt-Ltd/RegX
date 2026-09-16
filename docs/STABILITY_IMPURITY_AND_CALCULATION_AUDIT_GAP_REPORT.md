# Stability / Impurity Tooling and Calculator Provenance — Gap Report

> **Scope:** SOW 2.9 as a whole — both the *"stability & impurity AI assistant"*
> half and the *"Part 11 audit trail for calculator inputs/outputs"* half.
> **Type:** inspection record. No code, model, migration, audit, AI, history
> model, snapshot or calculation change accompanies this document.
> **Inspected at:** `regx-main` `d323084e211f560289226e268b66b0a50698b825`.
> **Companions:** [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md),
> [MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md),
> [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md),
> [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)

## Final status

| Area | Status |
|---|---|
| Stability / impurity assistant | **BLOCKED** — feasibility and product specification unresolved |
| Existing IIG/IID calculation provenance | **ENGINEERING-SPEC CONFORMANT** |
| Part 11 sufficiency | **NOT DETERMINED** |

**This report makes no 21 CFR Part 11 compliance conclusion.** The codebase's
existing Part 11 disclaimers remain intact and are not weakened by anything
recorded here.

---

## A. Stability & impurity AI assistant

### A.1 No REGX implementation exists

Searched at `d323084` across `backend/`, `frontend/`, `company_site/` and
`docs/`, excluding vendored directories:

| Term | Files | Where |
|---|---|---|
| `stability` | 32 | 24 legacy `company_site/templates`, 7 docs, 4 frontend test fixtures, **3 backend — all incidental** |
| `impurity` | 2 | `RATools/DMF/DMFChecklist.html` prose; legacy sqlite binaries |
| `shelf_life` | 8 | Legacy sqlite databases and RATools templates only |
| `degradant` | 4 | Legacy sqlite databases only |
| `assay` | 4 | Legacy sqlite databases only |
| `specification limit` | 4 | Legacy sqlite databases only |

The three backend `stability` matches are a test-fixture title
`"Stability data package"` in `regulatory_cases/tests/conftest.py` and
`submission_dossiers/tests/conftest.py`, and a code comment describing a
`"worker-stability risk"`. **None is stability tooling.**

There is no stability engine, no impurity engine, no shelf-life model and no
assistant of any kind in REGX.

### A.2 Feasibility is unresolved at the SOW level

A secondary record of the same SOW section — the legacy
`SOW-TECHNICAL-TOOLS-STATUS.md`, which measured a different codebase against the
same pages — renders 2.9 as **"Stability & impurity AI assistant"** and notes
that **the SOW itself marks it feasibility-TBD**.

That is recorded here as **secondary corroboration only**. It is not the SOW and
does not stand in for it. The authoritative SOW PDF was not available to the
author of this report; the feasibility-TBD status shall be verified against the
primary document when it becomes available.

The same requirement-source limitation, and the same three-level evidence
discipline, are set out at length in `WORD_ADDIN_GAP_REPORT.md` (P10, open as
PR #61 at the time of writing and therefore deliberately not linked here).

### A.3 Deficiency precedent data exists — and is not an assistant

REGX holds real, governed data that a future assistant would draw on:

* `deficiencies.DeficiencyRecord`, with corpora `ANDA` ("ANDA Deficiency
  Roadmap") and `MAJOR_CR` ("Major CR Roadmap");
* a PROTECT foreign key to `fda_data.FDADataSourceRelease`, so a corpus traces
  to the release that produced it;
* an `import_deficiencies` management command;
* list and facets endpoints behind `CanViewDeficiencies`.

That corpus contains FDA deficiency wording about impurities, assays and
degradants. **It is source data, not tooling, and its existence does not
constitute progress on 2.9.** Retrieving a precedent is not assessing a
stability or impurity question.

### A.4 No AI implementation is authorised

REGX contains **no AI generation capability in the backend**. No AI work is
authorised by this report, and none is performed by it. Any future assistant
would need — at minimum — a functional specification, an accuracy and
verification standard, a data boundary, and a regulatory position on what an
assistant may assert. None of those exists today.

---

## B. Calculator input/output provenance and audit

### B.1 The existing six-calculation mechanism

Six approved calculations exist and execute, enumerated in
[CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §2.2. For each execution:

* **`iig_checklist.response.calculated`** is emitted **after commit**, carrying
  actor, tenant, `execution_public_id`, `response_public_id`,
  `outcome_public_id`, `question_code`, `registry_identifier`,
  `calculation_name`, `status`, `reason_code` and, when one exists,
  `assessment_snapshot_public_id`. It carries **identifiers and status, not
  values**.
* **`CalculationOutcome`** records `calculation_name`, `formula_version`,
  `status`, `value`, `unit`, **`inputs`**, **`input_provenance`**,
  `rounding_rule`, `reason_code`, `generated_at` and
  `source_assessment_snapshot_public_id`.
* `CalculationOutcome._validate_completed_outcome()` **refuses to save a
  `COMPLETE` row without its provenance**. That is an enforced invariant, not a
  convention.
* `AuditEvent` itself is append-only at two layers — an ORM guard and two
  PostgreSQL triggers ([AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)).

### B.2 What the 4D-3 engineering specification requires

Quoted from
[MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md):

> **M4D3-PRV-001** The reproducibility chain shall consist of
> `calculation_name`, `formula_version`, `inputs`, `input_provenance`,
> `rounding_rule`, `generated_at`, `source_assessment_snapshot_public_id`, and
> the deployed code version. **No new database column shall be added.**

> **M4D3-RCL-003** Recalculation shall **update existing outcome rows in place**,
> calling `full_clean()` before each save.

> **M4D3-RCL-004** Recalculation shall produce no audit event and no version
> change when `status`, `value`, `reason_code` and `generated_at` are all
> unchanged.

> **M4D3-SNO-006** Normative snapshot policy: the orchestration service shall
> **create a new immutable `AssessmentSnapshot` for every governed population or
> recalculation event** in `draft` or `returned`. It shall not search for,
> deduplicate, or reuse an earlier snapshot. … **preserves the exact source
> assessment used for each event.**

> **M4D3-SNO-009** Required order for each governed calculation event: resolve
> the subject component; resolve the current approved FDA/IID release; call the
> governed `iid_assessment` snapshot service; receive exactly one
> `AssessmentSnapshot` object; retain it in the transaction-scoped context;
> resolve snapshot-derived kwargs from it; **execute the potency and MDE
> calculations**; persist each `CalculationOutcome` with the snapshot
> `public_id` and provenance; commit; emit audit after commit.

Read together, the specification decides four things explicitly:

| Question | Specification answer |
|---|---|
| Current-state only? | **Yes** — `CalculationOutcome` is updated in place (RCL-003) |
| Append-only outcome history? | **No** — and PRV-001 forbids adding a column for one |
| Historical record elsewhere? | **Yes** — a new immutable `AssessmentSnapshot` per governed event (SNO-006) |
| Audit pointer sufficient? | **Sufficient under the specified 4D-3 provenance design.** This does not establish sufficiency for SOW 2.9 or for 21 CFR Part 11 |

### B.3 Implementation trace

| Requirement | Implementation at `d323084` | Conforms |
|---|---|---|
| RCL-003 in-place update | `calculation_execution.py` saves the existing outcome row (three call sites); no replacement row is created | **Yes** |
| PRV-001 chain, no new column | All eight chain elements are fields on `CalculationOutcome`; no history column exists | **Yes** |
| SNO-006 one new snapshot, never reused | `_create_governed_snapshot()` → `iid_assessment.services.create_assessment_snapshot()`, documented as *"Create exactly one immutable `AssessmentSnapshot` and return it."* No lookup, no `get_or_create`, no reuse path | **Yes** |
| SNO-009 scope — "the potency and MDE calculations" | Gated by `_entry_needs_snapshot()`, true when any declared input reads from an `AssessmentSnapshot`. From the registry source, that is `percentage_of_iid_potency`, `difference_from_iid_potency`, `percentage_of_iid_mde` and `difference_from_iid_mde` — which use `_snapshot_resolver`. `percentage_w_w` and `daily_exposure` do not | **Yes** |
| MAP-010 upstream inheritance | The MDE calculations take no direct component input; their subject component is inherited from the upstream `calculate_daily_exposure` response | **Yes** |

`ChecklistResponseHistory` is append-only but records **reviewer-conclusion
amendments to responses** (`prior_raw_value` / `new_raw_value`). It is not a
calculation-outcome history, and the specification asks for none. No
`CalculationAmendment` model exists or is required.

### B.4 Classification — A, specified and satisfied

**Specification conformance: A — specified and satisfied.**
`CalculationOutcome` is intentionally a mutable current-state projection.
Recalculation updates the existing row in place under **M4D3-RCL-003**, while
governed historical provenance for snapshot-consuming calculations is preserved
through immutable `AssessmentSnapshot` records under **M4D3-SNO-006 / SNO-009**.
This architecture is deliberate and **shall not be characterised as a missing
calculation-history implementation.**

### B.5 Correction of an earlier inspection interpretation

An earlier inspection observation treated in-place outcome replacement as a
possible historical-retention gap. Review of the governing 4D-3 requirements
showed that interpretation was incorrect; in-place replacement is explicitly
required by the approved engineering specification.

The correction is recorded rather than removed because it shows the design was
re-evaluated against the governing engineering specification before any
implementation was proposed. It is **not** a corrective action, a defect, or a
validation deviation — it is an inspection interpretation corrected before
implementation.

### B.6 Residual governance question

**Residual regulatory/governance question — not an implementation defect.**
`percentage_w_w` and `daily_exposure` are outside the governed
`AssessmentSnapshot` path defined for the potency/MDE calculation family. Their
current `CalculationOutcome` is updated in place, and the corresponding audit
event records identifiers/status rather than a historical copy of the complete
prior input/output values. The 4D-3 engineering specification permits this
design. Whether that retention model satisfies the separate SOW 2.9 expectation
for a *"Part 11 audit trail for calculator inputs/outputs"* requires
regulatory/governance determination. **This report makes no Part 11 compliance
conclusion.**

Four distinctions are held apart deliberately in the paragraph above, and should
be preserved in any downstream summary of it:

1. the implementation conforms to 4D-3;
2. no engineering defect is established;
3. the SOW 2.9 regulatory expectation may be broader than the engineering
   specification;
4. engineering must not decide that Part 11 question itself.

### B.7 No Part 11 compliance claim

The codebase declines the Part 11 claim in several places, verified directly at
this commit:

* `backend/workflows/models.py:5` — *"…approval, and establishes no Part 11
  claim…"*
* `docs/DOSSIER_BLUEPRINTS.md:13` — *"**Not regulatory approval.** No 21 CFR Part
  11 compliance claim, no GxP"*
* `docs/DOSSIER_UPGRADES.md:16` — *"No Part 11 claim, no GxP validation claim, no
  validated-production…"*

Those disclaimers stand. Nothing in this report asserts, implies or advances a
Part 11 compliance position, and the presence of an immutable audit mechanism
does not constitute one.

---

## C. Relationship to P9

[CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) established that **SOW 2.3's
dissolution, impurity and stability calculators do not exist in either codebase
and are blocked on approved client formula specifications**, and that
`SCOPE-OUT-18` caps the existing registry at six formulas so a seventh cannot be
added to satisfy content.

That position is unchanged. This report **does not invent those calculators, nor
an audit design for them.** SOW 2.9's audit sub-bullet refers to calculator
inputs and outputs; for the calculators that do not yet exist, there is nothing
to audit, and the audit design for them cannot be settled before the formulas
are.

Two further constraints carried forward:

* The production regulatory content approval register stands at **0 of 20
  approved**
  ([MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md)), with
  Items 13 and 14 — the calculation bindings and their ordering — **PENDING**.
* The six formulas are governed by an approved *engineering* specification, not
  by a traceable external regulatory source
  ([CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §2.6).

---

## D. What this report does not authorise

No history model. No audit payload expansion. No broadening of the
`AssessmentSnapshot` path. No calculation change. No AI implementation. No
alteration of any Part 11 disclaimer.
