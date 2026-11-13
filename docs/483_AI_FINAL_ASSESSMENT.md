# 483-AI-final: technical assessment (static, read-only)

**Date:** 2026-11-13. **Asked for by:** Pratham's third direction (Step 2), via Maanav.
**Method:** static reading of a bare mirror of the private org repository `483-AI-final`, fetched 2026-11-13 (90 branches, 2,880 commits). **Not done:** the application was not run, no container was started, no API key was set, no external service was called. Its tests were **not run**: the backend needs Postgres and a network package install, so they cannot run fully offline (README: `DATABASE_URL` and `JWT_SECRET` are required even to collect tests).
**Reference branch:** `claude/cr84-answer-dashboard` (most recent, 2026-11-13; 1,858 commits ahead of `main`). `main` was last updated 2026-07-31 and is **not** the live code.
**What this document holds:** file paths, counts and my own summaries only. No client data, no credential values, no host addresses, no user names of client staff.

Confidence labels: **[Read]** = I read the code or doc; **[Grep]** = inferred from file names / keyword search, not read in full; **[Doc claim]** = stated in the repository's own docs, not verified.

---

## 0. Bottom line

- **This is a real, large, deployed 483 product, not a prototype.** Product name in the repo: **AuditMind** (formerly iPharmaAI). FastAPI backend, React frontend, Postgres, Redis, Qdrant, a self-hosted model. [Read]
- **It is in client UAT now** on a single GPU server (E2E Networks), behind Caddy basic auth, with a client access window and paid-AI budgets enforced by ledgers. Last documented cutover 2026-11-02. [Doc claim: `HANDOFF_20261102.md`, `README.md`]
- **Almost all of it was written by one contributor, `Devpt1904`** (2,735 of 2,880 commits), who is **still active today (2026-11-13)**. Our overview §0 presumes this person has left; that needs correcting.
- **Measured answer quality is not acceptable yet, by its own team's numbers:** on a 209-item blind-graded control bank, 43 correct and 51 critical errors (candidate-5); 0 of 55 multi-turn sequences fully correct. A later, not-deployed round reports 48 critical. [Doc claim]
- **No formal client acceptance or written sign-off was found.** Files named "client acceptance" are the developer's own test runs against the live lane. The two "Client QA" PDFs are vendor-produced Q&A samples prepared *for* client sign-off; no signed response is in the repository.
- **Consequence for our plan:** the Part 1 status in plan v2 (based on `company_site/` only) is wrong. Most SOW 1.x features exist here in some form. The real Part 1 questions are quality, acceptance, security, hosting (it is **not on Azure**) and ownership, not "build from scratch".

---

## 1. Who built it

Commit authors across all 90 branches (names/handles only; counts are commits reachable from any branch):

| Author (as recorded) | Commits | First | Last |
|---|---|---|---|
| `Devpt1904` | 2,735 | 2026-04-29 | **2026-11-13** |
| `Maanav Shah` | 70 | 2026-04-27 | 2026-06-01 |
| `Your GitHub Username` (unconfigured git identity) | 44 | 2026-05-01 | 2026-05-30 |
| `AuditMind Deploy` (deploy identity) | 16 | 2026-07-02 | 2026-07-04 |
| `Pratham Shrivastav` | 14 | 2026-07-06 | 2026-09-02 |
| `Claude` | 1 | 2026-10-19 | 2026-10-19 |

- **Most recent activity:** `Devpt1904`, 2026-11-13, on `claude/cr63-wl-drug-basis` and `claude/cr84-answer-dashboard`; also `claude/jovial-colden-8061b4` (11-10), `claude/quality-audit-cr40-f8c37a` (11-09), `claude/foi-classification` and `claude/candidate-9-1102` (11-08), `claude/ocr-483-ingest` (11-07). Branch names show the work is done largely with Claude Code sessions.
- **Branch structure (90):** `claude/*` 33, `fix/*` 15, `release/*` 5, `sow/*` 3, `feature/*` 3, `sync/*` 2, `maanav/*` 2, plus single branches (`remediation`, `reconcile-deploy3`, `r48`, …). **The release branch serving the client is `claude/candidate-9-1102`** (per the hand-off), not `main`. `main` is stale (2026-07-31).
- Who "Your GitHub Username" is cannot be told from the repo (44 commits in May 2026). Open question.

