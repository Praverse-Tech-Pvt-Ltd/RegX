# SOW 2.3 — Calculator Specification Intake

> **What this is:** a blank input form for the client / regulatory content owner
> to complete. Completing it is what unblocks SOW 2.3 calculator implementation.
> **What this is not:** a specification, a phase, an approval, or engineering
> work. **No formula, equation, operator, worked example, threshold, limit or
> acceptance criterion appears anywhere in this document, and none may be added
> to it by engineering.** No rounding rule is proposed for any calculator: the
> single rounding value quoted (§2) is the existing engine's own recorded
> behaviour, cited precisely so that nothing is assumed to be inherited from it.
> Every value cell is deliberately empty.
> **Prepared at** `regx-main` + [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md)
> (`cfbd9c5`). Engineering-contract facts below were read from code at that SHA.
> **Companions:** [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md),
> [IID_CALCULATION_RULES.md](IID_CALCULATION_RULES.md),
> [MILESTONE_4D_3_IMPLEMENTATION_SPEC.md](MILESTONE_4D_3_IMPLEMENTATION_SPEC.md)

> ## ⚠ Two approvals are required, and neither substitutes for the other
>
> ### 1. Formula / content specification approved? **YES / NO**
> ### 2. Engineering scope approved? **YES / NO**
>
> ## **BOTH must be YES before implementation starts.**
>
> A completed form with only the first is not authorisation. A scope approval
> with no completed form supplies no formula. See §H and
> [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §3.6.

## 1. Who completes this and why it cannot be completed by engineering

SOW 2.3 asks for three calculators — dissolution, impurity, stability/shelf-life.
**None exists, and none can be written from what the repository contains.** There
is no approved formula specification for any of them here or in the legacy
codebase, so writing one would mean engineering choosing a regulatory parameter.

That is the whole reason this form exists. It is an **owner/governance gap**, not
an engineering gap: adding engineering capacity changes nothing until the form
comes back completed and both approvals exist.

| Section | Completed by |
|---|---|
| A Identity, D Interpretation | Regulatory / content owner |
| B Formula, C Behaviour | Regulatory / content owner, with engineering available to clarify format |
| E Provenance | Regulatory / content owner |
| F Verification examples | Regulatory / content owner |
| G Governance | Regulatory / content owner **and** engineering scope approver |
| H Authorisation | Both approvers, independently |

**Engineering may format and validate. Engineering may never choose.** That is
the ownership rule already applied to the approval register
([MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md) §1) and
it applies here unchanged.

## 2. What engineering already provides, so you do not have to specify it

These are **platform facts read from code**, given so your answers land in the
right shape. They are constraints your answers must satisfy — **not answers, and
not defaults for any field below.**

| Constraint | Detail |
|---|---|
| Arithmetic | `Decimal` only. No floating point anywhere in a formula or unit conversion |
| Result shape | Every calculation returns `formula_identifier`, `formula_version`, `status`, `value`, `unit`, `inputs`, `input_provenance`, `rounding_rule`, `reason_code`, `generated_at` — **never a bare number** |
| Fail-closed | A calculation that cannot run returns a documented status and reason code. **Never a silently omitted value, never `0` standing in for "unknown"** |
| Canonical mass units | `microgram`, `milligram`, `gram`, `kilogram` |
| Canonical volume units | `microlitre`, `millilitre`, `litre` |
| Canonical count units | `tablet`, `capsule`, `unit`, `actuation`, `dose` |
| Existing reason-code vocabulary | `DATA_REQUIRED`, `FDA_VALUE_UNAVAILABLE`, `UNIT_MISMATCH`, `NOT_COMPARABLE`, `ROUTE_MISMATCH`, `DOSAGE_FORM_MISMATCH`, `INGREDIENT_UNRESOLVED`, `REGULATORY_REVIEW_REQUIRED` |
| Rounding is **not** inherited | The existing six formulas record `rounding_rule = "none (Decimal, unrounded)"`. **Your calculator's rounding must be stated explicitly in §C — there is no default to fall back on** |

> **Read the last row carefully.** Because the existing engine does not round, an
> unstated rounding rule does not quietly inherit a sensible one. It leaves the
> behaviour undefined, which is a rejection condition — see
> *Engineering rejection criteria*.

**Source:** `backend/iid_assessment/calculations.py`,
`backend/iid_assessment/unit_conversion.py`,
`backend/iig_checklist/calculation_registry.py:218`.

### 2.1 The precision an approved specification must reach

Stated structurally. **No formula, equation, operator, worked example, threshold
or limit appears here or anywhere else in this document — including from the
existing six-function engine.**

An approved calculator specification must identify:

* formula identifier
* formula version
* every variable
* variable role
* units
* operand relationship
* zero-denominator behaviour
* missing-input behaviour
* result unit
* rounding rule
* fail-closed conditions

**Engineering shall not infer any of these from prose, examples, spreadsheets,
regulatory guidance, or expected outputs.**

Each item is listed because leaving it unstated transfers the decision to
engineering. *Operand relationship* is the clearest case: naming the variables
does not say how they relate, and a specification that names them without fixing
that relationship has not been completed — it has been handed to engineering to
finish. **That is the standard §B and §C must meet.**

## 3. Relationship to the eleven-item list already published

[CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §3.5 and
[EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md) §2 both publish an
eleven-item minimum. **This form is a strict superset of that list, not a
competing one** — it expands the same requirements into completable fields.
Nothing in the eleven has been dropped or weakened.

| Published item | Where it lives here |
|---|---|
| 1 Calculator name | A |
| 2 Exact formula | B |
| 3 Variable definitions and value origin | B |
| 4 Units per variable and result | B, D |
| 5 Rounding rules | C |
| 6 Edge and error behaviour | C |
| 7 Acceptance / interpretation rules | D |
| 8 Source document | E |
| 9 Source version and date | E |
| 10 Named regulatory / client owner | G |
| 11 Approval evidence | G, H |

---

# 4. The form

Sections A–H below are the canonical field definitions. §§5–8 are blank copies to
complete — one per calculator. **A blank field blocks that calculator. Partial
input does not authorise a partial build.**

### A. Identity

| Field | What "complete" means |
|---|---|
| Calculator name | The name it carries in the product |
| Business purpose | What decision it supports |
| Regulatory / use-case scope | Where it applies, and where it explicitly does not |
| Intended user | Which role runs it |
| Informational or workflow-governed | Whether the result only displays, or gates a workflow step. **These have different audit and approval consequences — see §D** |

### B. Formula specification

| Field | What "complete" means |
|---|---|
| Exact mathematical formula | Written as an equation, not prose. Every operand named |
| Formula identifier | Stable machine identifier |
| Formula version | Version of this formula, not of the document |
| Per variable — name | The symbol as used in the formula |
| Per variable — definition | What the quantity is |
| Per variable — source | Where its value comes from: user entry, a named platform field, or an external record |
| Per variable — data type | Must be `Decimal`-compatible |
| Per variable — permitted range | Including whether the bound is inclusive |
| Per variable — unit | A canonical unit from §2, or a new one you define |
| Per variable — required / optional | If optional, §C must say what happens when it is absent |

### C. Calculation behaviour

| Field | What "complete" means |
|---|---|
| Operation sequence | The order operations are applied, where order changes the result |
| Rounding precision | Number of decimal places or significant figures |
| Rounding method | Half-up, half-even, truncate, ceiling, floor — named explicitly |
| Intermediate rounding rule | Whether intermediates round or only the final result. **These give different numbers** |
| Unit conversions | Which conversions are permitted, and at which step |
| Null / missing input | Per input: blocked with which reason code, or treated as a stated value |
| Divide by zero | The status and reason code returned. **A zero result is not an acceptable answer** |
| Invalid range | Behaviour when an input falls outside §B's permitted range |
| Negative values | Whether permitted, and behaviour if not |
| Boundary values | Behaviour exactly at each range bound |
| Fail-closed conditions | Every condition under which no number may be produced |
| User-visible error wording | What the user is shown. **Required, because an unworded failure becomes an engineering choice** |

### D. Interpretation

| Field | What "complete" means |
|---|---|
| Result unit | The unit of the returned value |
| Result meaning | What the number represents |
| Acceptance / interpretation rules | How the result is read |
| May the software classify PASS / FAIL? | **YES / NO.** If YES, the exact rule and its approved source |
| Numerical result only? | **YES / NO.** Whether the software displays the number and nothing more |
| Regulatory conclusions that must remain human-only | Any judgement the software must never assert |

> If "may classify PASS/FAIL" is **YES**, that classification is regulatory
> content and needs the same provenance and approval as the formula. Leaving it
> blank is not equivalent to NO — it is incomplete.

### E. Source provenance

| Field | What "complete" means |
|---|---|
| Source document title | Full title |
| Source owner | Publishing body or the client function that issued it |
| Source version / revision | Version identifier |
| Source effective date | Date the version took effect |
| Exact section / page | Precise enough to locate the formula |
| Jurisdiction / market | Where applicable |
| Primary source or client instruction? | **Which of the two.** A client instruction is a legitimate source — it must simply be labelled as one rather than presented as a published standard |
| Attachment / reference location | Where the document itself can be retrieved |

### F. Verification examples

Minimum per calculator — **these are acceptance evidence, not illustrations:**

| Class | Minimum | Each must state |
|---|---|---|
| Normal | **3** | Inputs with units · expected output · expected rounding · expected status |
| Boundary | **2** | Inputs at a range bound · expected output · expected rounding · expected status |
| Invalid input | **2** | Inputs · expected error / blocked status · expected reason code · expected user-visible wording |

> **Examples do not define the formula.** They verify it. A set of worked
> examples supplied *instead of* §B is a rejection condition — see *Engineering
> rejection criteria* — and engineering
> must not reverse-engineer an equation from outputs.

### G. Governance

| Field | What "complete" means |
|---|---|
| Regulatory / content owner | Named accountable role |
| Engineering scope approver | Named accountable role for the separate engineering scope approval ([CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §3.6) |
| Specification approval status | The real status |
| Approval evidence reference | **The approval itself, not a statement that one exists** |
| Approval date | Date of the actual approval |
| Effective version | Which version of this specification is approved |
| Superseded version handling | What happens to results produced under a previous version |

### H. Implementation authorisation

| # | Field | Value |
|---|---|---|
| 1 | **Formula / content specification approved?** | **YES / NO** |
| 2 | **Engineering scope approved?** | **YES / NO** |

> ## **BOTH must be YES before implementation starts.**
>
> Approval 1 comes from the regulatory / content owner. Approval 2 is separate
> engineering scope, because `SCOPE-OUT-18` caps the registry at the six existing
> functions — *"New calculation formulas beyond the six approved functions |
> Never in 4D"*. A formula specification does not lift that cap.

---

# 5. Calculator 1 — Dissolution

*(blank — to be completed)*

| § | Field | Value |
|---|---|---|
| A | Calculator name | |
| A | Business purpose | |
| A | Regulatory / use-case scope | |
| A | Intended user | |
| A | Informational or workflow-governed | |
| B | Exact formula | |
| B | Formula identifier | |
| B | Formula version | |
| B | Variables — name / definition / source / type / range / unit / required | |
| C | Operation sequence | |
| C | Rounding precision | |
| C | Rounding method | |
| C | Intermediate rounding rule | |
| C | Unit conversions | |
| C | Null / missing input | |
| C | Divide by zero | |
| C | Invalid range | |
| C | Negative values | |
| C | Boundary values | |
| C | Fail-closed conditions | |
| C | User-visible error wording | |
| D | Result unit | |
| D | Result meaning | |
| D | Acceptance / interpretation rules | |
| D | May software classify PASS / FAIL? | |
| D | Numerical result only? | |
| D | Human-only regulatory conclusions | |
| E | Source title / owner / version / effective date / section / jurisdiction | |
| E | Primary source or client instruction? | |
| E | Attachment location | |
| F | Normal examples (3) | |
| F | Boundary examples (2) | |
| F | Invalid-input examples (2) | |
| G | Regulatory / content owner | |
| G | Engineering scope approver | |
| G | Approval status / evidence / date | |
| G | Effective version | |
| G | Superseded version handling | |
| **H1** | **Formula / content specification approved?** | **YES / NO** |
| **H2** | **Engineering scope approved?** | **YES / NO** |

# 6. Calculator 2 — Impurity

*(blank — to be completed. Same fields as §5.)*

| § | Field | Value |
|---|---|---|
| A | Identity — name / purpose / scope / user / governed? | |
| B | Formula / identifier / version | |
| B | Variables — name / definition / source / type / range / unit / required | |
| C | Sequence / rounding precision / method / intermediate rule | |
| C | Unit conversions | |
| C | Null / zero-division / invalid range / negative / boundary behaviour | |
| C | Fail-closed conditions | |
| C | User-visible error wording | |
| D | Result unit / meaning / acceptance rules | |
| D | May software classify PASS / FAIL? | |
| D | Numerical result only? | |
| D | Human-only regulatory conclusions | |
| E | Source title / owner / version / effective date / section / jurisdiction | |
| E | Primary source or client instruction? | |
| E | Attachment location | |
| F | Normal (3) / boundary (2) / invalid (2) examples | |
| G | Owners / approval status / evidence / date / version / superseding | |
| **H1** | **Formula / content specification approved?** | **YES / NO** |
| **H2** | **Engineering scope approved?** | **YES / NO** |

# 7. Calculator 3 — Stability / shelf-life

*(blank — to be completed. Same fields as §5.)*

| § | Field | Value |
|---|---|---|
| A | Identity — name / purpose / scope / user / governed? | |
| B | Formula / identifier / version | |
| B | Variables — name / definition / source / type / range / unit / required | |
| C | Sequence / rounding precision / method / intermediate rule | |
| C | Unit conversions | |
| C | Null / zero-division / invalid range / negative / boundary behaviour | |
| C | Fail-closed conditions | |
| C | User-visible error wording | |
| D | Result unit / meaning / acceptance rules | |
| D | May software classify PASS / FAIL? | |
| D | Numerical result only? | |
| D | Human-only regulatory conclusions | |
| E | Source title / owner / version / effective date / section / jurisdiction | |
| E | Primary source or client instruction? | |
| E | Attachment location | |
| F | Normal (3) / boundary (2) / invalid (2) examples | |
| G | Owners / approval status / evidence / date / version / superseding | |
| **H1** | **Formula / content specification approved?** | **YES / NO** |
| **H2** | **Engineering scope approved?** | **YES / NO** |

# 8. Calculator 4 — Additional (blank template)

*(Template only. **No fourth calculator is currently requested, proposed or in
scope.** This exists so a later request arrives in the same shape rather than as
an ad-hoc message. Its presence is not a commitment to build anything.)*

| § | Field | Value |
|---|---|---|
| A | Identity — name / purpose / scope / user / governed? | |
| B | Formula / identifier / version | |
| B | Variables — name / definition / source / type / range / unit / required | |
| C | Sequence / rounding precision / method / intermediate rule | |
| C | Unit conversions | |
| C | Null / zero-division / invalid range / negative / boundary behaviour | |
| C | Fail-closed conditions | |
| C | User-visible error wording | |
| D | Result unit / meaning / acceptance rules | |
| D | May software classify PASS / FAIL? | |
| D | Numerical result only? | |
| D | Human-only regulatory conclusions | |
| E | Source title / owner / version / effective date / section / jurisdiction | |
| E | Primary source or client instruction? | |
| E | Attachment location | |
| F | Normal (3) / boundary (2) / invalid (2) examples | |
| G | Owners / approval status / evidence / date / version / superseding | |
| **H1** | **Formula / content specification approved?** | **YES / NO** |
| **H2** | **Engineering scope approved?** | **YES / NO** |

---

## Engineering handoff criteria

The **exact minimum** engineering must receive before work can start. This is a
conjunction: every line, for the calculator in question. Meeting five of six is
not a partial start.

| # | Required | Accepted when |
|---|---|---|
| 1 | **Completed specification** | Every field in §§A–D answered for that calculator. No blanks, no "TBD", no "as per standard practice" |
| 2 | **Approved source / provenance** | §E complete, including version and effective date, and labelled primary source *or* client instruction |
| 3 | **Test examples** | §F complete — 3 normal, 2 boundary, 2 invalid — each with expected output, rounding and status |
| 4 | **Both approvals** | §H1 **YES** and §H2 **YES**, with §G evidence attached. **Either one alone is not authorisation** |
| 5 | **Version identifier** | The specification version being implemented, so a later revision is distinguishable from this one |
| 6 | **Named accountable role** | A named regulatory/content owner and a named engineering scope approver. **A role with no name attached does not satisfy this** |

**Scope is per calculator.** A complete package for dissolution authorises
dissolution. It authorises nothing for impurity or stability.

## Engineering rejection criteria

A submission meeting any of these is returned rather than interpreted.
**Interpreting an ambiguous specification is how engineering ends up choosing a
regulatory parameter, which is the exact thing this process exists to prevent.**

| Rejected | Why |
|---|---|
| **Formula expressed only in prose** | Prose admits more than one equation. "Percent of label claim" does not say which quantity divides which |
| **Ambiguous units** | "mg" where the dimension or basis is unclear, or a unit outside §2 with no definition |
| **Missing rounding rule** | Nothing is inherited — the existing six round not at all (§2). An unstated rule leaves the number undefined |
| **Example outputs without a formula** | Engineering would have to reverse-engineer the equation, i.e. invent it |
| **Formula without a source** | Unattributable content cannot be governed, versioned or re-approved |
| **Source without a version** | A formula that cannot be tied to a specific revision cannot be re-verified when the source changes |
| **Regulatory limit copied in without interpretation approval** | A threshold lifted from published guidance with no approval that *this* is the applicable reading is engineering choosing a regulatory parameter |
| **Scope approval missing** | `SCOPE-OUT-18` is unlifted; §H2 is NO or blank |
| **Conflicting examples** | Two examples implying different rounding, ordering or thresholds. Engineering must not pick the one that looks right |
| **Blank PASS/FAIL field** | Blank is not NO. Whether software may classify is a decision that must be made, not defaulted |

## What this document does not do

It creates no formula, threshold, limit, acceptance criterion or rounding rule.
It approves nothing, advances no approval count, and adds no function to
`CALCULATION_BINDING_REGISTRY` — which holds **exactly six** identifiers and is
unchanged by this document. It states no Approval Register item as approved:
**Items 13 and 14 remain PENDING**, and the production regulatory content gate
remains **OPEN at 0 of 20**. It asserts no interpretation of any ICH, FDA or USP
text, and nothing here implies such text has been interpreted by anyone.

## Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** An immutable audit mechanism is not
   compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source, and the 279 calculation tests are engineering
   evidence, not validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
