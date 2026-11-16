# 483-AI-final: call pack (Pratham, Devpt1904, Maanav)

**Date:** 2026-11-16. **For:** the call on Pratham's direction of 2026-11-16 (to be saved unchanged at `docs/decisions/2026-11-16-pratham-direction-4.md`; **the e-mail text has not been provided yet**, so this pack follows Maanav's brief).
**Method:** static reading of a fresh read-only mirror of the private repository `483-AI-final` (fetched 2026-11-16: 90 branches, 2,901 commits, newest commit 2026-11-14 by `Devpt1904`). The application was **not run**, no key was set, nothing was sent to any model or cloud service. Line numbers are on branch `claude/cr84-answer-dashboard` (newest); every path listed below is also present on `main` and on `claude/candidate-9-1102` (the release branch the hand-off names as serving UAT).
**What this pack can and cannot say:** code shows what *can* be sent where, and under which settings. **What was actually sent in production depends on the server's environment and is not in git**; section 1.4 lists what must be checked in the cloud accounts to know. Statements from the repository's own docs are marked **[repo doc]**; they are the authors' claims, not verified.
Related: `docs/483_AI_FINAL_ASSESSMENT.md` (13 November), `docs/CREDENTIAL_INVENTORY.md` §9–§10.

---

## 0. The five things to settle on the call

1. **Which model calls left the server, to whom, with which data, since when** (§1). The code sends client content (483 text, iCretegy PACA root-cause/CAPA text) to **Google** (embeddings, vision OCR, fallback generation) and to **OpenAI** (Think, summaries, planner, web mode, "legacy LLM"). The repo's own notes say the GPU model was **not** deployed (§1.3).
2. **Hosting:** E2E Networks (where it runs) vs Azure (our plan v2) (§2). Most cost and quality figures are unknown on both sides.
3. **Quality:** by the team's own blind grading, 51 critical errors in 209 control questions on the live build; 196–233 critical in an 891-question full-corpus bank (§3).
4. **Acceptance:** demos, QA reports and feedback exist; **no written acceptance by iCretegy** was found (§4).
5. **Roles:** who owns Part 1, who maintains this repository, who operates the server and holds its keys (§5).

---

## 1. Data flows to external model services

### 1.1 Every code path that can send data to Google Gemini