## 2. Architecture

| Layer | What it is | Evidence |
|---|---|---|
| Frontend | React + Vite (TypeScript), Radix UI, `next-themes` (light/dark), `i18next` with 6 locale files (de, en, es, fr, gu, hi). Main chat surface `frontend/src/components/ChatAreaEnhanced.tsx`; evidence drawer; analysis/insights views with charts; prompt dictionary; settings with a language switch. | [Read/Grep] `frontend/src/App.tsx`, `frontend/src/i18n/index.ts`, `frontend/src/components/PromptDictionary.tsx` |
| Backend | FastAPI, async SQLAlchemy (asyncpg), Alembic migrations. 27 route modules: admin, admin_users, alerts, answer, api, api_keys, auth, break_glass, dashboard, evidence, export, history, ingest, intelligence, ip_allowlist, knowledge, mock, oauth, ops, regulatory_tools, review_gates, search, session, session_memory, user_profile, webhooks, workbench_adapter. | [Read] `backend/app/api/routes/` |
| Size warning | `backend/app/api/routes/answer.py` is **13,007 lines**; `backend/app/retrieval/` is very large. 1,137 backend test files. Committed `.bak.PATCH.*` copies of route files exist. | [Read] |
| Database | Postgres. Served population lives in an `effective.*` schema (views over `public.*` minus reviewed exclusions); a read-only snapshot DB per client release. | [Doc claim] hand-off §1, `ACCEPTANCE_20261011_R37.md` |
| Vector search | Qdrant (collections incl. `pharma_chunks`, `paca_root_cause_gold_gemini`), about 33 GB of storage on the server. | [Read] config; [Doc claim] README |
| Embeddings | `nomic-embed-text-v1.5` via a local OpenAI-compatible server; Gemini `models/gemini-embedding-001` for at least one collection. | [Read] `backend/app/core/config.py` |
| Generation models | **Self-hosted:** vLLM serving Qwen2.5 (README: `Qwen2.5-32B-Instruct-AWQ` in production; config default `qwen2.5-7b-lora-pharma-v2`, a LoRA fine-tune). **External:** Gemini (`gemini-2.5-flash` default/fallback; `gemini-2.0-flash` in `llm_adapter.py`), OpenAI (`gpt-4o-mini` default in `llm_adapter.py`; a paid "Think" path funded per user from an OpenAI key on the server). Optional external `DEEP_REASONING` layer (UAT only, budget-capped). Vendor names are deliberately hidden from users. | [Read] `backend/app/llm_adapter.py`, `backend/app/core/config.py`; [Doc claim] hand-off §2 |
| Where models are called | `backend/app/llm_adapter.py` (`call_llm_json`, `GeminiAdapter`), `backend/app/ai/orchestrator.py` (`AIOrchestrator`), `backend/app/services/answer_engine.py`, web mode under `backend/app/services/web_mode/`. | [Read/Grep] |
| Reranker | sentence-transformers cross-encoder, local. | [Read] config |
| Web search | Tavily (`backend/app/services/web_search.py`, per-user rate limit, budget ledger in `services/web_mode/budget.py`). | [Read] |
| Retrieval design | **Deterministic first:** counts and populations come from SQL record filters ("deterministic layers compute populations and counts rather than letting the model produce them"); a gazetteer normalises company names. Vector ranking exists but **"ranked retrieval is not shipped"** (0.31 recall vs a 0.45 bar), so answers depend on the user naming what they want. Citations point to the source document, page and record. | [Doc claim] README, `CLIENT_TESTING_PACK_20261014.md` §7 |
| Deployment | **One E2E Networks GPU server**, not Azure, not docker-compose (README: "The Azure VM was decommissioned in the July-2026 migration"). uvicorn :8000, vLLM :8100, Qdrant :6333, nginx :80; client UAT reached through Caddy (basic auth) → a small proxy → a backend "lane" per release; blue/green "relane" cutovers with a smoke gate and a rehearsed rollback script. s6-overlay init. Release bundles built with `git archive` and copied by SSH. | [Doc claim] README, hand-off §1, §3 |
| Legacy deploy files | `docker-compose.prod.yml`, `backend/Dockerfile`, `frontend/Dockerfile` on `main`, marked "LEGACY (Azure-era)". | [Read] |
| CI | **None today.** No `.github/` on the reference branch. A GHCR push workflow existed 2026-05-01 to 2026-07-02 (removed in `54fec037`; inventory §8 R13). Testing is by manual differential runs against a **known baseline of failing tests** (README: 105; hand-off: 250 failing ids on the live build vs 260 on its baseline, "0 new"). | [Read/Doc claim] |
| Backups | Database backups on the serving node only; **no off-node backup**. | [Doc claim] testing pack §7 |

