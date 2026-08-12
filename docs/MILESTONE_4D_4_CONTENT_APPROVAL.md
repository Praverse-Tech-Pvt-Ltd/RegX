# Milestone 4D-4 — Production Regulatory Content Approval Package

> **Status:** PENDING — no item below is approved.
> **Gate type:** regulatory-content approval. **Not an engineering decision.**
> **Blocks:** Milestone 4D-4 production-content implementation.
> **Companion:** `MILESTONE_4D_4_DISCOVERY.md`

## 1. Why this gate exists

`MILESTONE_4D_DISCOVERY.md:1089` (Open Question 4, *RESOLVED BY CONTROLLED
DEFERRAL*):

> The exact set of built-in `ChecklistDefinition` templates to ship (oral solid,
> oral liquid, parenteral, topical?) is a **regulatory-content decision, not an
> engineering one**, and is explicitly not decided in this document. **Decision:
> route it through a separate, dedicated regulatory-content approval gate**,
> owned by whoever holds IIG guidance interpretation authority, **required before
> 4D-4 begins**. No real regulatory checklist template exists in 4D-1 through
> 4D-3 — those stages use only synthetic `ChecklistDefinition` content (the
> paracetamol/acetaminophen worked example, §19, serves as the synthetic test
> fixture) — and implementation **must never silently invent real regulatory
> questions** in the absence of that separate approval.

**This document proposes no regulatory questions, no answer text, no
applicability rules, and no guidance interpretation.** It enumerates only what a
qualified approver must decide. Anything an engineer filled in here would be
precisely the "silently invent real regulatory questions" failure the gate
exists to prevent.

## 2. Who must approve

The holder of **IIG guidance interpretation authority** for this organisation.
Engineering may prepare structure and load approved content; engineering may not
author, interpret, or approve it.

## 3. Synthetic vs. production content

The repository distinguishes two categories, and the gate constrains only one.

| | Engineering test content | Production regulatory content |
|---|---|---|
| Examples | paracetamol/acetaminophen worked example (§19), per-test factories | shipped `ChecklistDefinition` templates |
| Used by | unit, integration, E2E, local development | real tenant executions |
| Approval gate | **not required** | **required — this document** |
| Basis | 4D-1…4D-3 "use only synthetic `ChecklistDefinition` content" (L1089) | L1089 |

**Resolved — `4D4-DEC-001`, approved by the project owner 2026-08-11.** The gate
is scoped to the **production-content workstream only**. Synthetic engineering
content may be used for generic 4D-4 engineering before this package is
approved; 4D-1 through 4D-3 already proceeded that way and their fixtures remain
the basis of the merged test suites.

**Allowed before this package is approved:** generic override/deviation
infrastructure; reviewer-conclusion completion; controlled-export
infrastructure; unit, integration and E2E tests on synthetic fixtures; API and
frontend engineering containing no real regulatory questions.

**Not allowed before this package is approved:** authoring production regulatory
checklist questions; loading production regulatory templates; activating
production regulatory templates; shipping production regulatory checklist
content.

This preserves L1089's stated purpose — that implementation "must never silently
invent real regulatory questions" — without stopping engineering that does not
touch regulatory content.

**Nothing in items 1–20 below is affected by this resolution. Production content
remains fully blocked, 0 of 20 approved.**

## 4. Approval table

All items PENDING. Evidence column cites the repository constraint the approved
content must satisfy; it is not a proposed answer.

