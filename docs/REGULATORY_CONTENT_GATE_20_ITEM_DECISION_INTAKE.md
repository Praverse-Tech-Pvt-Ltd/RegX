# Production Regulatory Content Gate — 20-Item Decision Intake

> **What this is:** a control package that turns the existing 20-item Approval
> Register into a completable decision form for a named regulatory authority.
> **What this is not:** approved content, a regulatory conclusion, or an approval
> of any kind. **It authors no checklist content, invents no citation, names no
> authority, and changes no register status.**
> **Verified at** `regx-main` `80661f3cbd9b0e97b5c6329aacd78350f38469ec`. Every
> item title, class, citation requirement, interpretation risk, status and
> completion criterion below was **extracted from the register at this SHA**,
> not retyped.
> **Companions:** [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md),
> [MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md),
> [MILESTONE_4D_4_CONTENT_APPROVAL.md](MILESTONE_4D_4_CONTENT_APPROVAL.md),
> [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md),
> [CALCULATOR_SPECIFICATION_INTAKE.md](CALCULATOR_SPECIFICATION_INTAKE.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md)

## A. Current register state, measured at this SHA

**Do not assume a count.** This is what the register says right now.

| Measured | Value |
|---|---|
| Total items | **20** |
| `PENDING` | **20** |
| `APPROVED` | **0** |
| Item 20 (formal sign-off) | ****PENDING**** |
| Production regulatory content gate | **OPEN — 0 of 20 approved** |

**Observed-state snapshot — read from the register, not a decision:**

| Field | Current observed |
|---|---|
| Approved | **0** / 20 |
| Pending | **20** / 20 |
| Rejected | **0** / 20 |
| Deferred | **0** / 20 |
| Gate | **OPEN** |

> The register states the count *“changes only when a named regulatory authority
> supplies a real approval. It is not advanced by document completeness,
> engineering readiness or milestone progress.”* **Nothing here advances it.**

## B. Owner classes

Only the classes the register itself uses. **No individual is named in this
document, because the repository names none.**

| Class | Meaning (register §1) |
|---|---|
| **REGULATORY-AUTHORED** | Regulatory writes it. Engineering may format and validate; never choose |
| **REGULATORY-APPROVED / ENGINEERING-DERIVED** | Engineering derives it mechanically from approved input; Regulatory confirms |
| **JOINT REGULATORY + ENGINEERING** | Regulatory intent plus a mechanical constraint that can make the intent unimplementable. Neither side can settle it alone |
| **FORMAL SIGN-OFF** | The signature that closes the gate |

| Field | Value |
|---|---|
| Named accountable authority | |
| Role | |
| Approval evidence | |

## C. Master 20-item decision matrix

One row per item, none collapsed or grouped. Titles, statuses, risks and
citation requirements are exactly as the register records them.