## 3. Capabilities against SOW 1.1–1.13

Row text as in plan v2 §1.1. "Present" means code exists for it; it does **not** mean it works well or was accepted. Quality is covered in §5.

| SOW | Requirement (short) | Status | Evidence | Note |
|---|---|---|---|---|
| 1.1 | AI platform on iCretegy 483 data; light/dark UI; PDF/Excel/Word/PPT input; browser/IP-based user management | **Present (mostly)** | `backend/app/ingestion/` (483, EIR, warning letter, guidance, PACA Excel, checklist extractors; `parsers/`), `routes/ingest.py`, `next-themes` in `App.tsx`, `routes/ip_allowlist.py` + `middleware/ip_allowlist.py`, `routes/admin_users.py` | PPT **input** not confirmed [Grep]. Data coverage dates not verified. |
| 1.2 | Fast mode and Think mode (summary, root cause, CAPA, classification) | **Present; quality not met** | `backend/app/ai/modes.py` (`AIMode.FAST/THINK`), `ai/root_cause_provenance.py`, `ai/capa_provenance.py`, `ai/classification_rubric.py` | Live client config: **Fast = rule-assembled, no model call**; Think = model interpretation over checked records, per-user paid budget. Observation summaries **OFF** (failed four blind runs). |
| 1.3 | Search: dataset-only with source/page and "No supporting data found"; web; both | **Present** | `ai/modes.py` (`SourceMode.DATASET/WEB/BOTH`), `ai/citation_policy.py`, `ai/evidence_policy.py`, "No supporting data found" in 91 files across the repository (36 in `backend/app` and `frontend/src`), `services/web_search.py` | Web/Both are budget-gated; every web turn runs a real search (hand-off §2). |
| 1.4 | Prompt dictionary; smart follow-ups; question history; top-20, investigator and company intelligence, cGMP 6-system | **Present** | `components/PromptDictionary.tsx`, `ai/related_questions.py`, `routes/history.py`, `routes/session_memory.py`, `ingestion/top20_extractor.py`, `routes/intelligence.py`, `system_checklist_extractor.py` | Chained follow-ups are a documented weakness (0/55 multi-turn fully correct). |
| 1.5 | Tables and pie/column charts; variable format; bad-response/comment feedback; reference guide | **Present** | charts in `AnalysisInsightsView.tsx`/`AnalysisPanel.tsx`; feedback `POST /feedback` and `GET /admin/feedback` in `routes/workbench_adapter.py`, `models/feedback.py` | Reference guide not checked. |
| 1.6 | New-483 alerts; metadata filters; home dashboard; pop-up when ready; accuracy graph; GDPR/HIPAA | **Partial** | `routes/alerts.py` (`POST /scan-new-483`), `models/alert.py`, `routes/dashboard.py`, toasts in `App.tsx` | Filters via the deterministic record filters. Accuracy graph: only a `dashboard.py` hit [Grep]. **GDPR/HIPAA: no compliance code found** (only keyword-ontology hits). |
| 1.7 | Skill assessment, guided tour, progressive disclosure, "explain this result" | **Partial** | onboarding skill level / job role / product type in `App.tsx` and `routes/user_profile.py`; `guided_tour_complete` flag; `POST /answer/explain` in `routes/answer.py` | Tour depth and progressive disclosure not verified [Grep]. |
| 1.8 | Session memory, user profile context, multi-turn reasoning | **Present; quality not met** | `routes/session_memory.py` (user-scoped by `claims.user_id`), profile context used in `routes/answer.py` | Multi-turn is the weakest measured area. |
| 1.9 | One-click PDF/Word report, scheduled reports, export PDF/Word/Excel/PPT/JSON, templates | **Partial** | `routes/export.py` (docx, json, pdf mentioned; Excel PACA workbook per owner preference) | **PPT export not found** in `export.py`. Scheduled reports not found. Hand-off: separate Excel/Word buttons and PDF render still to verify. |
| 1.10 | Confidence score, source attribution panel, "why did the AI say this" | **Present** | `ai/answer_format_controller.py`, `ai/answer_guardrails.py` (confidence), `EvidenceDrawer`, `ai/traceability.py`, `/answer/explain` | How confidence is computed was not reviewed; the QA report shows Low/Medium labels only. |
| 1.11 | Voice input, WCAG 2.1 AA, multi-language UI | **Partial** | browser `SpeechRecognition` in `ChatAreaEnhanced.tsx`; `aria-` attributes in 35 files; 6 locales + language switch | No accessibility test tooling (axe) found. **`useTranslation` is used in 0 components**, so most UI text is probably not translated [Grep; verify]. |
| 1.12 | Alert priority scoring, trend and competitor alerts | **Absent** | no matching code beyond one router keyword | SOW marks it feasibility-later. |
| 1.13 | Install on iCretegy's web within 90 days | **Not met as specified** | Running as **client UAT** on Praverse's E2E server, not installed on iCretegy's infrastructure | 90 days from 22 April 2026 passed 21 July 2026 (unchanged). |

