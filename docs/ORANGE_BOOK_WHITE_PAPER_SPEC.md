# White Paper on REGX: proposed specification for iCretegy confirmation

**Status:** PROPOSAL for client confirmation. **Nothing in this document will be
built until iCretegy confirms or amends it in writing.**
**Prepared:** 2026-10-12 by Praverse, from `docs/ORANGE_BOOK_PLAN.md` §6.
**Relates to:** SOW §2.5, "FDA Orange Book Integration".

## Why this document exists

SOW §2.5 asks that "the platform fetches reference data and performs calculations
automatically like in white paper & IIG checklist".

We reviewed the existing iPharmaAI "General White Paper (Structural Research Plan)"
tool. It is a **manually completed assessment form with a maker/checker approval
chain**:

- The user types in every RLD/RS value (proprietary name, strength, application
  number, approval date, holder, TE code, maximum daily dose).
- Patent and exclusivity information is uploaded as **screenshots**.
- The "IIG assessment table" is free text.
- **It performs no calculations and reads no FDA data.**

So there is no existing calculation to reproduce. We need iCretegy to confirm what the
REGX version should do. Below, each open question is followed by our proposed answer.
Please mark each one **Accept / Amend / Reject**.

All FDA data in the proposal comes from the **public FDA Orange Book download**, the
agreed primary source. Every value taken from it is shown with
**"Source: FDA Orange Book, release dated X"**. REGX states what the data says. It
gives no regulatory or legal advice and draws no conclusion about patent status or
filing eligibility.

---

## What the REGX White Paper would do (summary of the proposal)

1. **The user picks the RLD (and optionally the RS)** from an Orange Book search by
   ingredient, trade name or application number. Nothing is auto-selected, even when
   only one product matches.
2. **REGX fills in the RLD/RS block from the Orange Book:**
   - trade name, active ingredient;
   - dosage form and route;
   - strength;
   - application type and number, product number;
   - applicant (full name);
   - approval date, TE code;
   - RLD and RS flags;
   - marketing category (Rx / OTC / discontinued).

   Every auto-filled value is read-only in the form and shows its source release.
3. **Patents and exclusivity appear as structured tables** from the same Orange Book
   release, replacing screenshots:
   - patent number, expiry date, drug-substance and drug-product flags, use code and
     delist flag;
   - exclusivity code and expiry date.

   Every date is labelled "per FDA data dated X".
4. **The user completes the assessment fields** (proposed product, dosing, indication,
   MDD basis and the rest), plus any calculations iCretegy approves under Question 1.
5. **The completed paper goes through the existing REGX review chain:**
   Doer → Reviewer → VP. Each step is recorded in the immutable audit trail, and
   returning a paper for changes is supported, as it is today.
6. **The paper keeps a snapshot of exactly what it used:** the Orange Book release, the
   selected product identifiers and every looked-up value. A later FDA data update
   never changes a paper that was already written; it can only be refreshed
   deliberately, by creating a new version.

---

## Questions and our proposed answers

### Q1. Which calculations, if any, should the White Paper perform?

**Proposed answer:** a small, explicit set, each shown with its formula and inputs, and
**none of them a pass/fail regulatory judgement**:

| # | Calculation | Formula | Notes |
|---|---|---|---|
| C1 | Strength match | Is the proposed strength present among the RLD application's strengths in the Orange Book? (Yes / No; matching strengths listed) | Compares the parsed amount and unit. A strength that can't be parsed is shown as "cannot compare", never as "No" |
| C2 | Total daily intake per inactive ingredient | amount per unit (mg) × maximum dosage units per day | Needs the MDD to be structured (Q6) |
| C3 | % w/v (liquids only) | amount (mg) per mL ÷ 10 | Only where the dosage form is a solution or suspension |

**Comparing against the FDA IID is not proposed as a White Paper calculation.** See Q2.

### Q2. Should the White Paper reuse the IIG checklist engine, or stay separate?

**Proposed answer: reuse.** REGX already has a governed IIG checklist engine with
FDA-IID matching and approved calculations. The White Paper should **link to an IIG
checklist execution** for the same formulation rather than duplicate the comparison
against IID limits. That keeps one source of truth and one approval path for IID
comparisons.

**Note:** that engine's production content is waiting on iCretegy's 20-item content
approval (separate document). Until then the link can be shown, but no production IID
comparison will run.

### Q3. Patents and exclusivity: structured data from the Orange Book, or screenshots?

**Proposed answer: structured data.** It is taken from the Orange Book `Patent.txt` and
`Exclusivity.txt` of the **same release** as the selected product. The fields are:

- **Patents:** patent number, expiry date, drug-substance flag, drug-product flag, patent
  use code, delist-requested flag.
- **Exclusivity:** exclusivity code, expiry date.

Rules:
- Each date carries "per FDA data dated X".
- Codes are shown as published. REGX does not interpret use codes or exclusivity
  codes, and it does not state whether a patent or exclusivity blocks a filing.
- Users may still attach supporting documents through REGX's document module, but the
  screenshot fields are retired.

### Q4. Units, rounding and thresholds, and who owns the formulas?