| # | Path (file:line) | What it sends | When it runs | Switch / default | In git since |
|---|---|---|---|---|---|
| G1 | **Embeddings at ingestion**: `backend/app/services/llm_adapter.py:216` `_embed_batch_gemini` (via `ingestion/embedder.py:6` `embed_chunks`) | **Document chunks**: 483 observation text, warning letters, EIRs, FDA guidance, and **iCretegy PACA root-cause/CAPA records** (collection `paca_root_cause_gold_gemini`, `core/config.py:27`) | When an index is built with `EMBEDDING_PROVIDER=gemini` | `EMBEDDING_PROVIDER` (code default `openai_compatible` → local nomic server, `config.py:184-186`; `.env.example:78` the same). **But every production collection is named `*_gemini` and sized 3,072 (= `gemini-embedding-001`, `db/vector_store.py:23`)**, so the indexes in use were built with Gemini embeddings | 2026-05-04 (`245298be`) |
| G2 | **Embeddings at query time**: same function via `embed_text` / `embed_batch` (`llm_adapter.py:117`, `:161`) | **The user's question text** (and any text being searched) | Whenever vector search runs against a `*_gemini` collection with `EMBEDDING_PROVIDER=gemini` | Same switch. A 3,072-dim Gemini collection cannot be searched with a 768-dim nomic query, so **if vector search ran on those collections, queries went to Gemini**. The testing pack says ranked retrieval "is not shipped" and answers come from deterministic filters [repo doc], which may mean little or no query embedding in UAT: **unknown** | 2026-05-04 |
| G3 | **Answer generation, primary**: `backend/app/services/answer_engine.py:490` → `_call_gemini` (`:522`) | System prompt + **user question + retrieved chunks** (483/PACA/CAPA text) | `AI_MODEL_PROVIDER=gemini` | `answer_engine._get_provider()` reads the environment, **default `mock`** (`:381`); `config.py:214` default `openai_compatible`. The config comment (`config.py:233`) still says "Gemini remains the default … and fallback path": stale or not, it shows intent | 2026-05-15 (`ad85cfbe`) |
| G4 | **Answer generation, automatic fallback**: `answer_engine.py:502` | Same as G3 | **Whenever the `openai_compatible` / `ollama` / `vllm` model call fails AND `GEMINI_API_KEY` is set**; the answer is prefixed `[engine:backup]` | Implicit: presence of `GEMINI_API_KEY` in the environment | 2026-05-15; last changed 2026-06-30 |
| G5 | **Model client**: `backend/app/ai/model_client.py:128` `GeminiModelClient` (selected at `:360`) | The prompt it is given (orchestrator prompts with records) | `AI_MODEL_PROVIDER=gemini` | Same switch; key `AI_API_KEY` or `GEMINI_API_KEY` (`:131`) | 2026-05-20 (`d3932d0b`) |
| G6 | **"Explain simply"**: `backend/app/api/routes/answer.py:12990` `explain_answer` (call at `:13009-13011`) | **The full answer text** shown to the user and the original question | Every call of `POST /answer/explain` (a UI button) | **No provider switch**: always Gemini (`GEMINI_MODEL`, default `gemini-2.5-flash`, `config.py:201`) if `GEMINI_API_KEY` is set; 503 otherwise. Config comment: it 503'd until a 2026-07-10 fix | 2026-07-01 (`34e4ae36`) |
| G7 | **Related questions**: `backend/app/services/related_questions.py:66` `_gemini` (chosen at `:50-52`) | Question, first 400 characters of the answer, 80-character previews of the top 3 sources | After answers, when `AI_MODEL_PROVIDER=gemini` | Same switch; `openai_compatible` uses its own endpoint | 2026-05-15 |
| G8 | **Vision OCR of scanned 483s**: `backend/app/ingestion/fda483_extractor.py:404` → `_gemini_vision_ocr_pages` (`:557`), model `gemini-2.5-flash` (`:547`) | **Page images** of 483 PDFs (public FDA documents) | Last resort at ingestion, only when tesseract yields too little text ("a handful of files") | Key `GEMINI_API_KEY` or `EMBEDDING_API_KEY` (`:571`); no other switch | 2026-07-11 (`011fe441`) |

`answer.py:9460, 9478, 12038, 12679, 12924` pass `settings.GEMINI_API_KEY` into `generate_answer(...)`; the provider is still decided by G3/G4.
Safeguard present only on staging: `backend/app/staging/credential_guard.py:34, 46` refuses hosted-model keys (Gemini, OpenAI, Vertex, Cohere…) in the "deterministic worker". Nothing equivalent was found for the client lane.

### 1.2 Other external services that receive content (for completeness)