## 4. Datasets (described, not copied)

- **Corpus:** published FDA Form 483s, Warning Letters, EIRs and FDA guidance (public FDA material), plus **iCretegy's own data**: PACA root-cause/CAPA records (Excel), a cGMP 6-system review of observations (iCretegy reviewer overlays `icretegy-cgmp-review-v1..v3`), a keyword workbook and system checklists. README names "iCretegy database" as the intended source label. [Read: extractor names; Doc claim: README]
- **Ingestion:** `backend/app/ingestion/` extractors per source type, OCR for 483 scans (branch `claude/ocr-483-ingest`), text-quality and metadata-quality checks, a dataset pipeline and an embedder. FDA web pages are referenced in a few modules (`warning_letter_extractor.py`, `ontology/build_regulatory_knowledge.py`).
- **Served population:** about 25.5k observations in the live release (`FINAL_ACCEPTANCE_20261013_a9d20eb9.md`), held in a read-only snapshot database per release. Country attribution is disclosed per record (read off the 483, facility record, inferred, or not established).
- **In the repository itself:** 430 data-type files (inventory §8 R11): SQL data patches (incl. a dated UAT data folder under `backend/ops/data/`), the iCretegy feedback reconciliation CSV, generated exports, analytics logs, SOW copies. Client data **is** in git history of this private repo. Not copied here.

## 5. Tests and measured quality

