# Regulatory Technical Tools AI — Codebase Inspection Report

Repository: `D:\booking-demo-final`
Inspection date: 2026-07-14 (read-only; no code modified)

---

# 1. Repository Context

- **Current branch:** `devp0/feat/publish-booking-demo-final`
- **Current commit:** `b00c4297f8768ed7a2021da6b1fd254759fa23c3`
- **Backend framework:** Django 5.1.3 (`RAAI/settings.py`), DRF (`djangorestframework`, `djangorestframework-simplejwt`) present but lightly used.
- **Frontend framework:** Server-rendered Django templates (Bootstrap/Tailwind mix, jQuery/vanilla JS, Chart.js/GSAP for dashboards). No SPA framework (no React/Vue/Angular anywhere in the tree).
- **Apps:** `RATools/` (general "regulatory tools" — checklist automation), `AIDatabase/` ("483 Database AI" — FDA Form 483 / investigator / warning-letter analytics), `AdminMaster/` (auth + admin CRUD for checklist question banks and workflow assignment), `RAAI/` (project settings/urls/celery).

Module presence per the 12 topic areas in the request:

| Topic area | Found in |
|---|---|
| IIG checklist automation | `RATools/models.py` (`IIGChecklistUser`, `IIGAnswers`, etc.), `RATools/urls.py`, `RATools/views.py`, `templates/RATools/IIG/*.html` |
| FDA IIG database integration | **None found** — no lookup table, no FDA IIG data import/parsing anywhere in `*.py` |
| FDA Orange Book integration | **None found** — only external hyperlinks to fda.gov Orange Book pages in templates (manual reference), no data ingestion/model |
| HTML regulatory calculator integration | **None found** — no hits for "calculator" anywhere in `*.py` |
| Dissolution/impurity/stability trend calculators | **None found** — zero matches for "dissolution", "impurity", "stability trend" in `*.py` |
| ANDA/DMF checklist gap analysis | ANDA/DMF **checklists** exist (`RATools/models.py`: `ANDAUserReports`, `DMFChecklistUser`); "gap analysis" logic (automated deficiency prediction from checklist gaps) — **None found** |
| Deficiency database-backed predictive flagging | A "Deficiency" **library** exists but it belongs to **AIDatabase (483 Database AI)** — see Section 2 |
| Resolution playbook | `AIDatabase/views.py:4902` `playbook()` renders `templates/Playbook.html` — this is an **"FDA Inspection Playbook"** (483/inspection domain), static content only |
| Chatbot guidance across workflow | Chatbot code exists but is **entirely commented out** in `AIDatabase/views.py` and `AIDatabase/urls.py`; no chatbot in `RATools` at all |
| Word plug-in / drafting assistant | `python-docx` is a dependency but only used in `AIDatabase/models.py:612` to count words/pages of an uploaded file — not a drafting assistant |
| Section-wise reference guidance | **None found** as a backend feature; some templates reference CTD/eCTD numbering in free-text questions only |
| Zero-hallucination backend-only responses | Not applicable — no functioning chatbot to evaluate |
| Smart document versioning | **None found** — no version model, no `django-reversion` in `requirements.txt` |
| Document comparison | **None found** for regulatory documents. A **physical-product** comparison feature exists (`ProductComparison`/`TabletComparison`/`CapsuleComparison` in `RATools/models.py` — tablet/capsule size-shape-score vs RLD), unrelated to document diffing |
| Auto-tagging | **None found** |
| Doer → Reviewer → VP role workflow | A generic **Doer → up to 7 sequential Checker levels** workflow exists (see Section 8) — not literally named Doer/Reviewer/VP |
| Traceable actions / review gates | Sequential checker-level gating exists (`approved_by_checkers_level_1..7`); no timestamped audit records of who/when/why |
| 21 CFR Part 11 audit trail | **None found** — no audit trail model beyond Django's default `django.contrib.admin.LogEntry` (not used for this purpose) |

---

# 2. Separation from 483 Database AI

**Verdict: Partially separated (app-level split exists, but shared infrastructure and naming create real risk of confusion).**

Evidence:
- App-level code separation is real: `RATools/` (regulatory checklist tooling — IIG, ANDA, DMF, VP, Validation, Size/Shape/Score, White Paper) is a genuinely distinct Django app from `AIDatabase/` (Form 483 observations, investigator intelligence, GMPC, warning letters, Major CR deficiencies). URLs are namespaced under different app `urls.py` files (`RATools/urls.py` vs `AIDatabase/urls.py`), and models live in separate `models.py` files.
- However, both apps import from the **same** `AdminMaster/models.py` (`CustomUser`, `AssignChecker`) for auth and workflow, so role/permission logic is genuinely shared infrastructure, not duplicated — this is fine architecturally but means any new "Regulatory Technical Tools AI" role/workflow additions must be careful not to leak into 483 Database AI's checker assignment (`AssignChecker.REPORT_CHOICES` already interleaves ANDA/IIG/VP/DMF choices together with Form 483/Major CR/Warning Letter choices in one single `MultiSelectField`, `AdminMaster/models.py:46-130`).
- **Naming collision risk:** the term "Deficiency" is used in **both** apps for unrelated concepts:
  - In `AIDatabase/models.py` (lines ~40-107), "Deficiency" models (`ANDADeficiency`-style tables, exact class names redacted for brevity — see file) store **FDA 483 / Major CR** deficiency text by dosage form and CMC section — this is 483 Database AI content, **out of scope** for Regulatory Technical Tools AI.
  - The SOW's "deficiency database-backed predictive deficiency flagging" (item 7) does not exist as a feature anywhere; if built, it would need to reference the *existing* 483 deficiency library as a **read-only data source**, without merging the two apps' models.
