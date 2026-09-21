# Approval Register Items 13 and 14 — Decision Intake

> **What this is:** a blank decision package for a named regulatory authority and
> an engineering verifier, covering Approval Register **Item 13**
> (`SYSTEM_CALCULATED` bindings) and **Item 14** (calculation dependencies and
> ordering).
> **What this is not:** an approval, a binding selection, a citation, or
> production checklist content. **This document approves nothing, changes no
> approval count, and modifies neither the approval register nor any question
> definition, calculation binding or activation rule.**
> **Verified at** `regx-main` `d7d49780447b5784e74874ea490017d5c69c6d22`. Register
> state and all engineering facts were **re-read from source at this SHA**.
> **Companions:** [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md),
> [MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md),
> [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md),
> [CALCULATOR_SPECIFICATION_INTAKE.md](CALCULATOR_SPECIFICATION_INTAKE.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md),
> [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md)

## 0. Register state, re-read at this SHA

| Observed | Value |
|---|---|
| Production regulatory content gate | **OPEN — 0 of 20 approved** |
| Items with status `PENDING` | **20** |
| Items with status `APPROVED` | **0** |
| **Item 13** — `SYSTEM_CALCULATED` bindings | **PENDING** |
| **Item 14** — Calculation dependencies / ordering | **PENDING** (blocked on 12–13) |

**No status is changed by this document.** The count advances only when a named
regulatory authority supplies a real approval, and is not advanced by document
completeness, engineering readiness or milestone progress.

## 1. The division of labour this package rests on

> ### Engineering may validate a chosen binding.
> ### Engineering may not choose the binding.

**What engineering knows**, verified in code at this SHA:

| Fact | Value / source |
|---|---|
| Approved calculation identifiers | **Exactly six** (`calculation_registry.py:218`) |
| Binding **required** for `SYSTEM_CALCULATED` | `models.py:446` — *"SYSTEM_CALCULATED questions require a calculation_binding_identifier."* |
| Binding **forbidden** otherwise | `models.py:438` — *"calculation_binding_identifier may only be set when data_source_classification is SYSTEM_CALCULATED."* |
| Registry-known identifiers only | `activation_validation.py:568` resolves via `get_entry(...)`; an unknown identifier does not resolve |
| Dependency graph validation | `calculation_graph.py:95` `build_graph()`; `ERROR_DEPENDENCY_CYCLE`, depth and cascade checks |
| Depth limit | `CALCULATION_MAX_DEPENDENCY_DEPTH = 5` |
| Cascade node limit | `CALCULATION_MAX_CASCADE_NODES = 10` |

**What engineering does not know, and must not infer:** *which regulated question
should use which formula, and on what regulatory basis.* Nothing in the code
carries that mapping, and deriving it from a question's wording would be
engineering choosing a regulatory parameter.

### 1.1 The six approved identifiers and what each consumes

Enumerated from the live registry, not transcribed:

| # | Identifier | Primary input source |
|---|---|---|
| 1 | `percentage_w_w` | `SOURCE_FORMULATION_FIELD` |
| 2 | `daily_exposure` | `SOURCE_MAXIMUM_DAILY_UNITS` |
| 3 | `percentage_of_iid_potency` | **`SOURCE_ASSESSMENT_SNAPSHOT`** (`selected_iid_potency_amount`) |
| 4 | `difference_from_iid_potency` | **`SOURCE_ASSESSMENT_SNAPSHOT`** (`selected_iid_potency_amount`) |
| 5 | `percentage_of_iid_mde` | **`SOURCE_ASSESSMENT_SNAPSHOT`** (`selected_iid_mde`) |
| 6 | `difference_from_iid_mde` | **`SOURCE_ASSESSMENT_SNAPSHOT`** (`selected_iid_mde`) |

> ## ⚠ Four of the six identifiers read snapshot values
>
> **Identifiers 3–6 consume `iid.*` values that come from an
> `AssessmentSnapshot`.** That makes **OQ-8 (§4) a direct gate on two-thirds of
> the available binding options**, not a side question to be settled later.
>
> Binding a question to identifier 3, 4, 5 or 6 while OQ-8 is unresolved produces
> a binding whose input source is undefined. Identifiers 1 and 2 do not have this
> dependency.

---

