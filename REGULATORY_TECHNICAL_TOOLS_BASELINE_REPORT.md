# Regulatory Technical Tools AI — Baseline Report (Phase 0)

Generated as the required baseline before any Phase 1+ implementation work on the
Regulatory Technical Tools AI module inside `RATools`.

## 1. Repository identity

| Item | Value |
|---|---|
| Repository path | `D:\booking-demo-final` |
| Current branch | `devp0/feat/publish-booking-demo-final` |
| Current commit | `b00c4297f8768ed7a2021da6b1fd254759fa23c3` |
| Working tree | Dirty — see "Uncommitted state" below |
| Django version (installed, `.venv`) | 5.1.3 |
| Python | 3.13.14 |

### Uncommitted state at time of this report

```
 M .claude/launch.json
 M .env.example
 M AIDatabase/context_processors.py
 M RAAI/celery.py
 M RAAI/settings.py
 M requirements.txt
?? REGULATORY_TOOLS_CODEBASE_INSPECTION_REPORT.md
?? build.sh
?? render.yaml
```

These are all carry-over from prior session work (env-var secret migration, Render
deployment scaffolding, and the separate `REGULATORY_TOOLS_CODEBASE_INSPECTION_REPORT.md`
audit). None of them are part of this Phase 0 baseline and none touch RATools.

## 2. Apps present

| App | Purpose | urls.py | models.py | views.py |
|---|---|---|---|---|
| `RATools` | **Regulatory Technical Tools** (checklists, comparisons, reports) | 667 lines | 806 lines | 14,250 lines |
| `AIDatabase` | **483 Database AI** — FDA Form 483 observations, warning letters, GMPC, investigator analytics, deficiency data | 123 lines | 690 lines | 7,326 lines |
| `AdminMaster` | Shared auth (`CustomUser`), shared role-assignment (`AssignChecker`) | 136 lines | 272 lines | 1,781 lines |

Top-level routing (`RAAI/urls.py`) mounts each app under its own prefix — this part of the
separation is clean:

```python
path('ratools/', include('RATools.urls')),
path('aidatabase/', include('AIDatabase.urls')),
path('adminmaster/', include('AdminMaster.urls')),
```

## 3. RATools — current modules (regulatory tools scope)

Models (`RATools/models.py`, 806 lines, no migrations committed — schema only exists via
a pre-existing sqlite snapshot, see Section 8):

- **ANDA checklists**: `ANDAReportQuestions`, `ANDAUserReports`, `ANDAUserAnswers` — per-dosage-form
  checklist storage (MDI/DPI, Liposome, Microsphere, Nasal, Transdermal, Ophthalmic, Semi-Solid,
  Solid Oral, General ANDA — confirmed via `RATools/urls.py:17-201`, one route trio per dosage form).
- **DMF checklists**: `DMFChecklistUser`, `DMFReviewTableQuestion`, `DMFReviewAnswer`,
  `DMFModuleComment`, `DMFCATableQuestion`, `DMFCAAnswer` (`RATools/urls.py:215-219`).
- **IIG checklists**: `IIGChecklistUser`, `IIGAnswers`, `IIGAnswerSnapshot`,
  `IIGTableRowsAnswers`, `IIGSnapshot` — routes per IIG proportionality category (DPIs,
  Inhalation, Liquid Orals, Injection/Otic/Ophthalmic, MDIs, Nasals, Semisolids,
  Tablets & Capsules, Topical Solutions, Transdermal, Liposomes, Microspheres —
  `RATools/urls.py:220+`).
- **Product comparison**: `ProductComparison`, `TabletComparison`, `CapsuleComparison` —
  Size/Shape/Score-style physical comparison, not document diffing.
- **Validation reports**: `ValidationReportQuestions`, `ValidationUserReports`, `ValidationUserAnswers`.
- **VP reports**: `VPReportQuestions`, `VPUserReports`, `VPUserAnswers` — "VP" here means
  "Verification Protocol" report set (API-VALIDATION / API-VERIFICATION / DRUG PRODUCT
  VALIDATION, per dosage form), **not** a "Doer/Reviewer/VP" personnel role — see Section 6.
- **General checklist / White Paper**: `GeneralChecklistUSer`, `AppendixWhitePaper`,
  `AppendixTableRowsAnswers`, `GeneralAnswer`, `GeneralCheckerComments`, `GeneralTable13`,
  `GeneralTable14`, `GeneralReportQuestions`, `GeneralUserAnswers`.
