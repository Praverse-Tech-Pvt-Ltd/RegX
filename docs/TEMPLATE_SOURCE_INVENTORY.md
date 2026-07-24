# Template Source Inventory (Milestone 3)

Read-only inventory of legacy regulatory-template sources available on this development machine, taken before any import work began. No content was copied, imported, or activated during this phase — this document records catalog metadata only (table names, row counts, structural characteristics), never the underlying question/template text itself.

**Location surveyed:** the local, untracked (gitignored) legacy directories and SQLite files sitting alongside this repository checkout — `RATools/`, `AdminMaster/`, `AIDatabase/`, `RAAI/`, and `db*.sqlite3`. None of these are tracked on `regx-main` or any REGX branch; they are local-machine-only legacy artifacts. No repository history search was needed since REGX (`regx-main`) is a clean-room implementation that has never contained this content (see [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md)).

## Eligible — genuine template/question-bank content

These tables store reusable question/template *definitions* (not per-user execution answers), each backed by a CKEditor `RichTextField`.

| Source table | Legacy model | Est. rows | Category | Format | HTML | Numbering | Mojibake | Apparent duplicates | Eligibility |
|---|---|---|---|---|---|---|---|---|---|
| `RATools_andareportquestions` | `ANDAReportQuestions` | 44 | ANDA checklist, 8 report types (MDI/DPI, Nasal Spray, Ophthalmic, Parenteral, Semi-Solid, Solid Oral, Transdermal, General ANDA) | SQLite row, CKEditor HTML | Yes (`<p>`, entities) | No | None observed in sample | None (0 exact dupes) | **Eligible** |
| `RATools_dmfreviewtablequestion` | `DMFReviewTableQuestion` | 13 | DMF review, modules 3.2.S.1 / 3.2.S.2 | SQLite row, CKEditor HTML | Yes | **Yes** — numbers embedded in text ("1. United States Adopted Name...") | None observed | None checked (small set) | **Eligible** — numbering must be split out during normalization, not dropped |
| `RATools_dmfcatablequestion` | `DMFCATableQuestion` | 9 | DMF corrective-action, 4 modules | SQLite row, CKEditor HTML | Yes | **Yes** — same embedded-numbering pattern | None observed | None checked | **Eligible** |
| `RATools_validationreportquestions` | `ValidationReportQuestions` | 17 | Validation, 3 report types (API-Validation, API-Verification, Drug Product Validation) | SQLite row, CKEditor HTML | Yes | No | **Yes** — private-use bullet glyph (``, a Wingdings-derived character from pasted Word content) found embedded in text | Not checked | **Eligible**, requires mojibake normalization pass |
| `RATools_vpreportquestions` | `VPReportQuestions` | 46 | "VP" **report type** ("Verification Protocol"), 8 dosage forms — unrelated to the Doer/Reviewer/VP *role* naming used elsewhere in this codebase; see the disambiguation comment already present in `RATools/models.py` above `RegulatoryRole` | SQLite row, CKEditor HTML | Yes | No | None observed | **Yes** — 14 exact-duplicate question rows out of 46 (same question text reused across multiple dosage-form report types — plausible legitimate reuse, not necessarily an error) | **Eligible**, duplicate candidates must route through review, not auto-collapse |
| `RATools_generalreportquestions` | `GeneralReportQuestions` | 92 | General, 2 categories (Drug Substance / Drug Product general requirements) | SQLite row, CKEditor HTML | Yes | No | None observed | 1 exact duplicate | **Eligible** |
| `RATools_ccbestpractice` | `CCBestPractice` | 5 | Controlled Correspondence best practices | SQLite row, CKEditor HTML | Yes | No | **Yes** — category value literally stored as `DO�S` (replacement character in place of an apostrophe, a mid-word encoding-corruption artifact) | None checked (5 rows) | **Eligible**, category value needs a reviewed normalization mapping |

**Total eligible candidate rows: 226**, across 7 tables / 6 template families (ANDA, DMF-Review, DMF-CA, Validation, VP-report, General, CC-best-practice).

## Requires review — structurally ambiguous or not separable data