**Proposed answer:**
- **Units:** mg for amounts, mL for volumes, mg/day for total daily intake. Inputs in
  other units are converted only through REGX's governed unit table. An unknown unit
  is rejected, never guessed.
- **Rounding:** store full precision. Display to 2 decimal places (C2) and 2 decimal
  places of % (C3). C1 compares exact parsed values.
- **Thresholds:** **none in the White Paper.** Limit comparisons belong to the IIG
  engine (Q2).
- **Ownership:** iCretegy names a regulatory signatory who approves each formula (C1–C3)
  and its version. REGX records the approved formula version with every calculated
  value.

### Q5. Should the 92-question checklist and the combination-product appendix be ported?

**Proposed answer: yes, as a governed, versioned question bank owned by iCretegy.**
- It is managed through REGX's existing template registry: draft → review → approve →
  activate, with version history.
- Every completed White Paper records the question-bank version it was answered
  against, and later edits to the bank don't change it.
- The combination-product appendix becomes an optional section with the same
  versioning.
- The QSR document list and its owning departments are configurable per company
  rather than hardcoded.

### Q6. Which fields are mandatory, and what is the output?

**Proposed answer:**
- **Mandatory to submit for review:**
  - RLD selected from the Orange Book;
  - proposed product name, strength, dosage form and route;
  - maximum daily dose as amount + unit + basis (structured, replacing free text);
  - filing category, from a fixed list to be confirmed by iCretegy;
  - risk level (High / Moderate / Low, fixed list).

  Everything else is optional.
- **Output:**
  - the REGX record itself (viewable, versioned and audit-trailed);
  - an export (PDF) of the reviewed paper, showing the source release and review
    history.

  A signed or eCTD-formatted output would be a separate, later decision.
- **21 CFR Part 11:** REGX provides the controls (immutable audit trail, attributable
  actions, review chain). **We propose not to claim Part 11 compliance or attest to
  it.** Please tell us whether the contract requires an attestation.

### Q7. Conclusion wording for the combination-product assessment

**Proposed answer:** three fixed options:
- "Yes"
- "No"
- "Not sure: requires controlled correspondence"

The third replaces the two inconsistent variants in the current tool ("Not sure" and
"Not sure, require controlled").

### Q8. Which IID limit does the checklist compare against: per unit or per day?

**Status: proposed, pending iCretegy and regulatory reviewer confirmation.** Nothing
described here is built.

**What the FDA data shows** (FDA IID file of July 2026, `IIR_OCOMM.csv`, 9,071 rows):
each row carries **either** a per-unit limit **or** a per-day limit, never both.
- 3,805 rows give a **maximum potency per unit dose** (`POTENCY_AMOUNT` + `POTENCY_UNIT`,
  e.g. 0.14 mg, 11 %w/w, 45 mg/5ml).
- 4,059 rows give a **maximum daily exposure** (`MAXIMUM_DAILY_EXPOSURE`, always in mg in
  this file).
- 1,207 rows give neither (potency unit "NA" or "ADJ PH").

**Proposed answer:** the IIG checklist (Q2) picks the check from what the matching IID
row provides:

| IID row has | Check | Formula | Input from the White Paper |
|---|---|---|---|
| Potency (per unit) | **Per-unit check** | amount of the ingredient per dosage unit vs the IID potency | Amount per unit, in the same unit as the IID value |
| Maximum daily exposure (per day) | **Per-day check** | amount per unit (mg) × maximum dosage units per day (= C2) vs the IID maximum daily exposure (mg/day) | The product's maximum daily dose, structured (Q6) |
| Neither | No comparison | — | Shown as "IID gives no numeric limit for this ingredient, route and dosage form" |

Rules:
- The result is shown as "at or below" / "above" the IID value, with both numbers, the
  formula and the IID release date. It is **not** a statement that the formulation is
  acceptable or approvable.
- Units are compared only through REGX's governed unit table (Q4). A potency in a
  different basis (%w/w, %w/v, mg/5ml) is compared only when the product's amount is
  given on the same basis. Otherwise it is shown as "cannot compare", never as a result.
- If the maximum daily dose is missing or not structured, the per-day check is shown as
  "cannot compare: maximum daily dose needed", never skipped silently.
- When several IID rows match (for example the Orange Book route "INJECTION"), each row
  is checked and shown separately. No limit is picked automatically (see
  `docs/TERMINOLOGY_VOCABULARY_DECISION.md`).

**Why this matters now:** under REGX's current IID rule, a row with only a maximum daily
exposure is marked `potency_missing` (not usable). If this answer is accepted, that rule
changes so that such rows feed the per-day check. That is a separate engineering change
after confirmation.

---

## Not included in this proposal

- AI or LLM drafting of any section.
- Any statement about patent infringement, exclusivity expiry effects, filing
  eligibility or launch timing.
- Automatic lookup of drug-shortage, NDSRI, PSG or DMF status. These remain manual
  entries with optional attachments.

## Please return

For each of Q1–Q8: **Accept / Amend (with changes) / Reject**, plus the name of the
iCretegy signatory for Q4. Development starts only after written confirmation.