- **Controlled Correspondence**: `CCBestPractice`, `CCTemplate`.
- `DemoRequest` — public "schedule a demo" form capture, unrelated to any of the above.

**No models exist for**: FDA IIG database (external reference data), Orange Book, regulatory
calculators (dissolution/impurity/stability), a standalone deficiency database inside RATools,
document versioning, document comparison (in the "redline diff" sense), auto-tagging, or an
audit-trail/event-log table.

## 4. AIDatabase — current modules (483 Database AI scope, for boundary reference only)

Models (`AIDatabase/models.py`, 690 lines):

`Form483Master`, `Form483System`, `Form483Observation`, `Form483ObeservationContent`, `ANDA`,
`ANDAeCTD`, `ANDATechnicalAcceptance`, `MajorCR`, `ChatMessage`, `WarningLetter`, `ChatHistory`,
`ExactNameFileSystemStorage`, `ObservationImage`, `WarningLetterPdf`, `ObservationImageExcelMaster`,
`WarningLetterExcelMaster`, `Form483ExcelNewData`, `WarningLetterExcelNewData`,
`UserCheckedUpdate`, `SystemChecklist`, `GMPCExcelMaster`, `GMPCExcelFilter`,
`InvestigatorThemedKeywords`.

**Important cross-boundary finding**: `AIDatabase.models.ANDA` and `AIDatabase.models.MajorCR`
(`AIDatabase/models.py:38-107`) are **deficiency lookup tables** — `main_category` × `dosage_form`
× `cmc_section` × `deficiency_type` × `category_of_deficiency` → `deficiency` (rich text). This is
functionally the SOW's item 7, "Deficiency database-backed predictive deficiency flagging," but it
currently lives inside the 483/AIDatabase app, not RATools, and is named `ANDA` — the same name as
three unrelated RATools checklist models (`ANDAReportQuestions`/`ANDAUserReports`/
`ANDAUserAnswers`). See Section 6 for the resulting risk.

`ChatMessage`/`ChatHistory` (`AIDatabase/models.py:111-149`) are 483-scoped chat models — see
Section 7 for why they must not be reused for a RATools chatbot.

## 5. AdminMaster — shared models

`AdminMaster/models.py` (272 lines):

- **`CustomUser`** (`AbstractUser` subclass, `AUTH_USER_MODEL`) — `role` field with
  `ROLE_CHOICES = [admin, company_user, company_checker]`. **There is no `doer`, `reviewer`, or
  `vp` role value anywhere in this choice list.** Other fields: `internal_team`,
  `fda_deficiency_database` (boolean flag — access gate, not a data table),
  `complete_response_database` (boolean flag), `subscription_end_date`.
- **`AssignChecker`** — the actual workflow engine. One row per user, with:
  - `assigned_report`: a `MultiSelectField` whose `REPORT_CHOICES`
    (`AdminMaster/models.py:46-130`) **interleaves both domains in a single flat list** — RATools
    items (ANDA dosage forms, DMF, IIG categories, VP reports, White Papers, Controlled
    Correspondence) sit alongside explicitly 483/AIDatabase items (`'Form 483'`,
    `'Warning Latter'`) and ANDA-*Deficiency*/Major-CR-*Deficiency* entries that map to the
    AIDatabase `ANDA`/`MajorCR` deficiency tables described in Section 4, not the RATools ANDA
    checklist models.
  - `assigned_checker_level_1` through `assigned_checker_level_7`: seven independent
    `ManyToMany(CustomUser)` fields, each filtered to `role='company_checker'` — this is the "up
    to 7 checker levels" workflow. There is no ordering/state-machine enforcement visible at the
    model level (no `status`, no `current_level` field) — level progression logic, if any, lives
    in `RATools/views.py` and was not traced line-by-line in this baseline pass.
  - `level_report_1..39` — per-report-type integer level counts.
  - `report_level_json` / `checkers_json` — denormalized snapshots rebuilt on every `save()`.
  - No `reason`, `comment`, `rejected_at`, `approved_at`, or history field on this model —
    approval/rejection commentary, if it exists, is not stored here.

**Conclusion**: the "Doer/checker workflow" is real and substantial (multi-level assignment), but
it is **not** a Doer→Reviewer→VP named role chain as specified in the SOW — it's `company_user` →
up to 7 anonymous `company_checker` levels, with no distinct Reviewer or VP role identity, no
visible approval/rejection audit fields, and its `REPORT_CHOICES` list already spans both product
domains.