| # | Item | Decision | Owner | Status | Evidence / constraint | Approver | Date | Comments |
|---|---|---|---|---|---|---|---|---|
| 0 | Gate scope: whole milestone or content workstream only | **Content workstream only** | Project owner | **APPROVED** | `4D_DISCOVERY.md:1089` ambiguity, §3 above; `4D4-DEC-001` | Project owner | 2026-08-11 | Not a production-content item — a sequencing decision. Items 1–20 unaffected. |
| 1 | `ChecklistDefinition` identity — which templates ship (oral solid, oral liquid, parenteral, topical, …) | TBD | Regulatory | **PENDING** | L1089 names these as candidates only | | | Set is undecided |
| 2 | Checklist title per definition | TBD | Regulatory | **PENDING** | §1 definition governance | | | |
| 3 | Jurisdiction | TBD | Regulatory | **PENDING** | — | | | US FDA assumed but unstated |
| 4 | Regulatory basis | TBD | Regulatory | **PENDING** | `ChecklistVersion.regulatory_basis` exists | | | Field exists; content undecided |
| 5 | Source guidance, version, publication date | TBD | Regulatory | **PENDING** | §18 reproducibility | | | Must be citable |
| 6 | Section structure and ordering | TBD | Regulatory | **PENDING** | §2 sections/questions | | | |
| 7 | Question text (verbatim) | TBD | Regulatory | **PENDING** | L1089 — must never be invented | | | **Engineering must not draft** |
| 8 | Question codes / public identifiers | TBD | Regulatory + Eng | **PENDING** | §1 stable identity; UUID-only external | | | Codes are regulatory-facing |
| 9 | Answer type per question (18 available) | TBD | Regulatory + Eng | **PENDING** | `AnswerType`, §6a | | | Must respect §3d-i matrix |
| 10 | Required vs optional per question | TBD | Regulatory | **PENDING** | §8 completeness checks | | | Drives approval blocking |
| 11 | Applicability rules | TBD | Regulatory | **PENDING** | §9a rule evaluation | | | Interacts with APP-009 |
| 12 | `FDA_DERIVED_DEFAULT` bindings | TBD | Regulatory + Eng | **PENDING** | §4 | | | Which FDA field feeds which question |
| 13 | `SYSTEM_CALCULATED` bindings | TBD | Regulatory + Eng | **PENDING** | §6; 4D-3 registry has six approved calculations | | | Only the six exist |
| 14 | Calculation dependencies / ordering | TBD | Eng from 12–13 | **PENDING** | 4D-3 dependency graph; max reachable depth 3 | | | Derived, not authored |
| 15 | Help / guidance text | TBD | Regulatory | **PENDING** | — | | | Regulatory interpretation |
| 16 | Reviewer expectations per question | TBD | Regulatory | **PENDING** | §7, §11 paired justification | | | Blocked calc forces justification |
| 17 | Override eligibility per question | TBD | Regulatory | **PENDING** | §12 — only `FDA_DERIVED_DEFAULT` overridable | | | Engineering floor is fixed |
| 18 | Export inclusion per question | TBD | Regulatory | **PENDING** | §17 | | | Any exclusions? |
| 19 | Version number and effective date | TBD | Regulatory | **PENDING** | §1 versioning; §18 pinned version | | | |
| 20 | Formal sign-off (name, role, date, signature) | TBD | Regulatory authority | **PENDING** | L1089 authority requirement | | | Gate closes here |

## 5. Engineering constraints the approved content must satisfy

Fixed by merged code; content cannot override them:

1. **Answer-type × classification matrix** — all 90 combinations classified
   (`4D_1_IMPLEMENTATION_SPEC.md:1827`). Floors: `APPROVAL_METADATA` and
   `REVIEWER_CONCLUSION` only `REVIEWER_CONFIRMED`; `CALCULATED_VALUE` and
   `CALCULATED_STATUS` only `SYSTEM_CALCULATED`; `FDA_DERIVED_DEFAULT` never
   paired with narrative/approval/calculated types.
2. **Only six approved calculations exist** (4D-3 registry). A question needing a
   seventh is out of scope until that calculation is separately approved.
3. **Calculated-node depth** — max reachable calculated node count from any
   single question is **3** (`4D_3_IMPLEMENTATION_SPEC.md:944`).
4. **Overrides** — only `FDA_DERIVED_DEFAULT` is overridable (§12). Content
   cannot make a `SYSTEM_CALCULATED` question overridable.
5. **No new status vocabulary** — §11 reuses `CalculationStatus` / `MatchStatus`.
6. **`SYSTEM_CALCULATED` keeps `raw_value` null** (M4D3-MDL-006); results live in
   `CalculationOutcome`.
7. **UUID-only external identity**; no DB IDs anywhere client-facing.
8. **Reproducibility** — content must be answerable without re-querying live
   FDA/formulation data after approval (§18).

## 6. What engineering will do once approved

1. Load approved content as governed `ChecklistDefinition` / `ChecklistVersion` /
   `ChecklistSection` / `ChecklistQuestion` records through the existing 4D-1
   governance path (draft → review → approve → activate) — **not** a migration
   and **not** a fixture.
2. Encode approved applicability rules through the existing §9a mechanism.
3. Bind approved `FDA_DERIVED_DEFAULT` / `SYSTEM_CALCULATED` questions to
   existing resolvers and the six approved calculations.
4. Add content-validation tests asserting the approved structure loads and
   activates.

Engineering will **not** author question text, interpret guidance, invent
calculations, or approve its own content.

## 7. Gate status

**REGULATORY-CONTENT GATE: OPEN**

**0 of 20 production-content items approved.** Until item 20 is signed off, no
production regulatory checklist content may be added to the repository.

Item 0 (gate scope) is approved and is deliberately not counted among the
production-content items — it decides *sequencing*, not content. Generic 4D-4
engineering on synthetic fixtures is therefore unblocked; production regulatory
content is not.