- **Tests:** 1,137 backend test files, **14,423 test functions** (`def test_` count); 13 frontend test files. Not run (see top). [Read: counts]
- **Known failing baseline:** README states 105 pre-existing failures; the 2026-11-02 hand-off reports **250 failing test ids on the live build** (260 on its baseline). The release gate is "no *new* failing ids", not "all pass". This is a weak gate: a 250-failure baseline hides regressions in those areas. [Doc claim]
- **What the tests cover (by name):** answer contract checks, citation/evidence policy, unsupported-claim checks, routing, gazetteer, population baselines (fixed expected counts for named queries), web-mode budget, auth, review gates, ops scripts. [Grep]
- **Answer quality (team's own blind grading, 209-item control bank):** 853cd000 (client's earlier build) 11 correct / 110 critical; candidate-5: 43 correct / **51 critical**; multi-turn (55) fully correct: **0**. Ranked causes: AI filtering, understanding, follow-up, routing, retrieval; then data issues. Accuracy round 1102b (not deployed): 48 critical, 2 multi-turn correct. Observation summaries failed all four blind runs against frozen criteria (≥20/30 delivered, 0 critical, ≥95% faithful). [Doc claim: hand-off §4, §5, §9]
- **My reading:** the engineering discipline (frozen criteria, blind grading, ledgers, rehearsed rollback) is strong; the product's answer accuracy is far from release quality by its own measure.

## 6. iCretegy QA reports and feedback

- **`Client_QA_Report.pdf` (52 pages) and `Client_QA_Sample.pdf` (6 pages)**, committed 2026-07-01, removed 2026-07-02. Both are **produced by Praverse for iCretegy to review**, not reports written by iCretegy. The report lists 200 answers (100 questions × Fast and Think): confidence labels only Low (66) or Medium (134), **66 answers with zero sources**, every row marked "OK". The sample's answers include model text saying it cannot confirm the asked facts while still listing sources. **They demonstrate an early (July) build's weakness, not acceptance.** No reply from iCretegy is attached.
- **`backend/docs/release/ICRETEGY_FEEDBACK_RECONCILIATION_20261013.csv`:** 223 review rows from iCretegy's cGMP-system review. Reconciled outcome: 176 incorporated and served, 7 activated later, 8 excluded as "not a finding", 32 held (text repair, source verification, owner confirmation), 1 date-only; 8 date corrections. This is **real client feedback on data classification**, and it was processed.
- **`backend/docs/release/CLIENT_TESTING_PACK_20261014.md`:** a test script and guidance for iCretegy testers (sign-in window, two modes, how to judge and report an answer, known limitations). Evidence that **client testing was set up**, not that it concluded.
- **Docs named "acceptance"** (`CLIENT_ACCEPTANCE_20261010.md`, `ACCEPTANCE_20261011_R37.md`, `BROWSER_ACCEPTANCE_*`, `FINAL_ACCEPTANCE_20261013_a9d20eb9.md`): the developer's own acceptance runs. The "final Think acceptance" of 13 October records **INCOMPLETE: 3 of 5 passed, one failed, one not run**.
- **Open defects (my summary):** wrong or dropped filters and follow-up scope (largest critical-error cause); one year count off from the graded answer (diagnosed later as stale gold); summaries unsafe to enable; ranked retrieval below its bar; browser layout and export buttons not verified for the live release; 127 conversation turns from an 11 October incident held outside History with unresolved ownership and audit-log gaps for that window; no off-node backup; a real server reboot never performed.
- **Formal UAT or written acceptance:** **none found.** No signed acceptance, no client e-mail of acceptance, no UAT exit report from iCretegy in the repository. It may exist outside the repository; that is a question for Pratham.

## 7. Security