# Section 1 — Item 13: `SYSTEM_CALCULATED` bindings

**Current status: PENDING.** Unchanged by this document.

**Interpretation risk: HIGH** — *"the wrong calculation produces a wrong regulated
number."*

## 1.2 Decision table — one row per proposed `SYSTEM_CALCULATED` question

**Copy this block once per question. Nothing is preselected.**

| Field | Value |
|---|---|
| Question ID | |
| Question text / reference | |
| Dosage form / scope | |
| Regulatory use case | |

**Approved calculation identifier — select exactly one:**

`[ ] percentage_w_w`
`[ ] daily_exposure`
`[ ] percentage_of_iid_potency`
`[ ] difference_from_iid_potency`
`[ ] percentage_of_iid_mde`
`[ ] difference_from_iid_mde`
`[ ] NONE / NOT APPLICABLE`

| Field | Value |
|---|---|
| Regulatory rationale | |
| Primary source / citation | |
| Source version / date | |
| Exact section / page | |
| Input-data source | |
| Required `AssessmentSnapshot` / execution context | |

**Binding applies to:**

`[ ] all relevant products`  `[ ] dosage-form specific`  `[ ] route specific`
`[ ] market specific`  `[ ] other — describe`

| Field | Value |
|---|---|
| Regulatory owner | |
| Engineering reviewer | |

**Decision:** `[ ] APPROVE BINDING`  `[ ] REJECT BINDING`  `[ ] DEFER`
`[ ] NOT APPLICABLE`

| Field | Value |
|---|---|
| Evidence / approval reference | |
| Effective version / date | |

> If the selected identifier is **3, 4, 5 or 6**, the *Required `AssessmentSnapshot`
> / execution context* row cannot be completed until §4 is decided. A row left
> blank there is an incomplete binding, not an approved one.

---

# Section 2 — Item 13 completion criteria

> ### Item 13 is NOT complete merely because six calculations exist.
>
> The engine existing is an engineering fact. Item 13 is a regulatory mapping,
> and no amount of engine completeness advances it.

**All of the following are required:**

| # | Criterion |
|---|---|
| 1 | **Every** `SYSTEM_CALCULATED` question identified |
| 2 | Every such question **either** bound to one approved identifier **or** explicitly declared not applicable |
| 3 | Regulatory rationale present for each |
| 4 | Source / citation present for each |
| 5 | Input source defined |
| 6 | Execution / snapshot context defined (§4) |
| 7 | Owner named — a person, not a role |
| 8 | Approval evidence present — the approval itself |
| 9 | **No unknown identifier** — every binding resolves in the registry |
| 10 | **No seventh formula introduced** |

> ### Engineering may validate a chosen binding.
> ### Engineering may not choose the binding.
>
> Engineering can confirm that an identifier exists, that the answer type and
> classification match the registry entry, and that activation validation passes.
> It cannot confirm that the chosen calculation is the regulatorily correct one
> for the question — that judgement is the substance of Item 13.

---

# Section 3 — Item 14: calculation dependencies / ordering

**Current status: PENDING (blocked on 12–13).** Unchanged by this document.

**Interpretation risk: LOW** — derived, not authored.

**Engineering fact:** dependency behaviour is **registry-fixed and code-derived**.
`build_graph()` (`calculation_graph.py:95`) validates cycles, depth
(≤ `CALCULATION_MAX_DEPENDENCY_DEPTH` = 5) and cascade size
(≤ `CALCULATION_MAX_CASCADE_NODES` = 10).

> **Item 14 should not invent dependency ordering manually.** The registry already
> defines dependencies; Item 14 records the *derivation output and its validation
> result*. It is the one item in this package that is genuinely mechanical — once
> Item 13 is approved.

## 3.1 Per applicable question / binding

| Field | Value |
|---|---|
| Applicable question / binding | |

**Item 13 binding approved?** `[ ] YES`  `[ ] NO`

| Field | Value |
|---|---|
| Required upstream inputs | |
| Resolved registry dependencies | |

**Graph validation result:** `[ ] PASS`  `[ ] FAIL`  `[ ] REVIEW REQUIRED`  `[ ] NOT RUN`

**Cycle detected?** `[ ] YES`  `[ ] NO`  `[ ] NOT RUN`