| # | Register title | Current status | Interpretation risk | Owner class | Citation required? | Blocked on | Final disposition |
|---|---|---|---|---|---|---|---|
| 1 | Which `ChecklistDefinition` templates ship | **PENDING** | **HIGH** — the wrong set means the wrong products are assessed | REGULATORY-AUTHORED | **Yes** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 2 | Checklist title per definition | **PENDING** | LOW | REGULATORY-AUTHORED | No | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 3 | Jurisdiction | **PENDING** | **HIGH** — the wrong jurisdiction invalidates every question under it | REGULATORY-AUTHORED | **Yes** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 4 | Regulatory basis | **PENDING** | **HIGH** | REGULATORY-AUTHORED | **Yes** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 5 | Source guidance, version, publication date | **PENDING** | **HIGH** — an uncitable decision cannot be defended in audit | REGULATORY-AUTHORED | **Yes — this item *is* the citation requirement** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 6 | Section structure and ordering | **PENDING** | MEDIUM — ordering affects reviewer flow and export order | REGULATORY-AUTHORED | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 7 | Question text (verbatim) | **PENDING** | **HIGH — the highest in the register** | REGULATORY-AUTHORED | **Yes** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 8 | Question codes / public identifiers | **PENDING** | MEDIUM — codes are regulatory-facing in exports | JOINT REGULATORY + ENGINEERING | No | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 9 | Answer type per question | **PENDING** | **HIGH** — the answer type determines what a reviewer may record | JOINT REGULATORY + ENGINEERING | No | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 10 | Required vs optional | **PENDING** | **HIGH** — a wrongly-optional question lets an execution be approved without it | REGULATORY-AUTHORED | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 11 | Applicability rules | **PENDING** — capability limit resolved by `5A-DEC-004` | **HIGH** — applicability decides whether a question must be answered at all | REGULATORY-AUTHORED (intent); engineering encodes | **Yes** | OQ-4, OQ-8 | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 12 | `FDA_DERIVED_DEFAULT` bindings | **PENDING** — capability limit resolved by `5A-DEC-001` | **HIGH** — a wrong source field puts a wrong regulated value in front of a reviewer | JOINT REGULATORY + ENGINEERING | **Yes** | OQ-8 | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 13 | `SYSTEM_CALCULATED` bindings | **PENDING** | **HIGH** — the wrong calculation produces a wrong regulated number | JOINT REGULATORY + ENGINEERING | **Yes** | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 14 | Calculation dependencies / ordering | **PENDING** (blocked on 12–13) | LOW — derived, not authored | REGULATORY-APPROVED / ENGINEERING-DERIVED | No | Items 12–13 (register: “blocked on 12–13”) | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 15 | Help / guidance text | **PENDING** | **HIGH** — help text steers how a reviewer answers | REGULATORY-AUTHORED | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 16 | Reviewer expectations per question | **PENDING** | **HIGH** — this defines the review standard | REGULATORY-AUTHORED | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 17 | Override eligibility per question | **PENDING** | MEDIUM | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 18 | Export inclusion per question | **PENDING** — settled by `5A-DEC-003`; confirmation only | MEDIUM | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 19 | Version number and effective date | **PENDING** | MEDIUM — effective date determines which version governs an assessment | ⚠ **REGULATORY-APPROVED / ENGINEERING-DERIVED** (4D-4 table: "Regulatory") | Where guidance-derived | — | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |
| 20 | Formal sign-off | **PENDING** | **HIGH** | FORMAL SIGN-OFF | Source-reference inventory for the whole package | All preceding applicable items; OQ-8 | `[ ] APPROVED` `[ ] REJECTED` `[ ] DEFERRED` `[ ] PENDING` |

**No disposition is preselected.**

## D. Dependency table

Extracted from the register and the discovery record. **No dependency is invented.**

| Item | Blocked on | Dependency type | Human/regulatory? | Code-derived? | Current status |
|---|---|---|---|---|---|
| **11** | OQ-4, OQ-8 | Open question constraining approval | **Yes** — OQ-8 is a regulatory mapping | Partly — capability built by 5A-P1 | OQ-8 **unresolved** |
| **12** | OQ-8 | Open question constraining approval | **Yes** | Partly — governed allow-list exists | OQ-8 **unresolved** |
| **14** | Items 12–13 | Prerequisite items | No — derivation is mechanical | **Yes** — registry-fixed, `build_graph()` | Blocked; 12 and 13 both PENDING |
| **20** | All preceding applicable items; OQ-8 | Gate-closing sign-off | **Yes** | No | PENDING |

**No other item carries a dependency recorded in the register.** That does not
make any of them independent of the gate — Item 20 depends on all of them.

> **OQ-8 stays separately visible** and is not folded into any item. The register
> carries it as a constraint that *“must be read before approving”* Item 11 or 12.
> Its substance: which `AssessmentSnapshot` governs execution-level `iid.*`
> values. A snapshot is scoped to one formulation **component**, while
> applicability and FDA-derived defaults are properties of the **execution**.

## E. Engineering fact versus regulatory decision

**Mandatory distinction, applied to every item below.** Code capability must
never be mistaken for regulatory approval.

| | |
|---|---|
| **ENGINEERING FACT** | What the repository already enforces or supports. Verifiable by reading code |
| **REGULATORY / HUMAN DECISION** | What an accountable owner must still decide. Not derivable from code at all |