- The `AIDatabase/views.py` "Playbook" (line 4902) is titled **"FDA Inspection Playbook"** and lives entirely in `AIDatabase` — it should **not** be confused with the "Resolution playbook" requested for Regulatory Technical Tools AI (item 8), which does not exist.
- The OpenAI-backed logic that does work (`AIDatabase/observation_summary.py`, `AIDatabase/filters.py:15 get_synonyms_from_chatgpt`) is 100% scoped to 483 observation summarization and 483 search-term synonym expansion — it does not touch IIG/ANDA/DMF/VP data at all.

**Risk:** Because `AssignChecker` already mixes 483/Major-CR/Warning-Letter report types with ANDA/IIG/VP/DMF report types in the same `REPORT_CHOICES` list and the same per-user MultiSelectField, any Regulatory Technical Tools AI role/workflow expansion (new report types, new "VP" sign-off tier, new audit trail) will by default get commingled with 483 Database AI checker assignments unless deliberately isolated (e.g., a separate `RegulatoryToolsAssignChecker` model or a `module` discriminator field).

---

# 3. Existing Regulatory Tool Modules

| Module | Status | Evidence |
|---|---|---|
| IIG checklist automation | Implemented but untested | Models: `RATools/models.py:172-251` (`IIGChecklistUser`, `IIGAnswers`, `IIGTableRowsAnswers`, `IIGAnswerSnapshot`, `IIGSnapshot`). Routes: `RATools/urls.py:220-389` (show/add/delete per dosage form: liposome, microsphere, DPI, inhalation, liquid oral, injection, MDI, semisolid, nasal, tablet, topical, transdermal). Views: `RATools/views.py` (e.g. `add_iig_liposome_checklist` at line 5798). Templates: `templates/RATools/IIG/*.html` (11 dosage-form pages). No `tests.py` coverage (see Section 10). |
| FDA IIG database integration | Missing | Searched `IIG` + `database`/`lookup`/`import` across `*.py`; only user-entered checklist answers exist (`IIGTableRowsAnswers` fields are free-text `CharField`s filled by the Doer, not populated from an FDA IIG dataset). No FDA IIG data file, importer, or model found. |
| FDA Orange Book integration | Missing (UI/label only) | 22 template hits for "Orange Book", all are outbound `<a href="https://www.accessdata.fda.gov/scripts/cder/ob/index.cfm">` hyperlinks or free-text instructions like `templates/RATools/ControlledCorrespondences/CCTemplate.html:42` ("Note: Take information of RLD from the Orange Book..."). No parser, model, or API integration in any `.py` file. |
| HTML regulatory calculator integration | Missing | Zero matches for "calculator" in any `*.py` file repo-wide. |
| Dissolution / impurity / stability-trend calculators | Missing | Zero matches for "dissolution", "impurity", or "stability" + "trend" in any `*.py` file. `pandas`/`matplotlib`/`seaborn` are dependencies but are used only for AIDatabase's 483/warning-letter chart generation (`AIDatabase/views.py` chart endpoints), not for any calculator logic. |
| ANDA checklist / gap analysis | Partial (checklist implemented; no automated gap analysis) | Models: `RATools/models.py:7-66` (`ANDAReportQuestions`, `ANDAUserReports`, `ANDAUserAnswers`). Routes: `RATools/urls.py:17-201` (12 dosage-form ANDA checklists). Views throughout `RATools/views.py` (e.g. block at lines 420-520 shows real Doer→7-level-Checker query logic for the Microsphere ANDA report). "Gap analysis" — i.e., automatically flagging which checklist answers indicate a regulatory gap — was not found; answers are simple yes/no/not_applicable with no scoring/flagging logic. |
| DMF checklist / gap analysis | Partial (checklist implemented; no automated gap analysis) | Models: `RATools/models.py:108-167` (`DMFChecklistUser`, `DMFReviewTableQuestion`, `DMFReviewAnswer`, `DMFModuleComment`, `DMFCATableQuestion`, `DMFCAAnswer`). Routes: `RATools/urls.py:216-219`. Template: `templates/RATools/DMF/DMFChecklist.html`, `templates/AdminMaster/DMF/DMFReviewForm.html`. No gap-scoring logic found. |
| Deficiency database-backed predictive flagging | Missing (only a manual 483/Major-CR deficiency library exists, in the *other* app) | `AIDatabase/models.py` contains rich-text deficiency libraries keyed by dosage form / CMC section (e.g. lines ~40-107), searchable via `AIDatabase/filters.py`, but this is curated reference text browsed manually — there is no logic anywhere that reads a Regulatory Technical Tools checklist answer and predicts/flags a matching deficiency. And this data belongs to 483 Database AI, out of scope. |
| Resolution playbook | Missing (only an unrelated "FDA Inspection Playbook" exists, in the *other* app) | `AIDatabase/views.py:4902` `playbook()` → `templates/Playbook.html`, titled "FDA Inspection Playbook | iPharmaAI Regulatory Compliance". Renders static accordion HTML with no backend model/data — no linkage to specific deficiencies or checklist answers, and it is a 483-domain feature, not a regulatory-tools resolution playbook. |
| Chatbot guidance across workflow | Prompt/code present but disabled — Broken/non-functional | All chatbot views (`chat_ui_view`, `chat_with_bot`, `clear_chat`, `new_chat`, `get_all_chat_histories`, `get_all_chat_by_specific_id`, `delete_chat_by_id`) are commented out in `AIDatabase/views.py:5317-5619` and their routes are commented out in `AIDatabase/urls.py:114-120`. Template `templates/AIDatabase/Chatbot/ChatUiwithHtmlReponse.html` exists but is unreachable (no live URL renders it). No chatbot code of any kind exists in `RATools`. |
| Word plug-in / Word drafting assistant | Missing | `python-docx` is imported once, in `AIDatabase/models.py:9,612`, solely to compute word-count/page-count of an uploaded `.doc` file for a metadata field — no drafting, templating, or Word add-in/plugin exists anywhere. |
| Section-wise reference guidance | Missing | No matches for structured CTD/eCTD section-to-requirement mapping logic in `*.py`. Some templates mention module/section numbers as static labels only (e.g. `templates/AIDatabase/ANDA/ANDAeCTDBase.html`). |
| Zero-hallucination backend-only responses | Not applicable / Missing | No functioning chatbot exists to apply this control to (see "Chatbot" row above and Section 7). |
| Smart document versioning | Missing | No version-tracking model found. The only "version" field anywhere is `dmf_version = models.CharField(...)` (`RATools/models.py:116`), a free-text field the Doer types in manually — not a system-managed version history. `django-reversion` / similar is not in `requirements.txt`. |
| Document comparison | Missing (for regulatory docs) — a different, physical-product comparison exists | `RATools/models.py:256-382` implements `ProductComparison`/`TabletComparison`/`CapsuleComparison` — comparing physical tablet/capsule attributes (shape, color, dimensions, pictures) between RLD and company product, with routes `RATools/urls.py` "Size, Shape & Score" section (390-398) and templates `templates/RATools/SizeShapeScore/SizeShapeScore.html`. This is real and working but is a **dimensional comparison tool**, not document version diffing. |
| Auto-tagging | Missing | No matches for tagging/auto-tag logic in `*.py`. |
| Doer → Reviewer → VP role workflow | Partial (functional but different structure than specified) | See Section 8 — a real Doer + up to 7 sequential numeric Checker levels exists (`approved_by_checkers_level_1..7` on nearly every checklist model in `RATools/models.py`), driven by `AdminMaster/models.py:44-179` (`AssignChecker`). There is **no** distinct named "Reviewer" role and **no** distinct named "VP" *role* (the acronym "VP" in this codebase means "Validation Package" — a dosage-form report category, e.g. `templates/RATools/VP/VPSolidOral.html` — not "Vice President" approver). |
| Traceable actions / review gates | Partial | Sequential gating exists (checker level *n* can only act once level *n-1* is `"True"`/`"Done"` — confirmed in query logic e.g. `RATools/views.py:465-508`), but there is no persisted, timestamped, user-attributed audit record of each action — only current-state boolean/choice fields are overwritten in place. |
| 21 CFR Part 11 audit trail | Missing | No matches for "audit_trail", "AuditLog", "Part 11", "immutable" in any `*.py` file. Django's built-in `django.contrib.admin.LogEntry` exists (framework default) but is not used by any Regulatory Technical Tools view for calculator inputs/outputs — and there are no calculators to audit in the first place. |

