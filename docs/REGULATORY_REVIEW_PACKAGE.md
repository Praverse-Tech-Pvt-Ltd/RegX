# Regulatory review package

**For:** the Praverse regulatory reviewer (to be named by Pratham) and iCretegy. **Prepared by:** Maanav, with Claude Code. **Date:** 2026-11-06.
**Purpose:** one organised set of questions instead of separate technical emails (Pratham's second direction (`docs/decisions/2026-11-07-pratham-direction-2.md`), §7).

**Rules for this package**
- **Nothing here is approved.** Every item is a proposal until the named decision owner signs it off in writing, and the sign-off is recorded (who, date, document). Status "Approved" is used only with that evidence.
- "Proposed answer" is our engineering proposal. The reviewer may accept, amend or reject it.
- **Expected response dates are proposals** for Pratham to confirm when he sends the package. They assume the package goes out by **2026-11-13** and the regulatory reviewer is named by then.
- Sequence: the **Praverse regulatory reviewer** checks every item first; items marked "iCretegy" then go to iCretegy with the reviewer's position.

## Summary

| # | Item | Decision owner | Proposed response date | Status |
|---|---|---|---|---|
| 1 | 164 IID route and dosage-form mappings | Praverse regulatory reviewer (sign-off by Pratham) | 2026-11-27 | Proposed; none approved |
| 2 | Orange Book route/dosage-form/unit review workbook | Praverse regulatory reviewer (sign-off by Pratham) | 2026-12-04 | Prepared; none approved |
| 3 | `DROPS` (67 IID records) | Praverse regulatory reviewer | 2026-11-27 | Proposed: per record at review |
| 4 | INJECTION matching | iCretegy (after reviewer check) | 2026-12-04 | Draft question ready; not sent |
| 5 | Q8: per-unit vs per-day IID comparison | iCretegy + reviewer | 2026-12-04 | Proposed; not built |
| 6 | White Paper specification, Q1–Q7, 92-question bank, combination appendix | iCretegy (named signatory for Q4) after reviewer check | 2026-12-11 | Proposed; nothing built |
| 7 | 20-item regulatory content gate | iCretegy regulatory approver | 2026-12-18 | 0 of 20 approved |
| 8 | Approval Register items 13 and 14 | iCretegy regulatory approver | 2026-12-18 | Pending |
| 9 | IID source: public FDA download as source of record | iCretegy | 2026-11-27 | Proposed; Orange Book equivalent already agreed |
| 10 | Controlled units: unit list and allowed conversions | Praverse reviewer, then iCretegy where a rule is regulatory | 2026-12-11 | Design in `docs/CONTROLLED_UNITS_DESIGN.md` |

**Why it matters (real data):** of the 9,071 real FDA IID records, 0 are calculable today. With the proposed mappings applied: 1,207 have no numeric limit at all; 41 still lack a mapping (`DROPS`); 4,059 carry only a maximum daily exposure (need Q8); 16 use an unsupported unit (`mg/mg`); 3,748 have a supported per-unit limit and become comparable once controlled units exist **and** the mappings are approved (`docs/IID_BLOCKER_ANALYSIS.md`).

---

## 1. The 164 IID mapping proposals

- **What:** each distinct route and dosage-form text in the FDA IID file (July 2026, 9,071 rows) mapped to a term in the FDA SPL controlled lists (NCI codes; vocabulary decided 2026-10-13, `docs/TERMINOLOGY_VOCABULARY_DECISION.md`).
- **Proposed:** 59 route mappings and 105 dosage-form mappings, every one an **exact** match to an active SPL term (`propose_iid_mappings`, PR #94). Listed in the app at `/fda-data/mappings/` with status `proposed`.
- **Decision needed:** for each mapping, approve or reject. A Reviewer submits for review; a different VP approves (the loader can never approve, #97). A VP-only "approve selected" is approved by Pratham to build; it keeps one approval event per mapping.
- **Effect of approval:** nothing changes in existing records until `reresolve_terminology` runs (#93); it fills only empty links and never overwrites.
- **Decision owner:** Praverse regulatory reviewer; sign-off by Pratham. **Status:** proposed; **0 approved**. (A local test approval of all 164 on 2026-11-06 was discarded; it does not count.)

## 2. Orange Book route / dosage-form / unit workbook

- **What:** `orange_book_terminology_review_spl_2026-10-13.xlsx` (outside the repository, `D:/Praverse/data/fda/mappings/`), guide `docs/TERMINOLOGY_MAPPING_REVIEW.md`.
- **Content:** routes 79 = 36 exact / 9 likely / 34 unclear; dosage forms 117 = 75 / 10 / 32; units 52 = 4 / 14 / 34. Each row has the proposed SPL term and the consequence of the choice.
- **Decision needed:** confirm or correct each likely/unclear row; exact rows confirmed in bulk.
- **Decision owner:** Praverse regulatory reviewer; sign-off by Pratham. **Status:** prepared; none approved. The **units** sheet is now superseded by the controlled-units design (item 10).

## 3. `DROPS`

- **What:** the IID value `DROPS` (67 records) has no exact SPL dosage form (SPL has e.g. `SOLUTION/ DROPS`, `SUSPENSION/ DROPS`).
- **Proposed answer (owner decision 2026-11-05):** no blanket mapping; each record is resolved **per record at review** from the product. Pending reviewer confirmation.
- **Decision owner:** Praverse regulatory reviewer. **Status:** proposed.

## 4. INJECTION matching

- **Question (draft, `docs/TERMINOLOGY_VOCABULARY_DECISION.md` §4):** the Orange Book lists 7,231 products with route "INJECTION"; the IID always names the specific route.
- **Proposed answer (Pratham's preferred approach, direction 2026-11-06 §6C):** (a) a fixed list of injectable routes approved by the reviewer; (b) REGX shows every matching IID record with its own route and limit and **never auto-picks the highest or most favourable limit**; (c) the reviewer confirms the product's actual route before the result is used.
- **Risk if accepted loosely:** an intravenous product checked against another route's higher limit.
- **Decision owner:** iCretegy, in writing, after the reviewer's check. **Status:** draft question, not sent. **Not built** (`find_iid_candidates` takes one route today).

## 5. Q8: per-unit or per-day comparison

- **Data:** each IID row has either a per-unit potency limit or a maximum daily exposure, never both (3,805 / 4,059 / 1,207 with neither, per the July 2026 file; see `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md` Q8).
- **Proposed answer:** per-unit comparison when a comparable potency limit exists; per-day comparison (amount per unit × maximum dosage units per day vs maximum daily exposure) when a daily limit and a structured maximum daily dose exist; otherwise "cannot compare" with the reason. Results read "at or below" / "above" the reference with both numbers, source and calculation shown; **never** "acceptable", "approvable" or "compliant".
- **Decision owner:** iCretegy + Praverse reviewer (calculation, dosage basis, wording). **Status:** proposed; not built.

## 6. White Paper specification (`docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md`)

| Q | Question | Proposed answer (short) |
|---|---|---|
| Q1 | Which calculations? | Three, none a pass/fail judgement: C1 strength match against the RLD; C2 total daily intake per inactive ingredient (amount × max units/day); C3 % w/v for liquids (mg/mL ÷ 10). No IID comparison inside the White Paper |
| Q2 | Reuse the IIG engine? | Yes: link to an IIG checklist execution for IID comparisons; one source of truth |
| Q3 | Patents and exclusivity | Structured data from the same Orange Book release; codes shown as published, never interpreted as blocking |
| Q4 | Units, rounding, thresholds, formula owner | mg, mL, mg/day via the governed unit table; unknown units rejected; full precision stored, 2 decimals shown; no thresholds in the White Paper; iCretegy names a signatory per formula |
| Q5 | Port the 92-question checklist and combination appendix? | Yes, as a governed, versioned question bank owned by iCretegy |
| Q6 | Mandatory fields and output | RLD, product name/strength/form/route, structured max daily dose, filing category, risk level; output = versioned REGX record + PDF export; no Part 11 claim |
| Q7 | Combination-product conclusion wording | "Yes" / "No" / "Not sure: requires controlled correspondence" |
| Q8 | Per unit or per day | See item 5 |

- **Decision owner:** iCretegy (named signatory for Q4), after the reviewer has checked calculations, thresholds, units and wording. Requested reply: **Accept / Amend / Reject per question**, plus the 92-question bank and the appendix.
- **Status:** proposed; nothing built. Development starts only after written confirmation.

## 7. 20-item regulatory content gate

- **What:** the 20 decisions needed before any real checklist content goes live (`docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`): which templates ship, titles, jurisdiction, regulatory basis, source guidance, sections, verbatim question text, codes, answer types, required/optional, applicability, FDA-derived defaults, system-calculated bindings, ordering, help text, reviewer expectations, override eligibility, export inclusion, version/effective date, formal sign-off.
- **Proposed answer:** none pre-selected; every item needs a named iCretegy regulatory author or approver. Engineering facts for each item are in the intake.
- **Decision owner:** iCretegy regulatory approver. **Status:** **0 of 20 approved.**

## 8. Approval Register items 13 and 14

- **What:** which `SYSTEM_CALCULATED` questions bind to which of the six approved calculation identifiers (item 13), and their dependencies and ordering (item 14). Intake: `docs/APPROVAL_REGISTER_13_14_DECISION_INTAKE.md`.
- **Decision owner:** iCretegy regulatory approver. **Status:** pending. Item 14 depends on 12–13 of the content gate.

## 9. IID source

- **Proposed answer:** the public FDA IID download is the source of record (as already agreed for the Orange Book in writing, 2026-10-12). Operator downloads the file; REGX imports it as a new release; Doer validates; Reviewer/VP approve; VP activates. iCretegy's own files, if any, are a cross-check only.
- **Decision owner:** iCretegy (written confirmation, to be stored in the shared approvals folder; Pratham coordinates). **Status:** proposed.

## 10. Controlled units

- **What:** the unit list and the allowed conversions needed for real IID comparisons; design in `docs/CONTROLLED_UNITS_DESIGN.md`.
- **Decision needed:** confirm the unit list and that the proposed refused conversions are refused (for example, never % w/w to mg without a declared basis).
- **Decision owner:** Praverse reviewer; iCretegy where a conversion embodies a regulatory rule. **Status:** design only.

---

## Recording a decision

For every item: decision (accept / amend / reject), the exact wording accepted, decision owner's name and role, date, and the document or email it came from. Engineering records it in `PROJECT_OVERVIEW.md` §12 and, for content and mappings, in the application's own approval records. Until then the item stays "proposed".