> An item whose engineering capability is complete is **not** thereby closer to
> approved. Items 11, 12 and 18 are the clearest cases: the register records
> their capability limits as **resolved by 5A-P1**, and all three are still
> **PENDING**. Capability was the blocker to *asking* the question, not the
> answer to it.

## F. Citation requirements

Measured from the register:

| Citation requirement | Items | Count |
|---|---|---:|
| **Required (Yes)** | 1, 3, 4, 5, 7, 11, 12, 13 | **8** |
| **Not required (No)** | 2, 8, 9, 14 | **4** |
| **Conditional / scoped** | 6, 10, 15, 16, 17, 18, 19, 20 | **8** |

For every item where a citation is required, or conditionally required and the
content is guidance-derived, **all** of the following are required:

| Field | Value |
|---|---|
| Source title | |
| Source organization | |
| Source version | |
| Effective / publication date | |
| Exact section / page / table | |
| Market / jurisdiction | |
| Applicability rationale | |
| Supersession check | |
| Approval evidence | |

> ### “FDA”, “ICH”, “USP” or “per guideline” is not a citation.
> 
> Naming a body names an author, not a passage. Without an exact source, version
> and location, a decision cannot be re-verified when the source changes and
> cannot be audited. **This document supplies no citations.**

---

# G. Item-by-item decision sections

Register wording is preserved. **No decision field is pre-filled.**

## Item 1 — Which `ChecklistDefinition` templates ship

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — the wrong set means the wrong products are assessed |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes** |
| Evidence required | Scope-decision worksheet per candidate (template §5), source guidance per candidate |
| Completion criterion | Worksheet complete and signed for every candidate |
| **ENGINEERING FACT** — engineering dependency | None — this is the first gate; everything else depends on it |
| **ENGINEERING FACT** — validation rule | Every candidate resolved `INCLUDE`/`EXCLUDE`/`DEFER`; ≥ 1 `INCLUDE` for the gate to produce loadable content |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 2 — Checklist title per definition

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | LOW |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | No |
| Evidence required | None beyond the definition's own scope decision |
| Completion criterion | Title present for every `INCLUDE`d definition |
| **ENGINEERING FACT** — engineering dependency | ≤ 255 chars (`models.py:57`) |
| **ENGINEERING FACT** — validation rule | Non-blank, ≤ 255 chars |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 3 — Jurisdiction

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — the wrong jurisdiction invalidates every question under it |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes** |
| Evidence required | Statement of jurisdiction and its basis |
| Completion criterion | Jurisdiction stated per definition (storage settled by `5A-DEC-005`) |
| **ENGINEERING FACT** — engineering dependency | ✅ `ChecklistVersion.jurisdiction`, controlled vocabulary, lifecycle-frozen, checksum-covered (`5A-DEC-005`). Vocabulary is `US_FDA` only; another jurisdiction requires a governed decision, not a code change |
| **ENGINEERING FACT** — validation rule | Stated explicitly per definition; never inferred |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 4 — Regulatory basis

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes** |
| Evidence required | §4 source records |
| Completion criterion | Basis stated and cited per definition |
| **ENGINEERING FACT** — engineering dependency | ≤ 500 chars (`models.py:110`) |
| **ENGINEERING FACT** — validation rule | Non-blank for production content; ≤ 500 chars |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 5 — Source guidance, version, publication date

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — an uncitable decision cannot be defended in audit |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes — this item *is* the citation requirement** |
| Evidence required | Complete §4 record per source |
| Completion criterion | Source inventory complete; every guidance-derived decision references one |
| **ENGINEERING FACT** — engineering dependency | Reproducibility (§18): content answerable without re-querying live data |
| **ENGINEERING FACT** — validation rule | Every §4 field present; `reference_locator` precise, not document-level |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 6 — Section structure and ordering

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | MEDIUM — ordering affects reviewer flow and export order |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | Where guidance-derived |
| Evidence required | Rationale where structure follows a guidance structure |
| Completion criterion | Every section titled, coded, ordered, with criticality |
| **ENGINEERING FACT** — engineering dependency | Section code unique per version; `display_order` unique per version (`models.py:290-295`) |
| **ENGINEERING FACT** — validation rule | Codes match grammar; order values unique and complete |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 7 — Question text (verbatim)

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH — the highest in the register** |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes** |
| Evidence required | §4 source record per question, or declared organizational policy |
| Completion criterion | Every question has text authored by the regulatory author |
| **ENGINEERING FACT** — engineering dependency | `TextField`, no length cap (`models.py:319`) |
| **ENGINEERING FACT** — validation rule | Non-blank. **Engineering performs no wording check of any kind.** |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 8 — Question codes / public identifiers

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | MEDIUM — codes are regulatory-facing in exports |
| Owner class | JOINT REGULATORY + ENGINEERING |
| Owner | Regulatory + Engineering (unchanged) |
| Citation required? | No |
| Evidence required | Coding convention statement |
| Completion criterion | Every question coded; no collision; reserved codes present where required |
| **ENGINEERING FACT** — engineering dependency | Grammar `^[A-Z0-9][A-Z0-9_-]*$`, ≤ 100 chars, normalized (`codes.py:12-14`); unique **per section** (`models.py:351`); **version-wide unique if used as a calculation binding target** (`activation_validation.py:14-18`) |
| **ENGINEERING FACT** — validation rule | Grammar + length + uniqueness; reserved codes honoured |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 9 — Answer type per question

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — the answer type determines what a reviewer may record |
| Owner class | JOINT REGULATORY + ENGINEERING |
| Owner | Regulatory + Engineering (unchanged) |
| Citation required? | No |
| Evidence required | `answer_shape_intent` in plain language from Regulatory; mapping rationale from Engineering; **Regulatory confirmation of the mapping** |
| Completion criterion | Every question mapped **and the mapping confirmed by Regulatory** |
| **ENGINEERING FACT** — engineering dependency | 18 values (`enums.py:58`); `ALLOWED_MATRIX` closed (`compatibility.py:14`); enforced in `models.py:362` |
| **ENGINEERING FACT** — validation rule | Pair present in `ALLOWED_MATRIX`; `quantity_with_unit` ⟹ non-empty `allowed_units` (`services.py:401`) |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 10 — Required vs optional

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — a wrongly-optional question lets an execution be approved without it |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | Where guidance-derived |
| Evidence required | Rationale where a guidance expectation is mandatory |
| Completion criterion | Every question has an explicit value |
| **ENGINEERING FACT** — engineering dependency | `required` boolean, default `False` (`models.py:329`); drives completeness gating |
| **ENGINEERING FACT** — validation rule | Explicit per question — never defaulted by engineering |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 11 — Applicability rules

