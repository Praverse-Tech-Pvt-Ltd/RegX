# Terminology vocabulary decision: which controlled lists REGX should use

**Status:** decided 2026-10-13 (see Decisions below). Nothing here is built, seeded or approved by this document.
**Date:** 2026-10-13. **Author:** Maanav (with Claude Code). **Decision owner:** Praverse regulatory reviewer; sign-off by Pratham.
**Related:** `docs/FDA_TERMINOLOGY_MAPPING.md` (how mappings work), `docs/ORANGE_BOOK_PLAN.md` (Phase 3 depends on this).

## Decisions (2026-10-13, owner)

- **Controlled vocabulary:** the FDA SPL lists. For routes and dosage forms, `code` = the NCI Thesaurus code
  (e.g. `C38288`); the SPL term (e.g. `ORAL`) is the display name (`canonical_label`).
- **Units:** on hold. A separate, later PR, because units need a migration (§5).
- **INJECTION:** the question in §4 goes to iCretegy with its three conditions. Until it is answered: show all matching
  IID records, never auto-pick a limit, and the reviewer confirms the route. `find_iid_candidates` is **not** changed yet.
- **Review scope:** the reviewer fills in **routes and dosage forms only**. The workbook's Units sheet is marked
  "ON HOLD — do not fill".

## 1. The question

`ControlledRoute`, `ControlledDosageForm` and `ControlledUnit` are empty. Before any Orange Book value can be mapped,
someone has to decide what the *target* list is. The 2026-10-12 review workbook proposed "new codes = the Orange Book
term itself". That would make REGX invent its own vocabulary, which then fails to line up with the IID.

**Recommendation in one line:** use FDA's own Structured Product Labeling (SPL) lists as the controlled vocabulary,
NCI Thesaurus codes for routes and dosage forms and UCUM for units, and map Orange Book values *onto* them.

## 2. Official sources (checked 2026-10-13)

| List | URL | Page "content current as of" | Format | Size |
|---|---|---|---|---|
| Route of Administration | https://www.fda.gov/industry/structured-product-labeling-resources/route-administration | 10/29/2021 | HTML table: SPL term + NCI Thesaurus code | 121 terms |
| Dosage Forms | https://www.fda.gov/industry/structured-product-labeling-resources/dosage-forms | 02/03/2022 | HTML table: SPL term + NCI Thesaurus code | 158 terms |
| Units of Measure | https://www.fda.gov/industry/structured-product-labeling-resources/units-measure | 10/24/2024 | HTML table: UCUM name + UCUM code | 52 units |
| Units of Presentation | https://www.fda.gov/industry/structured-product-labeling-resources/units-presentation | 03/27/2018 | HTML table: SPL term + NCI code + UCUM | 76 terms |

