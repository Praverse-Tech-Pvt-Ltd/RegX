# IID blocker analysis: why 0 of 9,071 IID records are calculable

**Date:** 2026-11-06. **Status:** report only (read-only analysis of local data). Answers Pratham's second direction (`docs/decisions/2026-11-07-pratham-direction-2.md`) §6: how many records are unusable because of absent numbers, unsupported units and unapproved mappings, **without double counting**.

## Data and method

- **Data:** the real FDA IID file of July 2026 (`IIR_OCOMM.csv`, 9,071 rows), as loaded locally (release `bef6285c-2779-44f7-b9a7-e1bc6e4e126c`, active). The **164 proposed IID mappings** (59 routes, 105 dosage forms, PR #94) are **treated as applied**, as in the 2026-11-06 end-to-end test run. **None of them is approved**; this is a "what if the proposals were approved" view.
- **Read-only:** the analysis exported fields with `\copy` and classified them outside the database. The local database was backed up first (`D:/Praverse/backups/regx-local-db/2026-11-06/regx_before_iid_blocker_analysis.dump`) and verified unchanged afterwards (9,071 records, 59 + 105 mappings, 265 audit events, 4 releases).
- **One primary category per record**, first match wins, in this order: (1) no numeric limit at all; (2) route or dosage form without a mapping (incl. `DROPS`); (3) daily-exposure only (needs Q8); (4) potency with an unsupported unit representation; (5) potency with a supported unit (calculable once controlled units exist); (6) other.
- **"Supported unit"** = a unit string the minimal unit model in `docs/CONTROLLED_UNITS_DESIGN.md` can represent exactly without assuming a basis the file does not state.
- Script and raw output: review hand-off (`classify.py`, `evidence_iid_blocker_breakdown.txt`).

## Primary blocker (no double counting)

| # | Primary blocker | Records | Share | Unblocked by |
|---|---|---|---|---|
| 1 | **No numeric limit at all** (potency unit `NA` 850, `ADJ PH` 357; no daily exposure either) | **1,207** | 13.3 % | Nothing: the FDA row has no limit to compare against. Shown as "no IID limit published" |
| 2 | **Route or dosage form not mapped** (all `DROPS`) | **41** | 0.5 % | Reviewer resolves `DROPS` per record (review package item 3) |
| 3 | **Daily-exposure only** (maximum daily exposure in mg, no per-unit potency) | **4,059** | 44.7 % | **Q8 per-day rule** (iCretegy + reviewer) **and** a structured maximum daily dose on the formulation |
| 4 | **Potency with an unsupported unit** (`mg/mg`) | **16** | 0.2 % | Reviewer states the basis ("per mg of what"); until then refused |
| 5 | **Potency with a supported unit** | **3,748** | 41.3 % | **Controlled units** (engineering, now) + **mapping approvals** (reviewer) |
| 6 | Other | 0 | 0 % | — |
| | **Total** | **9,071** | 100 % | |

**Reading it:**
- **Absent numbers:** 1,207 records (13.3 %) can never be compared; that is the FDA data, not a REGX gap.
- **Unsupported unit representations:** 16 records (0.2 %).
- **Unapproved terminology:** **all 9,071** records depend on mapping approvals today (0 of 164 approved). With the proposals approved, only the 67 `DROPS` records remain unmapped (41 here as primary, 26 already in category 1).
- **The two big levers:** controlled units unlock up to **3,748** records (41.3 %) for per-unit comparison once mappings are approved; the Q8 rule unlocks up to **4,059** (44.7 %) for per-day comparison once confirmed and once formulations carry a structured maximum daily dose.
- **No record has both** a per-unit potency and a daily exposure (0 of 9,071), so the per-unit and per-day rules never compete for the same row.

## Overlap (every cause present on a record)

Each record appears in exactly one row. "supported_unit" means the record has a potency with a supported unit.

| Causes present | Records |
|---|---|
| daily_exposure_only | 4,059 |
| supported_unit | 3,748 |
| no_numeric_limit | 1,181 |
| mapping_missing + supported_unit | 41 |
| no_numeric_limit + mapping_missing | 26 |
| unsupported_unit | 16 |
| **Total** | **9,071** |

Mapping is the only cause that overlaps with another (67 `DROPS` records). Every other record has exactly one cause.

## Unit strings

**Category 4 (unsupported):**

| Unit | Records | Why |
|---|---|---|
| `mg/mg` | 16 | Mass per mass with no stated basis: per mg of the active, of the formulation, or of a dosage unit? Not convertible without a basis the file does not give |

**Category 5 (supported):**

| Unit | Records | Representation in the minimal model |
|---|---|---|
| `mg` | 1,914 | Mass per dose unit |
| `%w/w` | 872 | Percentage, weight in weight |
| `%w/v` | 596 | Percentage, weight in volume |
| `mg/5ml` | 177 | Concentration, mass per volume (normalised to mg/mL) |
| `mg/1ml` | 125 | Concentration, mass per volume |
| `%v/v` | 11 | Percentage, volume in volume |
| `ml/5ml` | 11 | Volume per volume (normalised to mL/mL) |
| `mg/15ml` | 9 | Concentration |
| `mg/120ml` | 8 | Concentration |
| `ml` | 7 | Volume per dose unit |
| `mg/100ml` | 4 | Concentration |
| `ml/1ml` | 4 | Volume per volume |
| `mg/2.5ml` | 2 | Concentration |
| `ml/15ml` | 2 | Volume per volume |
| `mg/0.1ml`, `mg/1000ml`, `mg/140ml`, `mg/0.2ml`, `mg/10ml`, `mg/20ml` | 1 each | Concentration |

**Daily exposure:** all 4,059 values are in `mg` (per day).

**Caveat on category 5:** "calculable once units exist" means REGX can represent the limit exactly. A comparison still needs the formulation's own quantity **in the same representation** (for example a `%w/w` limit is compared with the formulation's `%w/w`, never with mg per tablet unless the reviewer approves a conversion with a stated unit weight). See `docs/CONTROLLED_UNITS_DESIGN.md` for allowed and refused conversions.

## What this means for SOW 2.2

An end-to-end real-data IIG comparison is possible first for **category 5 records with `mg` per dose unit** (1,914 records) once (a) the unit model exists, (b) the relevant route and dosage-form mappings are approved by the named reviewer, and (c) the comparison rule is approved. Percentage and concentration limits follow with the same model, compared like with like.