| Register field | As recorded |
|---|---|
| Current status | **PENDING** — capability limit resolved by `5A-DEC-004` |
| Interpretation risk | **HIGH** — applicability decides whether a question must be answered at all |
| Owner class | REGULATORY-AUTHORED (intent); engineering encodes |
| Owner | Regulatory (unchanged) |
| Citation required? | **Yes** |
| Evidence required | Plain-language applicability intent + §4 citation |
| Completion criterion | Intent stated, encodable within the six fields, **and OQ-4 resolved** |
| **ENGINEERING FACT** — engineering dependency | Only six rule fields exist (`field_registry.py:14`); depth ≤ 5, ≤ 50 leaves, ≤ 8 KiB (`applicability.py:15-17`); rules immutable once approved (`models.py:212`) |
| **ENGINEERING FACT** — validation rule | `validate_condition_json()` passes against registry version 1 |
| Blocked on | OQ-4, OQ-8 |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 12 — `FDA_DERIVED_DEFAULT` bindings

| Register field | As recorded |
|---|---|
| Current status | **PENDING** — capability limit resolved by `5A-DEC-001` |
| Interpretation risk | **HIGH** — a wrong source field puts a wrong regulated value in front of a reviewer |
| Owner class | JOINT REGULATORY + ENGINEERING |
| Owner | Regulatory + Engineering (unchanged) |
| Citation required? | **Yes** |
| Evidence required | Which FDA field feeds which question, and why that field is the correct source |
| Completion criterion | Binding stated and naming an approved resolver identifier |
| **ENGINEERING FACT** — engineering dependency | ✅ Governed allow-list resolver layer (`5A-DEC-001`): `answer_sources.py`, provenance on the response, explicit failure statuses |
| **ENGINEERING FACT** — validation rule | Classification and answer-type pair allowed; **the binding identifier is validated against the approved registry at authoring time** and refused again at resolution |
| Blocked on | OQ-8 |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 13 — `SYSTEM_CALCULATED` bindings

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — the wrong calculation produces a wrong regulated number |
| Owner class | JOINT REGULATORY + ENGINEERING |
| Owner | Regulatory + Engineering (unchanged) |
| Citation required? | **Yes** |
| Evidence required | Which calculation applies to which question, and the regulatory reason |
| Completion criterion | Every calculated question bound to an approved identifier |
| **ENGINEERING FACT** — engineering dependency | **Exactly six** identifiers (`calculation_registry.py:218`); binding required for `system_calculated` and forbidden otherwise (`models.py:376-384`); reserved codes per §3.3 of the discovery |
| **ENGINEERING FACT** — validation rule | Identifier ∈ the six; answer type and classification match the registry entry; activation validation passes (`activation_validation.py:589`) |
| Blocked on | — none recorded |

