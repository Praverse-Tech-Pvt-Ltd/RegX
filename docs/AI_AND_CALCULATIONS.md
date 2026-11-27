# AI and calculations: where a model could touch a number (2026-11-27)

**Short answer:** today, **no AI and no statistical or machine-learning model touches any number, status or pass/review result in REGX.** Every number is plain decimal or exact-fraction arithmetic. Every status comes from fixed rules in a fixed order.

**The only AI-made content in REGX** is free text: warning-letter summaries copied from a spreadsheet column at import time. It is stored and searched, never used in a decision.

All `file:line` references are on `regx-main` at 4ff74d7. The full code search is in the review hand-off (`report__ai_and_calculations.md`), and the main points were re-checked by hand.

## 1. Where AI or a model appears in the code

| Place | What it is | Touches a number or status? |
|---|---|---|
| Backend and frontend dependencies (`backend/requirements/*.in`, `frontend/package.json`) | No AI or ML library at all (no openai, anthropic, numpy, sklearn …) | — |
| `backend/inspections/management/commands/import_inspections.py:155` | Copies an existing `ai_summary` spreadsheet column into `WarningLetter.summary` (`inspections/models.py:84-85` says it was "LLM-generated … by a separate pipeline") | **No.** Free text, shown and searched only. REGX generates nothing |
| `backend/inspections/views.py:116-133` | Search is a plain text match; the legacy AI query expansion was deliberately not carried over | No |
| `backend/templates_registry/models.py:430` (`FUZZY_SIMILARITY`) | Declared, never produced: only exact matches are made (`templates_registry/duplicates.py:29-46`) | No |
| `backend/iig_checklist/calculation_registry.py:538` | A guard that refuses `eval(` / `exec(` in calculation definitions | No (it prevents code execution) |
| `company_site/AIDatabase/observation_summary.py:332, 350` (legacy app, separate service) | OpenAI `gpt-4.1-mini` writes text summaries into an Excel column; only runs if `OPENAI_API_KEY` is set, which `compose.yaml` never does | **No.** Text, and **no REGX code imports it**: import-linter forbids it (`backend/pyproject.toml:46` and the `*-no-legacy-django-apps` contracts). Caveat: four ported apps are outside import-linter's `root_packages` (`pyproject.toml:36`); a search shows they import no legacy app today |
| `backend/external_integrations/` | Generic HTTPS connector for document import and frozen-package push (`models.py:35-79`, `transport.py`) | No AI provider |

## 2. The calculation and decision code: fixed rules only

| Step | Rule | Where |
|---|---|---|
| IID match | Exact ingredient + controlled route + controlled dosage form + active release; several matches → a person must pick; never "the most favourable" | `backend/iid_assessment/matching.py:79-143` |
| Unit comparison | Same family and same basis only; exact fractions; result is only "at or below" or "above" | `backend/iid_assessment/comparison.py:36-72, 180-274` |
| Formulas A–F (% w/w, daily exposure, % and difference of potency and MDE) | Decimal arithmetic, version `1.0.0` | `backend/iid_assessment/calculations.py:14, 77-237` |
| Final status (five possible) | Fixed order: no match → not comparable → review → exceeds → review → pass | `backend/iid_assessment/decisions.py:84-235` |
| Explanation text | Rewrites the sentence only, "never changes the match status or the decision status" | `backend/iid_assessment/reasons.py:10-13` |
| Checklist gap status | Not applicable / review / unanswered / gap / no gap, from the answer only | `backend/iig_checklist/gap_analysis.py:245-316` |

The only non-fixed value anywhere in these steps is the `generated_at` timestamp (`calculations.py:50-51`). It records when a run happened and feeds no value or status.

## 3. PR #129 (AI foundation) is not merged

- `gh pr view 129`: state **OPEN**, mergedAt **null**, head `1a525fd`.
- `git merge-base --is-ancestor 1a525fd origin/regx-main` → exit 1, so it is **not** in `regx-main`.
- No `ai_gateway` code exists on `regx-main`.
- **If merged as it stands:** it adds a text-only gateway (stub provider, off by default, health-check and benchmark prompts only). No IID, checklist, formulation or gap-analysis file is in its diff, so it would not let AI touch a number or status.
- It is parked by the owner until the provider and E2E are confirmed in writing (owner, 2026-11-26; recorded in the overview update in docs PR #176, not merged yet).

## 4. Can the user see the source and release date behind every fetched value?

**No. For every fetched value the answer is no on the release date, and mostly no on the source file.**
- The release record has a `publication_date` field (`backend/fda_data/models.py:124`). No screen shows it, and it is empty for both FDA releases in our data.
- In the 2026-11-27 run, none of the 12 IID preview screens showed a file name or a date (`docs/evidence/CALC_RUN_LOSARTAN_2026-11-27.md`).

| Fetched value | Screen | Source file shown? | Release date shown? | Where |
|---|---|---|---|---|
| Orange Book search rows (trade name, application, strength, RLD/RS, discontinued) | Product page, reference search | **No**: only "in the active release" in the empty-result message | **No** | FE `formulations/[publicId]/page.tsx:217, 223-250` |
| Chosen reference ("Application 020386-003") | Product page | **No**: an "FDA SOURCE" badge only; the trade name is not kept | **No** | FE `formulations/[publicId]/page.tsx:169-172` |
| Unit meanings list | Version page, add component | **No** | **No** | FE `components/QuantityMeaningSelect.tsx:12-70` |
| Active IID release | IID preview | **No**: an editable UUID box | **No** | FE `iid-assessments/preview/page.tsx:240-245, 342-345` |
| IID candidate / selected record (per-unit value, daily maximum) | IID preview | **No**: an "FDA SOURCE" badge on the per-unit value only | **No** | FE `preview/page.tsx:53-73, 446-488` |
| IID values used in a comparison | IID preview | **Partly**: "IID source row: row:NNNN" and "IID release: <UUID>", no file name | **No** | FE `preview/page.tsx:162-173` |
| Frozen IID record in a saved assessment | Saved assessment page (no screen links to it) | **No** | **No** | FE `iid-assessments/[publicId]/page.tsx:100-109` |
| FDA-derived checklist defaults (IID potency, MDE, route) | Checklist execution | **No**: the value itself is not shown either | **No** | FE `iig-checklists/executions/[executionPublicId]/ChecklistResponses.tsx:811-814` |

**What would fix it** (not done, needs an owner decision):
- show, next to each fetched value, the release's file name, the FDA publication date and the import date;
- fill `publication_date` at import.