- **Credentials:** already in `docs/CREDENTIAL_INVENTORY.md` §8 (R7 a Google API key in docs and an env template; R8 two Django `SECRET_KEY` literals in scripts; R9 test/UAT passwords and tokens; R13 the former GHCR workflow and its Actions secret names). The hand-off states the server holds an OpenAI key file and DB passwords outside git. Consolidated in the register (§9 of the inventory).
- **Auth model:** JWT (HS256) in an httpOnly cookie or bearer header; refresh and logout routes; roles `admin`, `user`, `doer`, `reviewer`, `vp`, `service_client`; **TOTP MFA only when enabled per user** and checked at login for reviewer/vp/admin (`routes/auth.py:89`); account lockout fields; API keys, OAuth client route, IP allow-list, break-glass and review-gate routes. In UAT, an outer Caddy basic-auth layer and a time window. [Read]
- **Concerns:** MFA secret is a plain `String(64)` column (`models/user.py`); I found no encryption of it [Grep; verify]. MFA is optional, not enforced for privileged roles (contrast REGX #113). One shared `JWT_SECRET`.
- **Tenant/user isolation:** users have a nullable `company_id` and an `is_platform_admin` flag; history and session memory are scoped by user id. Only 7 tenant/org references in `backend/app`. **It is a single-client application with per-user scoping, not a multi-tenant system** like REGX. Fine for one client; not a base for REGX tenancy.

## 8. What could be shared with REGX

| Component | Could share? | Constraints |
|---|---|---|
| AI adapter (`llm_adapter.py`, orchestrator, budget ledgers) | **As a separate service**, not as imported code | REGX needs tenant-aware calls, safe logging and an off switch (plan v2 §C); this adapter is per-user and FastAPI-native. Service-to-service auth required; REGX must enforce its own data access. |
| Retrieval (Qdrant, embeddings, gazetteer, deterministic filters) | **Yes, as a service** for 483 questions | Data governance: iCretegy data must not leak into other tenants. Independent deployment; REGX must work when it is down. |
| Auth | **No** | Different model (JWT vs REGX Django sessions + mandatory MFA). Sharing would weaken REGX's MFA gate. At most: REGX as identity provider later (separate decision). |
| FDA data (483 corpus, warning letters) | **Yes, the public part** | REGX keeps reference corpora platform-level; public FDA data is shareable, iCretegy's PACA/reviews are not without a written data-use decision. |
| Hosting | **Decision needed** | 483-AI-final is on E2E Networks GPU; REGX planning assumes Azure. Two hosting providers doubles the ops and security work. |

## 9. Relationship to company_site

- **Overlap:** both cover 483 observations, warning letters, top-20 recurring issues, investigator and company intelligence, filters and charts. 483-AI-final does all of these with AI search, citations, Fast/Think, history, exports and feedback, which company_site lacks.
- **What company_site still does that 483-AI-final does not (from REGX docs):** RATools (ANDA checklists, tables, calculators-adjacent tools), the AdminMaster console, the legacy 483 database's existing page set and its shared REGX login. Whether iCretegy still uses company_site's 483 pages once AuditMind is accepted is a product decision.
- **Duplication risk:** two 483 products for one client. company_site's `observation_summary.py` (the redesign we planned) duplicates AuditMind's summaries, which AuditMind itself switched off after failing blind runs. **Our summariser redesign should stay stopped** until this is decided.

## 10. Open questions for the call

1. Is AuditMind (483-AI-final) **the** Part 1 product? If yes, Part 1 work is improving its quality and getting acceptance, and company_site's 483 AI plans are dropped.
2. Who is `Devpt1904`, are they employed or contracted now, and who owns the server, the OpenAI key on it, and the E2E account?
3. Has iCretegy accepted anything in writing (UAT exit, sign-off, M2 trigger)? The repository shows none.
4. Hosting: E2E Networks (current) or Azure (our plan)? Data residency and the client's position on it.
5. Is the client told the measured quality (51 critical of 209)? What is the acceptance bar?
6. Should 483-AI-final get CI, a lower failing-test baseline, enforced MFA for privileged roles and off-node backups before any further client release?
7. Who is "Your GitHub Username" (44 commits, May 2026)?
8. Data governance: written permission for iCretegy data in this repo's history, and who has access.