> **Items 13 and 14 have their own package — do not duplicate it here.**
> Complete [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md), which carries the per-question binding table, the
> six-identifier limit, the no-seventh-formula boundary, the OQ-8 dependency
> and the separation from SOW 2.3. The fields below record only the
> resulting decision and its approval evidence.

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 14 — Calculation dependencies / ordering

| Register field | As recorded |
|---|---|
| Current status | **PENDING** (blocked on 12–13) |
| Interpretation risk | LOW — derived, not authored |
| Owner class | REGULATORY-APPROVED / ENGINEERING-DERIVED |
| Owner | Engineering, derived from items 12–13 (unchanged) |
| Citation required? | No |
| Evidence required | Derivation output; graph validation result |
| Completion criterion | Graph validates for every `INCLUDE`d definition |
| **ENGINEERING FACT** — engineering dependency | Dependencies are **registry-fixed**, not authored; depth ≤ 5, nodes ≤ 10 (`calculation_registry.py:35-36`) |
| **ENGINEERING FACT** — validation rule | `build_graph()` reports no cycle, no depth or node-limit breach, no unknown dependency code |
| Blocked on | Items 12–13 (register: “blocked on 12–13”) |

> **Items 13 and 14 have their own package — do not duplicate it here.**
> Complete [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md), which carries the per-question binding table, the
> six-identifier limit, the no-seventh-formula boundary, the OQ-8 dependency
> and the separation from SOW 2.3. The fields below record only the
> resulting decision and its approval evidence.

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 15 — Help / guidance text

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — help text steers how a reviewer answers |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | Where guidance-derived |
| Evidence required | §4 record where the text paraphrases guidance |
| Completion criterion | Present or explicitly declared not required, per question |
| **ENGINEERING FACT** — engineering dependency | `TextField`, blank allowed (`models.py:320`) |
| **ENGINEERING FACT** — validation rule | None mechanical |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 16 — Reviewer expectations per question

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** — this defines the review standard |
| Owner class | REGULATORY-AUTHORED |
| Owner | Regulatory (unchanged) |
| Citation required? | Where guidance-derived |
| Evidence required | Statement of what the reviewer must satisfy themselves of |
| Completion criterion | Expectation stated per question **and its storage location agreed** |
| **ENGINEERING FACT** — engineering dependency | ⚠ **No dedicated model field.** Nearest are `help_text` and `regulatory_reference`; `reviewer_confirmation_required` is a boolean only |
| **ENGINEERING FACT** — validation rule | `reviewer_confirmed` ⟹ `reviewer_confirmation_required = true` (forced, `models.py:398`) |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 17 — Override eligibility per question

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | MEDIUM |
| Owner class | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") |
| Owner | Regulatory expectation, within a fixed engineering floor |
| Citation required? | Where guidance-derived |
| Evidence required | Expectation statement per question |
| Completion criterion | Expectation recorded and confirmed consistent with the floor |
| **ENGINEERING FACT** — engineering dependency | **Only `fda_derived_default` is overridable** (`overrides.py:188`); permission `PERM_OVERRIDE_EXECUTION` — Reviewer and VP, never Doer (`permissions.py`); **no clear-override path** (APPROVED-DEFERRED) |
| **ENGINEERING FACT** — validation rule | Any expectation contradicting the floor is a **blocking finding**, not a configuration |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 18 — Export inclusion per question