| # | Service | Path | What | Switch |
|---|---|---|---|---|
| O1 | **OpenAI (Think, "deep reasoning")** | `backend/app/services/deep_reasoning/flags.py:22, 129` (`https://api.openai.com/v1/responses`) | Question + checked records for the Think interpretation | `DEEP_REASONING_*`, Stage 4 governor and ledgers. **[repo doc] in use on the client lane** (`docs/release_client_20261101/CUTOVER_PREP.md` §5: "Think … `DEEP_REASONING_MODEL=gpt-5.6-terra`"; hand-off: per-user paid Think budget) |
| O2 | **OpenAI (observation summaries, knowledge)** | `backend/app/services/knowledge/summarizer.py:1171` | Observation text | `SOURCE_SUMMARY_ENABLED`, `KNOWLEDGE_SUMMARY_*`. **[repo doc] "on by default" on 853cd000**; turned **off** for the 2 November release |
| O3 | **OpenAI-compatible "legacy LLM"** | `answer_engine.py` / `model_client.py` with `AI_MODEL_PROVIDER=openai_compatible` and an external base URL | Question + chunks | **[repo doc] client lane `.env`: `openai_compatible`, gpt-4o-mini** (`CUTOVER_PREP.md` §5), i.e. OpenAI, not a local GPU |
| O4 | **OpenAI embeddings** | `backend/app/embedding/service.py:18` | Texts to embed | `EMBEDDING_PROVIDER=openai` |
| O5 | **Tavily (web search)** | `backend/app/services/web_search.py:19, 140` | **The user's question** as a search query | `TAVILY_API_KEY`; web/both modes, per-user budgets [repo doc] |
| O6 | **Cohere (reranker)** | `backend/app/services/reranker.py:33`, `retrieval/reranker.py:56-60` | Question + candidate chunks | Only if `COHERE_API_KEY` is set; otherwise local |

### 1.3 Which paths use the local GPU (vLLM) instead

- `AI_MODEL_PROVIDER` in `{openai_compatible, ollama, vllm}` with `AI_MODEL_BASE_URL` / `LORA_SERVE_URL` pointing at a local server (`config.py:214-240`; default model `qwen2.5-7b-lora-pharma-v2`, LoRA served on `localhost:8001`), and `EMBEDDING_PROVIDER=openai_compatible` with `EMBEDDING_BASE_URL=http://localhost:8002/v1` (nomic).
- **Whether that is local depends only on the base URL.** The same setting pointed at OpenAI gives gpt-4o-mini (O3).
- **Conflicting statements in the repository:** the README says production runs vLLM with `Qwen2.5-32B-Instruct-AWQ` on an E2E GPU box; the team's own memory index says **"32B NOT deployed (no GPU), all calls OpenAI API"** (`docs/handover_memory/MEMORY_INDEX_20261108.md`, entry for 2026-10-28). **Ask Devpt1904 which is true for each period.**
- Mock (`AI_MODEL_PROVIDER=mock`) makes no model call; the measurement lanes and some UAT periods ran it [repo doc].

### 1.4 What must be checked to know what was actually sent (not guessed here)