**Depth within allowed engineering limit?** `[ ] YES`  `[ ] NO`  `[ ] NOT RUN`

**Node count within allowed engineering limit?** `[ ] YES`  `[ ] NO`  `[ ] NOT RUN`

**Ordering derived from registry?** `[ ] YES`  `[ ] NO`

**Manual dependency override requested?** `[ ] YES`  `[ ] NO`

> ### If a manual dependency override is requested: **STOP.**
>
> A manual override departs from registry-fixed dependencies and is **separate
> approved engineering scope**. It is not part of Item 14 and is not authorised by
> approving Item 14.

| Field | Value |
|---|---|
| Regulatory / content owner | |
| Engineering verifier | |
| Evidence | |

**Decision:** `[ ] APPROVE DERIVED DEPENDENCY/ORDERING`  `[ ] REJECT`  `[ ] DEFER`

---

# Section 4 — OQ-8: snapshot / source-binding governance

> **Deliberately not folded into Item 13.** It is a separate unresolved question
> with its own owner, and §1.1 shows it gates four of the six identifiers.

## 4.1 Current unresolved status, as recorded

**OQ-8:** *which `AssessmentSnapshot` governs execution-level `iid.*` values?*

Confirmed in code at this SHA: `AssessmentSnapshot` carries
`formulation_component_public_id` — it is **scoped to one formulation
component** — while applicability and FDA-derived defaults are properties of the
**execution**. **No approved specification says which component's snapshot
governs**, or whether one must be created during a population pass.

Owner recorded in the discovery: **Regulatory + Engineering lead.**

## 4.2 Current fail-closed behaviour while unresolved

**Conservative, and never silent:**

| Condition | Behaviour |
|---|---|
| Applicability rule reads any `iid.*` field | Evaluates to **`review_required`** with reason code `APPLICABILITY_SOURCE_UNRESOLVED` — *not* the false branch |
| FDA-derived binding with unavailable provenance | Resolves to explicit **`source_unavailable`** |

> *"We could not find out" is not the same answer as "no".* That distinction is
> the current behaviour and should be preserved by whatever rule replaces it.

## 4.3 Decisions required

| Question | Decision |
|---|---|
| **Exact snapshot-selection rule** | |
| May an FDA-derived binding be used when source provenance is unavailable? | |
| Is a "latest snapshot" ever allowed, and under exactly what conditions? | |
| Version / provenance requirement | |
| Superseded snapshot behaviour | |
| Must a snapshot be created during a population pass? | |

> ### "Latest" is not proposed here and must not be assumed.
>
> Selecting the most recent snapshot is a regulatory choice about which precedent
> record answers a regulated question. It is not a tie-break, and it is not a
> sensible default — it is one candidate rule among several, and it needs the same
> rationale and evidence as any other.

| Field | Value |
|---|---|
| Owner | |
| Evidence | |

**Decision:** `[ ] APPROVED`  `[ ] DEFERRED`  `[ ] NOT APPLICABLE`

---

# Section 5 — Binding source provenance

**Required for each approved binding.** Complete one block per binding.

| Field | Value |
|---|---|
| Source title | |
| Publishing body / client owner | |
| Source version | |
| Effective date | |
| Exact section / page | |
| Jurisdiction / market | |
| Rationale for applicability | |
| Approval evidence | |
| Supersession handling | |

> ### "Per FDA" / "per ICH" / "per USP" is not a citation.
>
> A citation without an exact source, version and location cannot be re-verified
> when the source changes, and cannot be audited. Naming a body names an author,
> not a passage. This is a rejection condition (see below).

---

# Section 6 — Item 13 versus SOW 2.3

**These are different things and must not be conflated.**

| | **Approval Register Item 13** | **SOW 2.3 calculator intake** |
|---|---|---|
| Concerns | Mapping regulated questions to the **existing six** approved identifiers | Possible **new** calculators — dissolution, impurity, stability/shelf-life |
| Nature | A regulatory mapping decision | A formula specification **plus** separate engineering scope approval |
| Document | This one | [CALCULATOR_SPECIFICATION_INTAKE.md](CALCULATOR_SPECIFICATION_INTAKE.md) |

**Approving Item 13:**