| Register field | As recorded |
|---|---|
| Current status | **PENDING** — settled by `5A-DEC-003`; confirmation only |
| Interpretation risk | MEDIUM |
| Owner class | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") |
| Owner | Regulatory intent; engineering feasibility |
| Citation required? | Where guidance-derived |
| Evidence required | Any exclusion requirement and its rationale |
| Completion criterion | Confirm that full governed inclusion is acceptable (`5A-DEC-003`) |
| **ENGINEERING FACT** — engineering dependency | ⚠ **No inclusion/exclusion mechanism exists.** Export covers **every** response of an approved execution (`controlled_export.py:453`), inside the SHA-256 checksum; only `approved` executions are exportable (`controlled_export.py:96`) |
| **ENGINEERING FACT** — validation rule | `5A-DEC-003` decided full governed inclusion for the first production release. An exclusion request is deferred to a later governed change, not a 5A blocker |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 19 — Version number and effective date

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | MEDIUM — effective date determines which version governs an assessment |
| Owner class | ⚠ **REGULATORY-APPROVED / ENGINEERING-DERIVED** (4D-4 table: "Regulatory") |
| Owner | Regulatory sets effective date; version number is allocated by the engine and confirmed |
| Citation required? | Where guidance-derived |
| Evidence required | Effective-date rationale |
| Completion criterion | Effective date approved; version number confirmed after allocation |
| **ENGINEERING FACT** — engineering dependency | `version_number` unique per definition (`models.py:157`), allocated by the governed creation path; `effective_date` / `expiry_date` are nullable dates (`models.py:108-109`) |
| **ENGINEERING FACT** — validation rule | Version numbering follows the governed sequence; effective date consistent with the approval date |
| Blocked on | — none recorded |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

## Item 20 — Formal sign-off

| Register field | As recorded |
|---|---|
| Current status | **PENDING** |
| Interpretation risk | **HIGH** |
| Owner class | FORMAL SIGN-OFF |
| Owner | Regulatory authority holding IIG guidance interpretation authority (unchanged) |
| Citation required? | Source-reference inventory for the whole package |
| Evidence required | All elements in the table below |
| Completion criterion | **This item closes the gate** |
| **ENGINEERING FACT** — engineering dependency | Engineering supplies commit SHA, checksum and the compatibility result — **and signs nothing** |
| **ENGINEERING FACT** — validation rule | Every element present; checksum matches the signed files |
| Blocked on | All preceding applicable items; OQ-8 |

**Exact unresolved decision:**

| Field | Value |
|---|---|
| What must be decided | |
| **Why engineering cannot decide it** | |
| Required source / citation | |
| Source version / date | |
| Exact section / page | |
| Jurisdiction / market | |
| Regulatory rationale | |
| Owner | |
| Evidence | |
| Effective version / date | |

**Decision:** `[ ] APPROVE`  `[ ] REJECT`  `[ ] DEFER`

**Dependencies satisfied?** `[ ] YES`  `[ ] NO`  `[ ] NOT APPLICABLE`

**Completion criterion met?** `[ ] YES`  `[ ] NO`

---

# H. Item 20 — formal sign-off and gate closure

> ### Item 20 must not be marked approved merely because engineering is complete.
> 
> It is the signature that closes the gate, not a status that follows from
> readiness. Engineering completeness is not one of its inputs.

**All preceding applicable items approved?** `[ ] YES`  `[ ] NO`

**Approval evidence complete?** `[ ] YES`  `[ ] NO`