- Index page: https://www.fda.gov/industry/fda-data-standards-advisory-board/structured-product-labeling-resources.
- **Licence (checked 2026-10-13 on the official pages):**
  - The four SPL pages carry no licence of their own; the only "licence" words on them are navigation links to unrelated SPL lists.
  - **FDA website policy** (https://www.fda.gov/about-fda/about-website/website-policies, content current as of 01/19/2024):
    "Unless otherwise noted, the contents of the FDA website (www.fda.gov) — both text and graphics — are not copyrighted.
    They are in the public domain and may be republished, reprinted and otherwise used freely". "Credit to the U.S. Food and
    Drug Administration as the source is appreciated but not required." FDA "strongly recommends that the copied item lists
    the date that the material was copied". The SPL pages carry no "otherwise noted" exception.
  - **NCI Thesaurus terms of use** (https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/ThesaurusTermsofUse.htm, no date on the page):
    "The NCI Thesaurus™ is released under the Creative Commons Attribution 4.0 International license (CC BY 4.0)."
    "The name "NCI Thesaurus" is trademarked. Only the NCI Thesaurus™ published by the NCI can be released under this name."
  - **What this means for REGX:** the NCI codes come from NCIt, so CC BY 4.0 applies to them: keep an attribution to NCI EVS
    (in `fda_source` and any export), and never call REGX's list "NCI Thesaurus". Record the date each list was copied.
  - **Not confirmed:** whether the CC BY 4.0 attribution has to appear in the user interface. That is a legal reading, not
    something the pages state. UCUM (units) has its own terms; not checked, because units are on hold.
- The pages are HTML, not file downloads. Scripted `/media/.../download` from fda.gov is blocked by FDA abuse detection and
  must not be worked around. A loader should read a saved snapshot of the table, not scrape fda.gov at run time.
- The page dates are old (2018–2024). FDA updates these lists without a release cycle, so every load must record the
  page date and a checksum of the snapshot it used.

## 3. How well each source matches (exact, case-insensitive)

Orange Book = active release from `EOBZIP_2026_08.zip` (48,761 products). IID = `iig_july_2026.zip`, file `IIR_OCOMM.csv`
(9,071 rows, members dated 2026-07-21, sha256 `d08cf074…980c987e`).

| Values | Distinct | Exact match to FDA list | Rows covered by exact |
|---|---|---|---|
| Orange Book routes vs SPL routes | 79 | **36** | 40,037 of 48,761 |
| Orange Book dosage forms vs SPL dosage forms | 117 | **75** | 39,499 of 48,761 |
| Orange Book strength units vs UCUM | 52 | **4** (MG, ML, MEQ, UCI) | 19,864 of 26,331 single-unit strengths |
| IID routes vs SPL routes | 59 | **59 (100%)** | 9,071 of 9,071 |
| IID dosage forms vs SPL dosage forms | 106 | **105** (only `DROPS` missing) | 9,004 of 9,071 |
| IID potency units vs UCUM | 23 | **2** (`mg`, `ml`) | 1,928 |

- **IID routes and dosage forms already use the SPL list.** FDA's "Most Recent Changes to the IID Database" page says FDA
  adopted SPL terminology for route, dosage form and units in July 2019 (https://www.fda.gov/drugs/drug-approvals-and-databases/most-recent-changes-iid-database).
- **The Orange Book does not.** It keeps older wording: `INJECTION` (route), `INJECTABLE` (form), `INHALATION`, `OTIC`,
  `ORAL-28`, multi-route values such as `INTRAMUSCULAR, INTRAVENOUS`, and `GM`/`MCG` for units.
- Raw overlap between the two sources (no mapping): routes 32 shared, 27 IID-only, 47 OB-only;
  dosage forms 62 shared, 44 IID-only, 55 OB-only.
- IID potency units are mostly not units: `%w/w` 889, `NA` 850, `%w/v` 597, `ADJ PH` 357, `mg/5ml` 177, plus 4,059 blank.

**What this means:** if REGX builds its vocabulary from Orange Book wording, the IID (the thing REGX checks formulations
against) needs a second mapping layer for 59 routes and 106 forms. If REGX uses the SPL list, the IID maps 1:1 with no
review, and only the Orange Book needs mapping.

## 4. INJECTION: how the two sources express injectables

- **Orange Book:** route `INJECTION` on 7,231 products, and dosage form `INJECTABLE` on 7,995. It does not say which
  injectable route.
- **SPL and IID:** there is **no `INJECTION` route** in the SPL list. The route is always the specific one, and "injection" lives
  in the **dosage form** (`INJECTION`, `INJECTION, SOLUTION`, `INJECTION, POWDER, FOR SOLUTION` …; 16 `INJECTION…` forms plus 2 `INJECTABLE…` forms in SPL).
- In the IID, rows with an injectable dosage form (`INJECT…`) use **42 different routes** (1,263 rows), led by INTRAVENOUS 428,
  INTRAMUSCULAR 241, SUBCUTANEOUS 161, INTRA-ARTICULAR 54, INTRALESIONAL 34. Also `PARENTERAL` 18, but also odd ones:
  `ORAL` 2, `RECTAL` 1, `DENTAL` 3, `IRRIGATION` 4.
- The dosage-form side is easy: OB `INJECTABLE` → SPL `INJECTION` is proposed as *likely*.
- The route side is not. One OB value would have to stand for many SPL routes.

### Three problems with the proposed answer

1. **"All injectable IID routes" is not a defined list.** Taken from the data, it would include ORAL and RECTAL. It needs
   a fixed, reviewed list of parenteral routes (the SPL routes a reviewer marks as injectable), not "whatever IID rows say".
2. **It can make an IID check too permissive.** IID limits are route-specific. If an IV product is matched against an
   INTRAVITREAL or INTRA-ARTICULAR record, the highest limit across routes could be applied to the wrong route.
   `backend/iid_assessment/matching.py` already refuses to auto-pick "the most favourable" value when several records
   match (`MULTIPLE_EXACT_MATCHES`); a one-to-many INJECTION rule must keep that behaviour.
3. It also needs code: `find_iid_candidates` (in `matching.py`) takes **one** `controlled_route_id`. Matching against a set of routes is a
   Phase 3+ change, not a mapping row.

### Question for iCretegy (draft)

> The FDA Orange Book lists 7,231 products with route "INJECTION", without saying intravenous, intramuscular,
> subcutaneous or other. The Inactive Ingredient Database (IID) always names the specific route.
>
> We propose: **Orange Book "INJECTION" matches all injectable IID routes and is flagged for reviewer confirmation.**
> In practice:
> (a) "injectable routes" means a fixed list that your regulatory reviewer approves (for example INTRAVENOUS,
> INTRAMUSCULAR, SUBCUTANEOUS, INTRADERMAL, INTRA-ARTICULAR …), not every route that happens to appear next to an
> injectable form in the IID;
> (b) REGX shows every matching IID record with its own route and limit, and never picks the highest limit automatically;
> (c) the reviewer confirms the actual route for the product before the result is used.
>
> Do you agree? If not, should REGX instead ask the user to pick the specific route for each Orange Book injectable
> product before any IID comparison?

## 5. How codes are stored today, and what seeding needs

From `backend/fda_data/models.py` on `regx-main@eedbf9c`:

- `ControlledRoute` / `ControlledDosageForm`: `code` (unique, max 50), `canonical_label`, `fda_source` (free text),
  `active_release` (FK to `FDADataSourceRelease`, nullable), `aliases` (JSON list), `lifecycle` (draft/active/retired).
- `ControlledUnit`: `code`, `symbol` (max 20), `dimension` (mass, volume, count, percentage, concentration),
  `conversion_factor_to_base`, `basis_requirements`, `aliases`, `active`. No source or release field.
- `iid_assessment.assess` looks routes up by `code` with `lifecycle="active"`; `fda_data.terminology.lookup_unit`
  matches unit `code`, `symbol` or alias, case-insensitive, and ignores `UnitMapping`.
- `fda_data/dispatch.py` deliberately refuses `fda_route_terminology` / `fda_dosage_form_terminology` imports: these
  are "governed vocabulary, not imported source data".

**Can the lists be seeded without a migration?**

- **Routes and dosage forms: yes.** Every field needed exists. Proposed use: `code` = NCI Thesaurus code (e.g. `C38288`;
  stable even if FDA rewords the label), `canonical_label` = SPL term (`ORAL`), `fda_source` = list name + page date +
  snapshot sha256, `active_release` = an `FDADataSourceRelease` of the existing `fda_route_terminology` /
  `fda_dosage_form_terminology` type, so the approve/activate lifecycle (approver ≠ loader) already applies.
  *Decided 2026-10-13:* `code` = NCI code. API callers pass `route_code`, so they will pass NCI codes.
- **Units: not fully.** UCUM codes fit in `symbol`, and mg/g/ug/mL/L fit the existing dimensions. But meq, mmol, curie
  family, IU, USP units and rates (`/h`, `/d`) have **no dimension**, units have **no version/source field**, and
  per-presentation units (`MG/VIAL`, 634 OB strengths) cannot be represented. Those need a model change (a migration),
  which is out of scope here.

### Proposed loader (NOT built)

`python manage.py load_spl_terminology --list routes|dosage-forms --snapshot <file.csv> --page-date YYYY-MM-DD`

- Reads a **saved, reviewed CSV snapshot** of the FDA table (term, NCI code). It does not fetch from fda.gov.
- Registers one `FDADataSourceRelease` (type `fda_route_terminology` / `fda_dosage_form_terminology`) with the snapshot's
  sha256 and the page date, so each load is a versioned, platform-level reference (no tenant FK).
- Upserts by NCI code: new terms are created as `lifecycle="draft"`; label changes are recorded, not silently overwritten;
  terms missing from the new snapshot become `retired`, never deleted (mappings point at them with `SET_NULL`).
- Activation (draft → active) happens only when that release is approved and activated by a different user.
- Idempotent: the same snapshot twice changes nothing. `--dry-run` prints the diff.
- Not a data migration: vocabulary stays an explicit, reviewed act, like the regulatory content gate.

## 6. Recommendation

1. **Routes and dosage forms:** adopt the FDA SPL lists (NCI codes) as `ControlledRoute` / `ControlledDosageForm`.
   The IID then maps 1:1 (59/59 routes, 105/106 forms); only the Orange Book needs reviewed mappings.
2. **Units (on hold, separate PR):** adopt UCUM codes, with written translation rules for Orange Book tokens (`GM`→`g`, `MCG`→`ug`, `MG/ML`→`mg/mL`).
   Percent basis, activity units and per-presentation units wait for a unit-model decision.
3. **INJECTION:** send the question in §4 to iCretegy before any route mapping for it is approved.
4. **Review:** use the regenerated workbook `orange_book_terminology_review_spl_2026-10-13.xlsx` (kept outside the repo,
   in `D:/Praverse/data/fda/mappings/`). The 2026-10-12 workbook is kept but superseded.

Workbook counts against the SPL lists (distinct values; products in brackets):

| | Exact | Likely | Unclear |
|---|---|---|---|
| Routes (79) | 36 (40,037) | 9 (939) | 34 (7,785) |
| Dosage forms (117) | 75 (39,499) | 10 (9,055) | 32 (207) |
| Units (52) | 4 (19,864) | 14 (2,743) | 34 (3,724) |

- "Likely" examples: `INHALATION`→`RESPIRATORY (INHALATION)`, `OTIC`→`AURICULAR (OTIC)`, `ORAL-28`→`ORAL`,
  `INJECTABLE`→`INJECTION`, `SOLUTION/DROPS`→`SOLUTION/ DROPS`, `CAPSULE, DELAYED REL PELLETS`→`CAPSULE, DELAYED RELEASE PELLETS`.
- Two "likely" routes need extra care: `SPINAL`→`INTRASPINAL` and `INTRATRACHEAL`→`ENDOTRACHEAL` are my reading, not FDA's.
- Most "unclear" routes (and 7,231 of their 7,785 products) are `INJECTION` plus multi-route values. A product holds one
  route today, so multi-route values need a model decision, not just a mapping.

## 7. Side finding: the IID parser would reject the real FDA file

`backend/fda_data/parsers.py` requires the columns `Inactive Ingredient`, `Route`, `Dosage Form`, `CAS Number`, `UNII`,
`Potency Amount`, `Potency Unit` (`IID_REQUIRED_COLUMNS`). The real July 2026 `IIR_OCOMM.csv` header is
`INGREDIENT_NAME,ROUTE,DOSAGE_FORM,CAS_NUMBER,UNII,POTENCY_AMOUNT,POTENCY_UNIT,MAXIMUM_DAILY_EXPOSURE,MAXIMUM_DAILY_EXPOSURE_UNIT,RECORD_UPDATED`.
An import of the real file would fail on missing columns, and the maximum daily exposure columns (filled on 4,059 rows) have no
place to go. **Not fixed here.** It is a separate change, and it should come before any IID-based work.

## 8. Not done, on purpose

- No mapping loaded or approved; no code list seeded; Phase 3 not started.
- No loader command, no migration, no parser fix.