| Source | Reason | Disposition |
|---|---|---|
| `RATools_cctemplate` (`CCTemplate`) | Named "template" but is actually a per-submission **execution form** (applicant name, NDA number, signature image, contact details) with 0 rows populated. No reusable question content to extract — it's a form-instance record, not a question bank. | Requires review; likely excluded once confirmed no template content exists in the model itself |
| `RATools_appendixwhitepaper` (`AppendixWhitePaper`) | Named "White Paper" but its ~80 fields are hardcoded Django `BooleanField`/`CharField` form fields (e.g. `ir_tablet`, `category_1_device`) in **code**, not question rows in the database. 0 rows populated. The "template" here is the Python class definition, not migratable tabular data. | Requires review; a code-level (not data-level) migration approach would be needed, out of this milestone's scope |
| IIG feature (`IIGChecklistUser`, `IIGAnswers`, `IIGTableRowsAnswers`, etc.) | No `IIGReportQuestions`-equivalent table exists anywhere in the schema. The IIG feature is a hardcoded parameterized form (RLD dose, strength, ingredient tables), not a data-driven question bank. | **Excluded** — no separable template source exists to migrate; matches the explicit instruction not to implement IIG calculations this milestone |
| `RegulatoryRole`, `RegulatoryReviewGate`, `RegulatoryAuditTrail` (RATools) | Legacy governance/workflow infrastructure tied to the legacy `CustomUser` model and legacy runtime. Valuable as a **design reference** (REGX's own template lifecycle in this milestone independently arrives at a similar Doer → Reviewer → VP approval-gate shape), but this is legacy runtime state, not content to import. | Requires review as design reference only; excluded from data migration |
| `RegulatoryGapAnalysisReport` | AI-generated gap-analysis **output**, not template content. Also explicitly out of scope ("Do not begin ... AI ... scoring" this milestone). | Excluded |

## Explicitly excluded

| Source | Reason |
|---|---|
| `AIDatabase/models.py` (`Form483Master`, `Form483System`, `Form483Observation`, `Form483ObeservationContent`, `WarningLetter`, `WarningLetterPdf`, `ObservationImage`, `ChatMessage`, `ChatHistory`, `SystemChecklist`, plus an app-local `ANDA`/`ANDAeCTD`/`ANDATechnicalAcceptance` set, `MajorCR`) | Entire app is 483/warning-letter/inspection-analytics/AI-chat content. **AIDatabase must never be imported**, full stop — per explicit instruction, no further inspection of its models beyond class-name classification was performed. Note: this app has its own, *separate* `ANDA` model set distinct from `RATools.ANDAReportQuestions` — the two are not the same data and must not be confused. |
| `AdminMaster/models.py` (`CustomUser`, `AssignChecker`) | User/assignment infrastructure tied to the legacy identity model. Not template content. |
| `RATools_*useranswers`, `RATools_*userreports`, `RATools_*checklistuser`, `RATools_*comment`, `RATools_generaltable13/14`, `RATools_productcomparison`, `RATools_tabletcomparison`, `RATools_capsulecomparison` | Per-user checklist **execution** data (answers, approvals, comments, product-comparison results) — not template/question definitions. Out of scope for a template-migration milestone regardless of eligibility; would belong to a future checklist-execution milestone, explicitly not started here. |
| `RATools_demorequest` (`DemoRequest`) | Marketing demo-booking data. Unrelated to regulatory templates. |
| `db_old.sqlite3`, `db_17_1_2.sqlite3` | Stale snapshots of the same schema (59 tables, same shape as `db.sqlite3`'s 63). `db_old.sqlite3` predates the current question-bank data (0 rows in `RATools_andareportquestions` vs. 44 in the live `db.sqlite3`). Redundant/duplicate backups — `db.sqlite3` is the authoritative live source. |
| `db_corrupted.sqlite3` | Named and shaped (48 vs. 63 tables) as a known-bad snapshot. Not inspected further. |
| `db.sqlite3.bak_before_customuser_column_fix`, `db.sqlite3.bak_before_gap_analysis_migration`, `db.sqlite3.bak_before_regulatory_migration` | Pre-migration safety backups, by naming convention. Duplicate/redundant relative to the live database. |
| `static/`, `staticfiles/`, `media/`, `templates/` (legacy Django template/static dirs at repo root) | Legacy UI assets (HTML templates, CSS/JS, uploaded media), not structured regulatory question-bank content. Not inventoried further — wrong artifact type for this migration. |
| `REGULATORY_TECHNICAL_TOOLS_BASELINE_REPORT.md`, `REGULATORY_TOOLS_CODEBASE_INSPECTION_REPORT.md` (repo root) | Pre-existing narrative inspection reports, not a data source. Read as background context for this inventory; not a migration source themselves. |

## Summary

| Disposition | Count |
|---|---|
| Eligible | 6 template families (7 tables), 226 candidate rows |
| Requires review | 5 (2 empty "template" tables with no separable content, IIG's non-existent question bank, legacy governance infra as reference-only, gap-analysis output) |
| Excluded | AIDatabase (entire app, unread beyond class names), AdminMaster identity tables, all `RATools` execution/answer/comment tables, `DemoRequest`, all stale/duplicate database backups, legacy static/template/media directories |
| Unknown | None — every candidate reachable from the surveyed locations was classified |

No content was imported, copied into REGX source, or activated during this phase, consistent with the "do not import during inventory" requirement. The eligible sources above are candidates for a future, explicitly-approved import batch through the pipeline built in this milestone — building the pipeline does not itself constitute approval to run it against this data.