**Citations complete?** `[ ] YES`  `[ ] NO`

**Outstanding interpretation questions?** `[ ] YES`  `[ ] NO`

**Outstanding OQs?** `[ ] YES`  `[ ] NO`

| Field | Value |
|---|---|
| Named regulatory authority | |
| Formal sign-off reference | |
| Signed / effective date | |

**Gate decision:** `[ ] AUTHORISE PRODUCTION REGULATORY CONTENT`  
`[ ] DO NOT AUTHORISE`  `[ ] DEFER`

## I. Gate status rule

A governance rule, not code. **No gate logic is implemented by this document.**

> **The gate remains OPEN unless all three hold:**
> 
> 1. every required Item 1—20 is genuinely approved according to the source register;
> 2. required evidence and citations are present;
> 3. Item 20 formal sign-off exists.

| Field | To be completed |
|---|---|
| Approved | ____ / 20 |
| Pending | ____ / 20 |
| Rejected | ____ / 20 |
| Deferred | ____ / 20 |
| Gate | `[ ] OPEN`  `[ ] CLOSED` |

The **current observed state** is in §A and is a snapshot of the register, not
a decision recorded here.

## J. Content authoring boundary

> ### This package does not author regulated checklist content.

Until the register gate is formally closed:

* **no production regulatory checklist content may be activated;**
* **no PENDING decision may be converted into a product rule by engineering;**
* **no regulatory citation may be invented;**
* **no interpretation may be inferred from examples or guidance alone.**

Draft, demo and test content must stay clearly separate from production
regulatory content, and neither the existence nor the passing of demo content
bears on any item above.

## K. Handoff workflow

The controlled human sequence. **No workflow code is implemented.**

| Step | Action |
|---|---|
| 1 | Regulatory owner reviews the item |
| 2 | Source / citation attached where required |
| 3 | Decision and rationale recorded |
| 4 | Dependencies verified |
| 5 | **Engineering verifies implementability only** |
| 6 | Approval evidence attached |
| 7 | Register status updated by the authorised process |
| 8 | Next dependent item may proceed |
| 9 | Item 20 formal sign-off, only after all prerequisites |
| 10 | Production-content activation handled separately, after gate closure |

> Step 5 is the one most easily overstepped. Engineering confirms a decision
> *can be implemented as written*. It does not confirm the decision is correct.

## L. Rejection criteria

Return the package if any of these occur.

| Rejected | Why |
|---|---|
| **Owner unnamed where required** | A role cannot approve; the register requires a named authority |
| **Citation-required item has no exact citation** | Cannot be re-verified or audited |
| **Rationale says only “industry standard”** | Asserts consensus in place of a source |
| **Engineering chose a regulatory interpretation** | The failure this entire package exists to prevent |
| **Dependencies ignored** | Approving 14 before 12—13, or 11/12 while OQ-8 is open |
| **Item 20 signed early** | Gate closure without its prerequisites is not closure |
| **Approval asserted without evidence** | “Approved” without the approval is not an approval |
| **Register state in package differs from source** | The package must reconcile to the register, not replace it |
| **Formula/binding content exceeds the approved six-function scope** | `SCOPE-OUT-18` is unlifted |
| **SOW 2.3 conflated with Item 13** | Different scopes, different approvals — see [APPROVAL_REGISTER_13_14_DECISION_INTAKE.md](APPROVAL_REGISTER_13_14_DECISION_INTAKE.md) |
| **OQ-8 silently assumed resolved** | It constrains Items 11, 12 and 20 |
| **Part 11 compliance asserted** | No such claim is made anywhere in this repository |
| **Production readiness claimed before gate closure** | The gate is the definition of readiness for this content |

## M. What this document does not do

It approves nothing and changes no register status. It does not modify
[MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md), any
question definition, the calculation registry, any binding or any activation
rule. It authors no checklist content, writes no citation, names no authority,
and implements no gate logic or workflow code. The count it reports —
**0 of 20** — was read from the register and is unchanged by anything here.

## N. Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** An immutable audit mechanism is not
   compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source, and the calculation tests are engineering
   evidence, not validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
