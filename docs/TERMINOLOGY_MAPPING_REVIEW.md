# Orange Book terminology mapping review

**Status:** proposals for human review. **Nothing has been approved, created or loaded.**
**Owner:** Praverse regulatory reviewer, with sign-off by Pratham.
**Prepared:** 2026-10-12 from the active local Orange Book release
`6d9fe36b-839d-4ced-8b7c-f3b326243be0` (48,761 products, FDA file `EOBZIP_2026_08.zip`).

**Review workbook** (kept outside the repo):
`D:/Praverse/data/fda/mappings/orange_book_terminology_review_2026-10-12.xlsx`

---

## 1. Why this is needed

Every Orange Book product carries its route, dosage form and strength as FDA wrote
them. REGX stores those **raw** values, and also a **normalised** value pointing at a
controlled code. The normalised value is what search filters, the IID matching engine
and later the lookup page rely on.

**Today no product has a normalised route or dosage form, and every strength is
`review_required`.** There are two reasons:

1. **The controlled vocabularies are empty.** The local database has 0 controlled
   routes, 0 dosage forms and 0 units. No migration, seed or command creates them.
2. **There are no mappings.** The importer never guesses: an unmapped raw value stays
   unmapped (`fda_data/terminology.py`).

Consequence: `GET /fda-data/orange-book/products/?route=…` and `?dosage_form=…` match on
normalised codes, so they **currently return nothing**.

## 2. How mapping works today (plain words)

- **Controlled code.** A canonical entry: `ControlledRoute`, `ControlledDosageForm` or
  `ControlledUnit`. A unit also has a *dimension* (mass, volume, count, percentage or
  concentration) and a conversion factor.
- **Mapping row.** "FDA raw value X means controlled code Y". It exists for routes,
  dosage forms and units (plus substance/UNII, which uses its own flow).
- **States** (`fda_data/mapping_transitions.py`):
  `proposed → reviewed → approved`, or `rejected`.
  - Submitting for review needs the review permission (**Reviewer** or **VP**).
  - **Approving needs `fda_data.approve`, which only the VP role holds.**
  - Approval is legal only from `reviewed`.
  - `approved` and `rejected` are final.
  - **Nothing is ever approved automatically.**
- **Only an approved, current mapping resolves a value**, and it is applied **when a
  release is imported**.

### Gaps to close before loading (engineering, not part of this review)

1. **No API creates route, dosage-form or unit mappings or controlled codes.** Only
   substance proposals have a create endpoint. A loader is needed (§5).
2. **Approval does not update products already imported.** The 48,761 rows keep
   `NULL` until one of two things happens:
   - the same file is re-imported as a **new release** after the mappings are
     approved. The current tools support this, but it is a new release with a new
     review → approve → activate;
   - or a "re-resolve terminology on a release" step is built.

   An owner decision is needed on which.

## 3. What the review covers

| Type | Distinct values | exact | likely | unclear |
|---|---|---|---|---|
| Routes | 79 | 44 | 4 | 31 |
| Dosage forms | 117 | 99 | 1 | 17 |
| Units (from single number+unit strengths) | 52 | 5 | 2 | 45 |

Measured against products:
- **Routes:** exact covers 40,655 products, likely 320, unclear 7,786. `INJECTION` alone
  accounts for 7,231 of the unclear.
- **Dosage forms:** exact covers 48,725 products, likely 1, unclear 35.
- **Units:** exact covers 21,952 single-value strengths, likely 260, unclear 4,119.

**Confidence means:**
- **exact:** the raw value is one plain term. The proposed code is a **new** controlled
  code that is that term (for example `ORAL`, `TABLET, EXTENDED RELEASE`).
- **likely:** a recognisable variant of a base term. The proposed code is the base
  term:
  - a pack suffix (`ORAL-28` → `ORAL`);
  - a term listed twice (`INTRAVENOUS, INTRAVENOUS`, `SOLUTION, SOLUTION`);
  - Orange Book's `GM` for gram.
- **unclear: no code is proposed.** This covers:
  - several routes or forms in one value (combination packs, multi-route injectables),
    when a product can hold only ONE normalised value today;
  - `INJECTION`, which doesn't say IV, IM or SC;
  - `N/A`;
  - units the current model can't represent: mEq, IU/units, curies, rates (`/HR`),
    amounts per presentation (`/VIAL`, `/SPRAY`), mass-per-mass, and `%` without a basis.

**Policy decisions the unclear rows depend on** (list them in the review notes):
1. multi-route and multi-form values: a combined code, or a model change to allow
   several;
2. what `INJECTION` should map to;
3. the percentage basis (w/w, w/v, v/v);
4. whether to add dimensions for amount (mEq/mmol), activity (IU/units), radioactivity
   and rate;
5. "per presentation" strengths (per vial, spray or packet).

### Strengths

- **26,331 strengths** are a single number plus unit (e.g. `15MG`, `1MG/ML`). They are
  flagged **only because no units exist**, and they resolve once their units are
  approved.
- **22,430** use richer patterns: **592 distinct shapes**.
- The **Strength patterns** sheet lists the 30 most common, each with why it's flagged
  and a **proposed** parsing rule, for example:
  - `EQ … BASE` → amount + unit with basis "base equivalent";
  - `A;B` → one strength per ingredient;
  - `32MG/4.4ML (7.2MG/ML)` → use the bracketed concentration;
  - strip `**Federal Register…` footnotes into a note.
- **None of this is implemented.** Parser changes are a separate engineering change
  after the policy decisions above.

## 4. How to fill in the workbook

On the **Routes**, **Dosage forms** and **Units** sheets, fill in one row per raw value:

| Column | What to enter |
|---|---|
| Approve (Y/N) | `Y` to accept the row; `N` to reject it (leave blank to skip it this round) |
| Corrected code | Only if you change the proposed code, or to give a code for an *unclear* row. Use UPPER_SNAKE_CASE for routes and dosage forms, as proposed (e.g. `INTRAVENOUS`). For units, use `code [dimension]` (e.g. `milligram [mass]`) |
| Reviewer | Your name |
| Date | `YYYY-MM-DD` |

Rules:
- **Do not edit** the Raw value, Count, Proposed code, Confidence or Reason columns.
  The loader matches rows on Raw value.
- An *unclear* row marked `Y` **must** have a Corrected code. Otherwise the loader
  refuses that row.
- Several raw values may share one code (for example `ORAL`, `ORAL-28`, `ORAL-21` →
  `ORAL`).
- Record policy decisions (§3) in a note to Pratham. They also inform the parser
  changes.
- Return the workbook to the same folder with a new name, e.g.
  `…_reviewed_YYYY-MM-DD.xlsx`. Keep the original unchanged.

## 5. How it will be loaded (proposed; not built)

1. **Loader** (a new management command): reads the reviewed workbook and validates
   every row first. It refuses the whole file on:
   - an unknown raw value;
   - a `Y` without a code;
   - a malformed code;
   - an edited protected column.
2. **For every `Y` row**, it creates the controlled code if missing, plus a mapping row
   in **`proposed`** state with the reviewer's name and date in its reason. **The
   spreadsheet never approves anything by itself.**
3. **In REGX**, a Reviewer submits the mappings for review, and a **VP approves** them.
   That keeps the existing segregation of duties and audit trail. Pratham's sign-off is
   this approval step.
4. **Re-resolution:** re-import `EOBZIP_2026_08.zip` as a new release and take it
   through review → approve → activate, or use a re-resolve step if one is built (§2).
   Then check the normalised counts against this review.

Nothing will be loaded until the reviewed workbook comes back.