## 6. Separation from 483 Database AI — classification

**Partially separated**, consistent with the earlier `REGULATORY_TOOLS_CODEBASE_INSPECTION_REPORT.md`
audit, with one new concrete finding from this pass:

| Layer | Verdict | Evidence |
|---|---|---|
| Django apps | Separated | `RATools` vs `AIDatabase` are distinct apps, distinct files |
| URL routing | Separated | `/ratools/` vs `/aidatabase/` prefixes, no cross-includes |
| Models | Separated in file, **not in namespace** | `AIDatabase.ANDA`/`MajorCR` are deficiency data that semantically belongs to Regulatory Technical Tools scope, but is modeled inside AIDatabase and shares the class name `ANDA` with three RATools models |
| Shared role/workflow model | **Mixed** | `AdminMaster.AssignChecker.REPORT_CHOICES` is one flat list spanning both domains (confirmed, `AdminMaster/models.py:46-130`) |
| Chatbot | N/A yet | No working chatbot in either app; existing commented-out chatbot code and `ChatMessage`/`ChatHistory` models are 483-scoped (`AIDatabase/models.py:111-149`) |
| Auth/user model | Shared by design | Single `CustomUser` across both apps — expected for one login system, not a violation |

**Risk if left mixed while building Regulatory Technical Tools AI:**

1. Any new "assign this report to a checker" UI for a new regulatory-tools feature (e.g. a
   calculator, a gap-analysis report) will, if implemented naively, either have to append to the
   same shared `REPORT_CHOICES` list (deepening the mixing) or fork a parallel mechanism
   (duplicating the workflow engine). Both are worth flagging explicitly before Phase 1 work
   touches `AssignChecker`.
2. A future "deficiency database" built for Regulatory Technical Tools AI (SOW item 7) must not be
   confused with, or accidentally query, the existing `AIDatabase.ANDA`/`MajorCR` tables — those
   are pre-existing 483-adjacent deficiency data with a different data model and, per the task
   instructions, out of scope for this module. New deficiency-database work should live in
   `RATools.models` under non-colliding names.
3. `role='company_checker'` is a single flat role with no level semantics baked into the user
   record itself — a Doer→Reviewer→VP hierarchy, if required by SOW item 16, cannot currently be
   expressed without either extending `ROLE_CHOICES` or introducing a separate role/assignment
   model scoped to Regulatory Technical Tools only (to avoid retroactively changing 483 workflow
   behavior).

## 7. Existing chatbot code

Confirmed still commented out and 483-scoped, unchanged since the prior audit:

- `AIDatabase/views.py:5328-5329, 5464-5465` — commented-out `openai.OpenAI(api_key=...)`
  instantiations tied to 483 report generation, **hardcoded key strings still present in the
  comments**.
- `AIDatabase/filters.py:14` — **live, uncommented** `openai.api_key = "sk-proj-2llREpG..."` —
  confirmed still present and unresolved at time of this baseline (flagged previously, not yet
  fixed or rotated).
- No chatbot code of any kind exists inside `RATools`.

**This blocks any AI-powered work in Phase 1+ per the task's own constraint** ("Hardcoded OpenAI
keys were found in AIDatabase files and must be removed/rotated before any AI work"). Any phase
that introduces chatbot guidance, predictive deficiency flagging via LLM, or zero-hallucination
retrieval must not proceed until this is remediated — tracked as a blocking risk below, not
addressed in this Phase 0 pass since Phase 0 is baseline-only.

## 8. Migrations and schema

`RATools`, `AIDatabase`, and `AdminMaster` have **no migration files** — `RATools/migrations/`,
`AIDatabase/migrations/`, `AdminMaster/migrations/` do not exist on disk and are explicitly
gitignored (`.gitignore:12-14`). The working local schema comes entirely from a pre-existing
sqlite snapshot (`db_17_1_2.sqlite3`, copied to `db.sqlite3` for local runs). Generating fresh
migrations from current `models.py` against that snapshot previously failed with a foreign-key
mismatch (`RATools_validationuserreports` → `RATools_validationreportquestions`), confirming real
schema drift between the models file and the snapshot.

**Consequence for this project**: any new model added for Regulatory Technical Tools AI needs its
own migration generated and committed (breaking from the app's current no-migrations pattern is
unavoidable — Django cannot create new tables without one), and that migration must be verified
against the actual local dev database before being treated as safe.