| Check | Where | What to record |
|---|---|---|
| Which Google Cloud project(s) the Gemini key(s) belong to; key names and creation dates | Google AI Studio → API keys; Cloud console → APIs & Services → Credentials | Project id, key name, created, last used (no key characters) |
| **Generative Language API usage by method** (`embedContent`/`batchEmbedContents` vs `generateContent`) **per day since 2026-05-04** | Cloud console → APIs & Services → Generative Language API → Metrics (filter by credential and method) | Daily request counts by method; first and last day of use |
| **Tier:** free (AI Studio) or paid (billing account attached) for each project and period | Cloud console → Billing → the project's billing account; AI Studio plan | Tier per period. Google's terms on whether prompts may be used to improve products differ between free and paid tiers [**verify against Google's current terms**] |
| Billing for the Generative Language API | Cloud console → Billing → Reports (filter by service) | Monthly cost per project |
| Environment of every server that ran the app (UAT lanes, owner lane, staging) | The servers' `.env` / process environment (read by the operator; never paste values) | Values of `AI_MODEL_PROVIDER`, `AI_MODEL_BASE_URL`, `EMBEDDING_PROVIDER`, `DEEP_REASONING_*`, `SOURCE_SUMMARY_ENABLED`; whether `GEMINI_API_KEY` was set (G4, G6) |
| OpenAI usage for the key(s) on the server | OpenAI platform → Usage (by project / key), and the server's Stage 4 ledgers [repo doc] | Requests and spend per model per day |
| Whether the public key (`iCretegy-AI483`, register C1) is in the same project as the private one (C2) | Same as row 1 | Yes/no |

**Data governance point:** G1 means iCretegy's PACA root-cause records were very likely embedded by Google (collections named `*_gemini`). Whether that is acceptable under the client agreement is Pratham's call; the usage evidence above must be preserved **before** any key is revoked (`docs/CREDENTIAL_INVENTORY.md` §10).

---

## 2. Infrastructure: E2E Networks vs Azure

Known = in a repository document; **[Estimate]** = reasoning, not measured; **Unknown** = nothing found.

| Aspect | E2E Networks (where 483-AI-final runs) | Azure (REGX plan v2) |
|---|---|---|
| **Model quality** | Measured by the team for *their* configuration: 43 correct / 51 critical of 209 (live build), but much of that build's model work is OpenAI calls (§1.2), not a model hosted on E2E. Self-hosted Qwen quality: not measured in any report found | **Unknown.** No Azure model has been benchmarked; the checklist (`docs/AZURE_MODEL_INTEGRATION_CHECKLIST.md`) is unanswered |
| **Data governance** | One server; Qdrant (~33 GB) and Postgres on the same box; **no off-node backup** [repo doc]; client data copies in many ops folders. External calls to Google/OpenAI/Tavily as in §1. E2E is an Indian provider with Indian data centres [**verify**]; the contract and DPA with E2E: **Unknown** | Region and data-handling settings (abuse monitoring, logging) are open items in the checklist §5, §7: **Unknown**. Keeps model calls inside one provider if Azure OpenAI is used [Estimate] |
| **Latency** | vLLM "3–4 min warm after restart" [repo doc]; per-answer latency: not found in the reports read | **Unknown** (benchmark plan in checklist §9, not run) |
| **Operating cost** | Known: per-feature spend ceilings in the ledgers (e.g. Think $1.30 client allocation; web mode up to $57) [repo doc]. Server and GPU monthly cost: **Unknown** (no invoice in the repo) | **Unknown.** Plan v2 §E gives ranges only [Estimate] |
| **Deployment complexity** | Hand-run: SSH, `git archive` bundles, blue/green "relane" scripts, s6 init, manual ledgers; **no CI**; a reboot never tested [repo doc] | Not built. Plan v2: IaC + automated deploys [Estimate, not done] |
| **Integration with REGX** | Separate FastAPI app, JWT auth, single-client; sharing would be service-to-service only (assessment §8) | REGX's own platform target; the 483 product would still need its own deployment or a port [Estimate] |
| **Biggest unknowns** | Which model actually served UAT when (§1.3); server cost; backup | Everything in the Azure checklist; who owns the subscription |

**Reading:** the comparison cannot be decided on facts today. The quality numbers belong to the application logic plus OpenAI calls, not to E2E as a host; the cost and latency figures needed are missing on both sides.

---

## 3. Evaluation: the 51 critical errors

**Source:** `HANDOFF_20261102.md` §4, `docs/release_client_20261101/ACCURACY_ROUND_20261102B.md` [repo doc]. Control bank of 209 items, blind-graded by two graders against frozen expected answers.

| Build | Correct | Critical | Multi-turn (55) fully correct |
|---|---|---|---|
| 853cd000 (client before 2 Nov) | 11 | 110 | 0 |
| candidate-5 (basis of the 2 Nov live release) | 43 | **51** | 0 |
| accuracy round 1102b (**not deployed**) | 45 | 48 | 2 |

**The 51 by primary cause** (graders' attribution): AI filtering 11 · AI understanding 8 · AI follow-up 8 · AI routing 8 · AI retrieval 5 · data metadata 3 · data entity linkage 3 · data missing record 2 · data duplicate 2 · OCR 1. **Reading:** 40 of 51 are in question interpretation (filters dropped or wrong, follow-up scope, routing to the wrong handler); 11 are data quality.
**After round 1102b (48):** routing 9 · filtering 7 · retrieval 7 · understanding 6 · (remainder not listed in the excerpt read). One new critical versus 853cd000 (G07-063), so the round's own "no new critical" bar is **not met**.
**A larger bank exists:** 891 questions over the full corpus: Fast 4.1% answerable-correct, 233 critical (2026-10-27 baseline), then 4.78% / 196 critical after recovery fixes [repo doc: `docs/handover_memory/MEMORY_INDEX_20261108.md`]. The control bank (209) is the one reported to the client.
**Remediation in the repo:** seven shared fixes in round 1102b (date scope, issue-date vs inspection-start, city and FEI handling, topic vs registrant, follow-up carry-over, "how many of those cite…", place guards) with 73 focused tests, **not deployed**; diagnosed-but-unfixed items listed there (follow-up scope, partial firm names, FOI routing). Observation summaries failed four blind runs and stay off. Later branches (to 2026-11-14) carry further work (system assignment, warning-letter basis, answer dashboard); **no later graded bank result was found**.

---

## 4. iCretegy evidence

| Evidence | What it is | Who made it |
|---|---|---|
| `Client_QA_Report.pdf` (52 p), `Client_QA_Sample.pdf` (6 p), July 2026 | 200 Q&A samples (Fast/Think) prepared **for** the client's review; 66 answers with no sources | Praverse (vendor) |
| `backend/docs/release/ICRETEGY_FEEDBACK_RECONCILIATION_20261013.csv` | **Real client feedback**: 223 rows of iCretegy's cGMP-system review, reconciled (176 incorporated, 7 later, 8 excluded, 32 held) | iCretegy feedback, reconciled by the developer |
| `backend/docs/release/CLIENT_TESTING_PACK_20261014.md` | Test script and guidance for iCretegy testers | Vendor |
| "Client acceptance" documents (10–13 Oct) | The developer's own acceptance runs against the live lane; the final Think run was **INCOMPLETE (3 of 5)** | Vendor |
| `docs/release_client_20261101/*`: live release notes (2 Nov), QA report (5 Nov, 23 questions, several issues incl. follow-up scope and false zero), "Passed Questions" (5 and 6 Nov), "Test Evidence and Status" (4 Nov), web test screenshots (6 Nov) | Status and evidence packs for the client | Vendor (committed by `Devpt1904`, 4–8 Nov) |
| UAT data folder (`backend/ops/data/…uat_20261020/`) | Data prepared for a client UAT session | Vendor |

**No written acceptance, sign-off, UAT exit report or e-mail of acceptance from iCretegy was found** in any branch. It may exist outside git: ask.

---

## 5. Questions for Devpt1904 (short and specific)

1. Which environment values did the client lane use for `AI_MODEL_PROVIDER`, `AI_MODEL_BASE_URL`, `EMBEDDING_PROVIDER`, `DEEP_REASONING_MODEL`, `SOURCE_SUMMARY_ENABLED`, per release since July?
2. Was `GEMINI_API_KEY` set on the client lane, and did the `[engine:backup]` Gemini fallback ever fire?
3. Which Google project and tier built the `*_gemini` collections, and on which dates? Were PACA records embedded there?
4. Was a self-hosted model (Qwen 7B LoRA or 32B AWQ) ever serving the client, and when? The README and the 28 Oct note disagree.
5. Does query-time vector search run in UAT, or only deterministic filters?
6. Who owns the E2E account, the server's root access, and the OpenAI key file on it?
7. What does the server cost per month, and where are backups kept?
8. Is there any written iCretegy acceptance (UAT exit, sign-off, e-mail)?
9. What is the current live build, and is the 1102b accuracy round deployed?
10. Is the 891-question bank re-run planned, and what bar would you call release quality?
11. Which of your branches are meant to merge, and which are experiments?
12. Are you continuing on Part 1, and on what terms (role, hours, access)?

---

## 6. Not done here

No code was run; no key was used; no cloud console was opened. Section 1.4 and the credential evidence list (`docs/CREDENTIAL_INVENTORY.md` §10) are for the account owners.