* does **NOT** authorise a seventh calculation;
* does **NOT** approve any SOW 2.3 formula;
* does **NOT** lift `SCOPE-OUT-18` (*"New calculation formulas beyond the six
  approved functions | Never in 4D"*).

**Approving SOW 2.3:**

* does **NOT** complete Item 13 automatically. A new calculator would create new
  questions needing their own bindings, rationale and citations.

---

# Section 7 — Gate impact

**Current gate, re-read at this SHA: OPEN — 0 of 20 approved.**

| If this happens | The gate becomes |
|---|---|
| Item 13 approved | **1 of 20** |
| Item 14 approved | **1 of 20** |
| Both approved | **2 of 20** |

* **Item 13 approval advances only Item 13.**
* **Item 14 approval advances only Item 14.**
* Even with both approved, the production regulatory content gate **remains
  open** until all twenty items are approved **and Item 20 (formal sign-off) is
  signed**.

> ### Completing Items 13 and 14 is not production readiness.
>
> No production regulatory checklist content may be authored, loaded or activated
> until Item 20 is signed. Representing 13/14 completion as readiness would
> misstate the gate by eighteen items and a signature.

---

# Section 8 — Human decision summary

**No box is preselected.**

**Item 13:** `[ ] APPROVED`  `[ ] PENDING`  `[ ] REJECTED`  `[ ] DEFERRED`

**Item 14:** `[ ] APPROVED`  `[ ] PENDING`  `[ ] REJECTED`  `[ ] DEFERRED`

**OQ-8 / snapshot governance:** `[ ] APPROVED`  `[ ] PENDING`  `[ ] NOT APPLICABLE`

| Field | Value |
|---|---|
| Named regulatory authority | |
| Engineering verifier | |
| Approval evidence | |
| Effective version / date | |

> The register states the count *"changes only when a named regulatory authority
> supplies a real approval."* An unnamed authority cannot supply one.

---

## Engineering handoff criteria

Engineering may proceed only when **all** of the following hold:

| # | Required |
|---|---|
| 1 | Item 13 binding decisions exist |
| 2 | Exact approved identifiers selected — one of the six, per question |
| 3 | Citations and rationales exist |
| 4 | Source provenance complete (§5) |
| 5 | **Snapshot / execution context resolved** (§4) — required for identifiers 3–6 |
| 6 | Owner named |
| 7 | Approval evidence exists |
| 8 | Item 14 derivation can be run **mechanically** from the registry |
| 9 | **No unknown or new formula introduced** |

## Engineering rejection criteria

Return the package if any of these occur.

| Rejected | Why |
|---|---|
| **Formula chosen because it "looks right"** | Plausibility is not a regulatory rationale; this is the HIGH interpretation-risk case |
| **Question text alone used as rationale** | Restates the question rather than justifying the mapping |
| **Citation says only "FDA", "ICH", "USP"** | Names a body, not a passage; cannot be re-verified or audited |
| **Source version missing** | A binding that cannot be tied to a revision cannot be re-checked when the source changes |
| **Snapshot context unspecified** | Four of six identifiers read snapshot values; the input source would be undefined |
| **"Latest" chosen without an approved rule** | Which precedent answers a regulated question is a regulatory choice, not a tie-break |
| **Seventh formula requested under Item 13** | `SCOPE-OUT-18` is unlifted; that is separate approved engineering scope |
| **Dependencies manually invented** | Dependencies are registry-fixed; a manual override is separate scope (§3.1) |
| **Item marked approved without evidence** | "Approved" without the approval is not an approval |
| **13/14 completion represented as closing the 20-item gate** | Misstates the gate by eighteen items and a signature |

## Boundaries preserved

* **No regulatory interpretation by engineering.**
* **No seventh calculation** — the registry holds exactly six and is unchanged.
* **No content activation**, and **no production checklist authoring**.
* **No 21 CFR Part 11 claim.**
* **No validated-production claim for the calculation engine.**
* **No regulatory conclusion from any gap report.**

## What this document does not do

It approves nothing and changes no approval status. It does not modify
[MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md), any
question definition, the calculation registry, any binding, or any activation
rule. It selects no identifier, writes no citation, proposes no snapshot-selection
rule, and names no authority. The gate count it reports — **0 of 20** — was read
from the register, and is not altered by anything here.

## Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** An immutable audit mechanism is not
   compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source, and the calculation tests are engineering
   evidence, not validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