---

# 4. Data Source Inspection

| Data source | File path / expected ingestion path | Format supported | Parser/importer | Schema/model | Search/index | Source ref captured | Version captured | Gaps |
|---|---|---|---|---|---|---|---|---|
| FDA IIG (Inactive Ingredient Guide) | None — expected e.g. `AIDatabase/management/commands/import_iig_data.py`, does not exist | N/A | None found | None found | None | No | No | Entire dataset absent; IIG checklist fields (`IIGTableRowsAnswers`) are hand-typed by users, not populated from FDA data |
| FDA Orange Book | None — no ingestion path exists | N/A | None found | None found | None | No (only outbound links) | No | Entire dataset absent |
| ANDA/DMF/VP checklist question banks | `RATools/models.py` (`ANDAReportQuestions`, `DMFReviewTableQuestion`, `DMFCATableQuestion`, `VPReportQuestions`, `ValidationReportQuestions`, `GeneralReportQuestions`) — seeded via Django admin or management commands, no importer found in repo | DB rows (RichText) | None found (manual admin entry, per `RATools/admin.py`) | Yes — full model schema exists | Basic Django ORM filter only, no dedicated search index | N/A (internal question bank) | No version field | Question banks exist but there's no bulk import tooling checked into this repo |
| Deficiency reference library (483/Major-CR) | `AIDatabase/models.py` deficiency tables, populated via `AIDatabase/management/commands/import_deficiency_data.py` and `import_major_cr.py` | Likely Excel/CSV (see command names) | Yes — dedicated management commands exist | Yes | Yes, via `AIDatabase/filters.py` (django-filter based) | Partially (category/dosage/CMC fields) | No | **This is 483 Database AI data — out of scope for Regulatory Technical Tools AI**, listed here only to show what a "deficiency database" importer pattern would look like if replicated |
| Calculator reference data (dissolution/impurity/stability limits) | None | N/A | None | None | None | No | No | No calculator feature exists to need this data yet |
| Regulatory document uploads (for Word/versioning/comparison) | `media/` directory receives uploads (e.g. `IIGAnswerSnapshot.snapshot`, `TabletComparison.picture_trld`, etc., all `FileField`/`ImageField`) | Images/files, `.doc`/`.pdf` handled ad hoc in `AIDatabase/models.py:600-615` for page-count only | Minimal — `PyPDF2`/`python-docx` used only for page/word counting, not content extraction for chatbot/RAG | Files stored, not parsed into structured content | None | No | No | No systematic document ingestion/versioning pipeline exists |