## 9. Existing tests

```
$ python manage.py test
Found 0 test(s).
Ran 0 tests in 0.000s
NO TESTS RAN
```

All three `tests.py` files are Django's default boilerplate with zero real test code:

```python
# RATools/tests.py, AIDatabase/tests.py, AdminMaster/tests.py
from django.test import TestCase
# Create your tests here.
```

There is no test infrastructure (no factories, no fixtures, no `pytest.ini`/`pytest-django`
config in `requirements.txt`) to build on. Phase 1+ test work starts from zero.

## 10. `python manage.py check` result

```
System check identified some issues:

WARNINGS:
?: (ckeditor.W001) django-ckeditor bundles CKEditor 4.22.1 which isn't supported anymore
   and does have unfixed security issues...

System check identified 1 issue (0 silenced).
```

Passes with one pre-existing, unrelated warning (CKEditor version). No errors.

## 11. Existing security risks relevant to this project

1. **Live hardcoded OpenAI API key** — `AIDatabase/filters.py:14`. Blocks any AI-powered
   Regulatory Technical Tools AI work per the task's own stated precondition. Not fixed in this
   Phase 0 pass (baseline is inspection-only).
2. **No migrations committed** for any of the three apps — a structural risk for reliably adding
   new Regulatory Technical Tools AI models later; each new model will require careful migration
   generation and verification against the real dev DB (see Section 8).
3. **Zero test coverage** — no regression safety net exists; every Phase 1+ change is unverified
   by anything except manual/agent-driven inspection unless new tests are written alongside it.
4. **Shared workflow model (`AssignChecker`) already mixes both domains** in one choices list —
   a design risk for keeping Regulatory Technical Tools AI cleanly separated going forward (see
   Section 6).

## 12. Summary table — SOW scope vs. current RATools state

| SOW item | Current state | Evidence |
|---|---|---|
| 1. IIG checklist automation | Exists, manual, untested | `RATools/models.py:172-255`, `RATools/urls.py:220+` |
| 2. FDA IIG database integration | Missing | No external IIG reference data model or importer found |
| 3. FDA Orange Book integration | Missing | No model, no importer |
| 4. HTML regulatory calculator integration | Missing | No calculator route/view found |
| 5. Dissolution/impurity/stability calculators | Missing | No calculator logic found |
| 6. ANDA checklist gap analysis | Checklist exists, no gap analysis | `RATools/models.py:7-70`; no scoring/gap logic found |
| 6. DMF checklist gap analysis | Checklist exists, no gap analysis | `RATools/models.py:108-171`; no scoring/gap logic found |
| 7. Deficiency database + predictive flagging | Deficiency data exists but **misplaced** in AIDatabase | `AIDatabase/models.py:38-107` (`ANDA`, `MajorCR`) — no predictive logic anywhere |
| 8. Resolution playbook | Missing | No model/view found |
| 9. Chatbot guidance | Missing (483-scoped remnants only) | `AIDatabase/views.py:5328+`, `AIDatabase/models.py:111-149` |
| 10. Word plug-in / drafting assistant | Missing | `python-docx` is a dependency but only used for something unrelated per earlier audit (needs re-verification in Phase 1) |
| 11. Section-wise reference guidance | Missing | No implementation found |
| 12. Zero-hallucination backend-only responses | N/A — no chatbot exists yet | — |
| 13. Smart document versioning | Missing | No version field/model found in RATools |
| 14. Document comparison | Only physical-product comparison exists (Size/Shape/Score), not document diffing | `RATools/models.py:256-387` |
| 15. Auto-tagging | Missing | No tagging model/field found |
| 16. Doer→Reviewer→VP workflow | Partial — `company_user`→7 checker levels exists, but no named Doer/Reviewer/VP roles | `AdminMaster/models.py:8-43, 44-273` |
| 17. Traceable actions / review gates | Partial at best — level assignment exists, no visible approve/reject/comment/history fields | `AdminMaster/models.py:44-273` |
| 18. 21 CFR Part 11 audit trail | Missing | No audit/event-log model found anywhere in RATools or AdminMaster |

---

**Phase 0 status: complete.** No code was modified in this phase — this was inspection and
baseline capture only, per instructions. Proceeding to Phase 1 requires the user's confirmation of
scope/order, and the blocking OpenAI-key issue (Section 7/11) should be resolved before any phase
that adds chatbot or LLM-based predictive logic.