---

# 5. Output and Report Verification

For each of the 12 output attributes requested, checked against every module that produces a "report" (ANDA/IIG/DMF/VP/Validation/White Paper checklists — the only report-generating code that exists):

| Output attribute | Status | Evidence |
|---|---|---|
| Structured table output | Present | All checklist "show_*_report" views render structured HTML tables of question/answer pairs, e.g. `templates/RATools/ANDA/*.html`, `templates/RATools/IIG/*.html` |
| Reference-source citation | Missing | Answers are free-text/boolean with no linkage to a specific FDA rule/guidance citation field in any model |
| Calculation logic shown | Missing | No calculators exist, so no calculation logic to show |
| Gap explanation | Missing | No gap-analysis logic exists (Section 3) |
| Resolution guidance | Missing | No resolution-playbook linkage exists (Section 3) |
| Confidence / limitation statement | Missing | No AI-generated content is produced by these modules (they are manual data-entry forms), so no confidence scoring applies |
| Version number | Missing | No version field on any checklist/report model except the free-text `dmf_version` CharField (`RATools/models.py:116`), which is not a managed report version |
| "Generated by" attribution | Partial | `user = models.ForeignKey(CustomUser, ...)` on every checklist model records who created it, but is not surfaced as a formal "generated by" report field/label consistently in every template |
| "Reviewed by" attribution | Partial | Checker levels are recorded as boolean/choice state per level, but there's no `reviewed_by` user FK captured at the time of approval — only whichever `AssignChecker.assigned_checker_level_N` M2M set was active at check time (mutable, not a point-in-time snapshot) |
| Audit trail ID | Missing | No audit-trail model exists (Section 9) |
| Export availability | Partial | `download_document` (`RATools/urls.py:401-405`) and `open_file`/`download_folder_zip` (`RATools/urls.py:14-15`) exist for downloading uploaded reference documents/folders, but there is no "export this generated report as PDF/DOCX" feature found for the checklist reports themselves |

---

# 6. Backend-Only / Existing UI Integration Check

Existing pages/components that could plausibly host Regulatory Technical Tools AI features without a redesign:

- **Module hub:** `templates/RATools/ModuleHome.html` and `templates/RATools/RAToolsBase.html` — the existing landing/nav shell for all RATools checklist types (IIG/ANDA/DMF/VP/Validation/White Paper). Served by `RATools/views.py` `moduletemplate`/`module_view` (`RATools/urls.py:11-12`).
- **Checklist "show/add/report" triad pattern:** every existing dosage-form checklist (e.g. IIG Liposome: `show_iig_liposome` / `add_iig_liposome_checklist` / report template) is a reusable pattern — new tools (e.g. a dissolution calculator) could follow the same `show_*` (list) → `add_*` (form) → `*_report` (detail) view triad and reuse the same base templates (`templates/RATools/baseShow.html`).
- **Admin-side review forms:** `templates/AdminMaster/DMF/DMFReviewForm.html`, `templates/AdminMaster/ANDA/AndaEditForms.html`, `templates/AdminMaster/VP/VPEditForm.html` — existing checker/edit UI that a new module's review step could imitate.
- **Dashboard/report viewer:** `templates/483dashboard.html`, `templates/gmpcdashboard.html`, `templates/auditiq.html` (AIDatabase) show working chart/report viewer patterns (Chart.js) that a "stability trend calculator" output could reuse for trend visualization, **without importing any 483-specific data**.
- **Chatbot panel shell:** `templates/AIDatabase/Chatbot/ChatUiwithHtmlReponse.html` — a chat UI shell already exists in markup even though its backend is disabled; this could be repurposed as the "chatbot guidance" surface for Regulatory Technical Tools AI, provided a **new**, separately-scoped view/urls entry is built (not by re-enabling the existing 483-scoped, commented-out one).
- **Export buttons:** `download_document`/`download_folder_zip` (`RATools/urls.py:14-15,401-405`) — reusable file-download endpoints.
- **Role-based UI:** templates branch on `user.role` (`admin`/`company_user`/`company_checker`) throughout `RATools/views.py` (e.g. lines 427-509) — this pattern is reusable for Doer/Reviewer gating but would need a genuinely new role or a `module` scoping field to avoid mixing with 483 Database AI checker assignments.

Recommendation per scope item (18 items), what to reuse vs. build, and what not to touch:

| # | Scope item | Host in existing UI? | Backend/API needed | Minimal UI connection | Do NOT change |
|---|---|---|---|---|---|
| 1 | IIG checklist automation | Yes — already implemented | None (extend existing) | None | Existing IIG models/views/templates |
| 2 | FDA IIG database integration | Yes, as a lookup panel inside existing IIG add/report pages | New importer + `IIGReferenceEntry`-style model | Add a lookup widget to `templates/RATools/IIG/*.html` | Existing `IIGChecklistUser` schema |
| 3 | FDA Orange Book integration | Yes, same pattern as #2 | New importer + `OrangeBookEntry` model | Replace static hyperlink text with a live lookup field | — |
| 4-6 | HTML calculators (dissolution/impurity/stability/etc.) | Yes, as new pages under `RATools/ModuleHome.html` nav | New calculator views + calc logic modules | New nav entries following the `show_*`/`add_*` triad | Existing checklist logic |
| 7 | ANDA/DMF gap analysis | Yes, as an added section on existing report pages | New scoring/flagging logic reading existing `ANDAUserAnswers`/`DMFCAAnswer` | Add a "Gaps" panel to `show_anda_*_report`/`show_dmf_report` templates | Existing answer models (read-only consumption) |
| 8 | Deficiency-backed predictive flagging | Only via a **read-only, clearly-labeled cross-reference** to AIDatabase's deficiency library — do not merge apps | New service layer that queries `AIDatabase` deficiency models read-only from `RATools` | Add "related deficiencies" panel | Do not modify `AIDatabase` deficiency models/views |
| 9 | Resolution playbook | New feature — do not reuse `AIDatabase.playbook()` (that's the FDA Inspection Playbook) | New model + view scoped to RATools | New nav entry in `RAToolsBase.html` | `AIDatabase/views.py:4902 playbook()` |
| 10 | Chatbot guidance | New, separately-scoped backend; may reuse the existing (currently dead) chat UI template as a visual starting point | New views/urls, new OpenAI call chain scoped only to Regulatory Technical Tools data | New chat panel embedded in `ModuleHome.html` | Do not re-enable the commented-out `AIDatabase` chatbot code as-is (it's 483-scoped and has other issues, see Section 7) |
| 11 | Word plug-in / drafting assistant | Not hostable in existing UI — needs new Office Add-in or server-side `.docx` generation endpoint | New service using `python-docx` (already a dependency) generatively, not just for page-counting | New "Export to Word" button on report pages | — |
| 12 | Section-wise reference guidance | Yes, as tooltips/side-panel on checklist question templates | New CTD-section-to-question mapping model | Add reference sidebar to checklist templates | — |
| 13 | Zero-hallucination backend-only chatbot | N/A until #10 is built | Retrieval layer restricted to RATools models | — | — |
| 14 | Smart document versioning | New — no existing UI to host it in | New `DocumentVersion` model + diff view | New "Version History" tab on report pages | — |
| 15 | Document comparison | New (distinct from existing `ProductComparison`, which is physical-attribute comparison, not document diffing) | New diff service (e.g. `difflib`) | New "Compare" button | Do not conflate with `ProductComparison`/`TabletComparison`/`CapsuleComparison` |
| 16 | Auto-tagging | New | New tagging model + auto-tag logic (rule-based or LLM-based) | Tag chips on report list views | — |
| 17 | Doer→Reviewer→VP workflow | Partial reuse of existing Doer/Checker-level pattern | Rename/extend to explicit `Reviewer`/`VP` roles or add a `role_stage` concept on top of existing checker levels | Reuse `AssignChecker`-style UI, but new model to avoid mixing with 483 assignments | Existing `AssignChecker.REPORT_CHOICES` (don't silently append 18 new choices into the same shared list without a module discriminator) |
| 18 | 21 CFR Part 11 audit trail | New — nothing to host it in yet | New immutable `AuditTrail` model logging every calculator/checklist state change | New "Audit Log" tab on report pages | — |

---

# 7. Chatbot and Zero-Hallucination Verification

- **Source-only mode:** Not applicable — no functioning chatbot exists. The only active OpenAI calls are:
  - `AIDatabase/observation_summary.py` — summarizes a single FDA 483 observation's text using `gpt-4.1-mini` (`SUMMARY_MODEL`, line 35). This is a **summarization** task over a single provided observation, not open-domain Q&A, and it is scoped to 483 data.
  - `AIDatabase/filters.py:15 get_synonyms_from_chatgpt()` — expands a search term into synonyms via `gpt-4o-mini` for 483/Major-CR filtering (mostly called from commented-out call sites; only one live call site remains, line 932).
- **Citation enforcement:** Not implemented in either active OpenAI call — outputs are plain summarized/synonym text with no source citation requirement.
- **Retrieval restricted to backend data:** Not applicable (no RAG/retrieval pipeline exists at all — no vector store, no embeddings, no document retrieval code found anywhere in `*.py`).
- **"Not found" / graceful-decline handling:** Not implemented; `observation_summary.py` has retry/error handling (`SUMMARY_MAX_ATTEMPTS`, lines ~264-372) for API failures, but no explicit "answer not found in data" guard for hallucination.
- **No-hallucination guards:** None found (no system-prompt constraints requiring the model to only use provided context were found beyond the summarization prompt itself, which was not fully inspected line-by-line but shows no citation/verification step).
- **Prompt-injection protection:** None found.
- **Security note (adjacent finding, not in the 18-item scope but material to any chatbot work):** `AIDatabase/filters.py` lines 11-14 and `AIDatabase/views.py` lines 5328-5465 contain **multiple live-looking OpenAI API keys hardcoded in source** (one active, several commented out). No `OPENAI_API_KEY` environment variable is referenced in `.env.example` or `RAAI/settings.py`. This is a credential-hygiene risk that should be remediated (rotate keys, move to env vars) before any new chatbot work reuses this pattern.

**Conclusion:** There is no chatbot to evaluate for zero-hallucination compliance; the requested "chatbot guidance across workflow" (item 9) and "zero-hallucination" (item 12) capabilities must be built from scratch, and should **not** be built by re-enabling `AIDatabase`'s commented-out, 483-scoped, key-hardcoded chatbot code.

---

# 8. Role Workflow Verification

- **Backend roles:** `AdminMaster/models.py:21-25` `CustomUser.ROLE_CHOICES` = `admin`, `company_user`, `company_checker`. There is **no** `doer`, `reviewer`, or `vp` role value anywhere. "Doer" is a *behavioral* label applied in code/UI to whichever `company_user` created a checklist (`is_completed_by_doer` boolean field, e.g. `RATools/models.py:33,117,177,269,407,464,506`), not a stored role.
- **Route authorization:** Views branch on `request.user.role` (e.g. `RATools/views.py:427-509`), gated by Django's `login_required`-style decorators (per prior audit note) — standard Django auth, not a custom permission-class system.
- **Review gates:** Confirmed real and sequential — `AssignChecker` (`AdminMaster/models.py:44-179`) assigns up to 7 distinct checker levels per report type via `assigned_checker_level_1..7` M2M fields; each checklist model's `approved_by_checkers_level_1..7` `CharField` (choices `False`/`True`/`Done`) is checked before the next level's queryset includes that item (e.g. `RATools/views.py:465-508` shows level *n* only sees items where level *n-1* = `"True"`).
- **Approval/rejection:** Only "True"/"Done" states are modeled; there's no explicit "Rejected"/"Sent back" state or reason-for-rejection field found in any checklist model.
- **Comments:** Present for some modules only — `DMFModuleComment` (`RATools/models.py:142-146`, has `comment`+`status`), `GeneralCheckerComments` (`RATools/models.py:737-740`), and a `comment` field on `ValidationUserAnswers`/`VPUserAnswers`/`GeneralUserAnswers` (`RATools/models.py:438,495,776`). ANDA and IIG checklists have **no** comment field.
- **Change reason:** Not captured anywhere (no `reason_for_change`/`change_note` field found).
- **Version locking:** Not implemented — no field prevents concurrent edits or locks a report at a given approval stage beyond the boolean gate itself.
- **Audit trail:** None (see Section 9).
- **Frontend state display:** Templates do show current approval state (`show_buttons_doer` boolean controls doer-side button visibility; checker-level views filter by state as shown above), so the *current* state is visible, but *history* of state changes is not.
- **Export-after-review:** No distinct "final, reviewed" export/PDF-lock feature found; `download_document`/`download_folder_zip` are generic file downloads, not review-gated exports.

**Conclusion:** A working multi-level Checker gate exists and is more granular than a simple 3-tier Doer/Reviewer/VP model (it supports up to 7 levels), but it does not match the SOW's named 3-role model, lacks rejection/change-reason capture, and has no audit trail — all of which would need to be added.

---

# 9. Audit Trail / Part 11-Style Control Verification

Searched for: `AuditTrail`, `AuditLog`, `audit_trail`, `Part 11`, `immutable`, `timestamp.*user` across all `*.py` files — **no matches for any of them.**

Checked for the requested properties against the *closest* existing thing (checklist approval state fields) — none apply because there is no audit trail model at all:

| Property | Status |
|---|---|
| 12 audit event types (create/edit/submit/approve/reject/etc.) | Missing — no event log table exists; only current-state fields are overwritten in place |
| Immutability | Missing — approval fields are plain mutable `CharField`s, directly overwritable |
| Timestamp captured | Partial — only `IIGSnapshot.date` (`auto_now_add`) and a few `DateField`s exist; no `created_at`/`updated_at` timestamp pair on the checklist/report models themselves |
| User ID captured | Partial — creator (`user` FK) is captured at creation, but not who performed each subsequent approval action |
| Role captured at time of action | Missing |
| Previous/new value captured | Missing |
| Reason for change captured | Missing (except the narrow `DMFModuleComment.status`/`comment` and similar comment fields noted in Section 8) |
| Exportability of audit trail | Missing (nothing to export) |
| Reviewability of audit trail | Missing |

Django's built-in `django.contrib.admin.LogEntry` exists as a framework default (records superuser admin-site CRUD actions) but is not referenced by any custom Regulatory Technical Tools view, so it provides no coverage for calculator inputs/outputs or checklist approvals performed through the app's own UI.

**Conclusion: Missing entirely.** A 21 CFR Part 11-style audit trail would need to be built from scratch — likely a new `AuditTrail` app/model capturing `(actor, role, timestamp, object_type, object_id, field, old_value, new_value, reason, ip_address)` with `on_delete` protection and no update/delete permitted at the DB layer.

---

# 10. Testing Verification

All three apps' `tests.py` were read in full:

- `RATools/tests.py` — 3 lines, `from django.test import TestCase` + comment only. **Boilerplate stub.**
- `AIDatabase/tests.py` — 3 lines, identical stub. **Boilerplate stub.**
- `AdminMaster/tests.py` — 4 lines, identical stub (plus a comment). **Boilerplate stub.**

No other test files, `tests/` directories, `pytest.ini`, `conftest.py`, or CI test configuration were found in the repository (only `build.sh`/`render.yaml` for deployment, no test-runner CI config).

| Test area (of the 16 requested) | Status |
|---|---|
| All 16 listed test areas (unit tests for checklists, calculators, gap analysis, chatbot, versioning, comparison, role workflow, audit trail, etc.) | **Missing** — Cannot run, because none exist. Classification: **Missing** for every area; "Cannot run" is moot since there is nothing to execute beyond Django's default `manage.py test` no-op. |

**Conclusion:** This repository has **no real automated test coverage** for any module, regulatory-tools or 483-related. This is a pre-existing condition across the whole codebase, not specific to the (largely unbuilt) Regulatory Technical Tools AI scope.

---

# 11. Gap Summary and Implementation Backlog

| Requirement | Current Status | Evidence | Gap | Priority | Suggested Implementation |
|---|---|---|---|---|---|
| 1. IIG checklist automation | Implemented (untested) | `RATools/models.py:172-251`, `RATools/urls.py:220-389` | Add test coverage | Low | Add `tests.py` cases for save/approve flow |
| 2. FDA IIG database integration | Missing | No matches found | Full build needed | High | New model + management-command importer of FDA IIG dataset; lookup UI in checklist forms |
| 3. FDA Orange Book integration | Missing | Only outbound links in templates | Full build needed | High | New model + importer (FDA Orange Book data files); lookup UI |
| 4. HTML regulatory calculator integration | Missing | No "calculator" in `*.py` | Full build needed | Medium | New calculator views/templates framework, reusable across calc types |
| 5. Dissolution/impurity/stability calculators | Missing | No matches in `*.py` | Full build needed | Medium | New calc logic modules + trend charting (reuse Chart.js pattern from `483dashboard.html`) |
| 6. Other technical calculators | Missing | No matches | Full build needed | Medium | Same as above, define scope with iCretegy first |
| 7. ANDA/DMF gap analysis | Partial (checklist exists, no gap logic) | `RATools/models.py` ANDA/DMF models | Add scoring/flagging on top of existing answers | High | New service reading `ANDAUserAnswers`/`DMFCAAnswer`, no schema change needed to start |
| 8. Deficiency-backed predictive flagging | Missing (only 483 deficiency data exists, separate app) | `AIDatabase/models.py` deficiency tables | Build read-only cross-reference service; do not merge apps | High | New `RATools` service querying `AIDatabase` models read-only |
| 9. Resolution playbook | Missing (only unrelated "FDA Inspection Playbook" exists) | `AIDatabase/views.py:4902` | Full build in `RATools`, distinct from existing playbook | Medium | New model + view + templates |
| 10. Chatbot guidance | Disabled/dead code only, 483-scoped | `AIDatabase/views.py:5317-5619` (commented out) | Full new build, scoped to Regulatory Technical Tools data only | High | New app/module; do not reuse hardcoded keys or 483-scoped code |
| 11. Word plug-in / drafting assistant | Missing (docx used only for page counting) | `AIDatabase/models.py:9,612` | Full build | Medium | Server-side `.docx` template generation via `python-docx`; consider Office Add-in later |
| 12. Section-wise reference guidance | Missing | No matches | Full build | Low-Medium | New CTD-section mapping model + sidebar UI |
| 13. Zero-hallucination responses | N/A (no chatbot) | Section 7 | Depends on item 10 | High (once 10 starts) | Retrieval-restricted prompt design, citation enforcement, refusal handling |
| 14. Smart document versioning | Missing | No version model; `django-reversion` absent from `requirements.txt` | Full build | Medium | New `DocumentVersion` model, snapshot-on-save pattern |
| 15. Document comparison | Missing (distinct from existing physical-attribute comparison) | `RATools/models.py:256-382` is unrelated | Full build | Medium | New diff service (e.g. Python `difflib`) over versioned documents |
| 16. Auto-tagging | Missing | No matches | Full build | Low | Rule-based tagging first; LLM-based later if chatbot lands |
| 17. Doer→Reviewer→VP workflow | Partial (generic 7-level Doer/Checker exists, no named Reviewer/VP roles) | `AdminMaster/models.py:21-25,44-179`; `RATools/models.py` `approved_by_checkers_level_1..7` on every model | Decide whether to rename/restructure existing checker levels into named roles, or layer a new `role_stage` on top | High | Extend `CustomUser.ROLE_CHOICES` or add stage metadata; avoid touching shared `AssignChecker.REPORT_CHOICES` without a module discriminator |
| 18. 21 CFR Part 11 audit trail | Missing | No matches anywhere | Full build | Critical (blocking for compliance claims) | New immutable `AuditTrail` model + middleware/service layer capturing every calculator/checklist state change |
| Supporting: separate audit/role infra from 483 Database AI | Partially shared today | `AssignChecker.REPORT_CHOICES` mixes both domains | Risk of cross-contamination as new report types are added | High | Add a `module` field (`"regulatory_tools"` vs `"483_database"`) to `AssignChecker`/future audit models, or split into two assignment tables |
| Supporting: test coverage | Missing everywhere | All three `tests.py` are stubs | No regression safety net for any new feature | Medium | Establish a test baseline alongside any new Regulatory Technical Tools AI feature work |
| Supporting: OpenAI key hygiene | Hardcoded keys committed | `AIDatabase/filters.py:11-14`, `AIDatabase/views.py:5328-5465` | Secrets exposed in git history | Critical | Rotate keys, move to env vars (`OPENAI_API_KEY`), before building any new chatbot |

---

# 12. Final Recommendation

1. **Is Regulatory Technical Tools AI currently separate from 483 Database AI?** Partially. The two live in genuinely distinct Django apps (`RATools` vs `AIDatabase`) with separate models/views/urls, but they share `AdminMaster`'s user/role/checker-assignment infrastructure, and `AssignChecker.REPORT_CHOICES` already interleaves both domains' report types in one list — a real risk of future contamination if not deliberately partitioned.

2. **What is already implemented?** A substantial, working set of **checklist-automation** modules for IIG (11 dosage forms), ANDA (12 dosage forms), DMF, VP/Validation Package (9 dosage forms), API Validation/Verification, Size/Shape/Score physical-product comparison, and White Paper/Appendix forms — each with real models, CRUD views, and a genuine multi-level (up to 7) Doer→Checker approval gate. None of this is tested by automated tests.

3. **What is partially implemented?** ANDA/DMF checklists exist but have no automated gap analysis; the Doer/Checker workflow exists but lacks named Reviewer/VP roles, rejection states, change reasons, and version locking; some report types have comment fields, others don't.

4. **What is missing?** FDA IIG database integration, FDA Orange Book integration, all regulatory/technical calculators (dissolution, impurity, stability trend, HTML calculators generally), deficiency-database-backed predictive flagging, a resolution playbook, a working chatbot (existing chatbot code is commented out, 483-scoped, and has hardcoded API keys), a Word drafting assistant/plug-in, section-wise reference guidance, smart document versioning, document comparison (for regulatory documents, as opposed to the unrelated physical-product comparison that does exist), auto-tagging, and any 21 CFR Part 11-style audit trail.

5. **What can be integrated into existing UI without redesign?** New calculators, gap-analysis panels, and a resolution playbook can be added as new pages/sections under the existing `RATools/ModuleHome.html` navigation shell and `show_*`/`add_*`/`*_report` view triad pattern; a chatbot panel can reuse the existing (currently dead) `ChatUiwithHtmlReponse.html` markup as a visual starting point only.

6. **What backend/API modules are needed?** FDA IIG and Orange Book data importers + lookup models; calculator logic services; a gap-analysis/flagging service reading existing checklist answers; a new, separately-scoped chatbot/RAG pipeline; a document versioning + diff service; a Word-document generation service (beyond the current page-counting-only use of `python-docx`); an immutable audit-trail model/service; and either an extension of `CustomUser.ROLE_CHOICES` or a new role-stage layer for Doer/Reviewer/VP.

7. **What data is required from iCretegy?** FDA IIG dataset (current release, in a parseable format), FDA Orange Book dataset (or confirmation to rely on FDA's public download files), dissolution/impurity/stability acceptance-limit reference tables per dosage form, resolution-playbook content (what remediation guidance should say per deficiency category), and any Word document templates the drafting assistant should target.

8. **What should be built first?** (a) Fix the credential hygiene issue (rotate/relocate the hardcoded OpenAI keys) before any new AI work touches this codebase; (b) the audit-trail model, since every other new feature (calculators, gap analysis, chatbot) should be logging into it from day one rather than retrofitted later; (c) the FDA IIG/Orange Book data importers, since calculators and gap analysis will likely depend on this reference data.

9. **What should be deferred for feasibility review?** The Word plug-in/drafting assistant (Office Add-in scope is a separate engineering effort from the rest of the Django app); the chatbot's "zero-hallucination" guarantee (needs a retrieval architecture decision — vector DB vs. structured-query-only — before implementation starts); auto-tagging (low priority, and its usefulness depends on whether document versioning/comparison ships first).

10. **What are the biggest risks?** (1) **Data-domain leakage** — `AssignChecker.REPORT_CHOICES` and shared `CustomUser` role fields already mix 483 Database AI and regulatory-tools report types; adding 18 new scope items without a `module` discriminator will make role/permission logic increasingly hard to reason about and audit. (2) **No test safety net** — every existing module (and the entire proposed 18-item scope) has zero automated test coverage, so new work compounds an existing regression risk. (3) **Committed secrets** — live-looking OpenAI API keys are hardcoded in `AIDatabase/filters.py` and `AIDatabase/views.py`; any new chatbot work must not inherit this pattern, and the existing keys should be rotated. (4) **Compliance claim risk** — building calculators or workflow features and *labeling* them "21 CFR Part 11 compliant" or "zero-hallucination" without the underlying audit-trail/retrieval-restriction infrastructure (both currently absent) would be a false claim to end users/regulators.
