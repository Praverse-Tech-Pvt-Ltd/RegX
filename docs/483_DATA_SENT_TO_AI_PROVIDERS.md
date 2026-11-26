# 483-AI-final: where data can go to Gemini, OpenAI, Tavily or Cohere

**Date:** 2026-11-27 (code read on 2026-11-26).

**Method:** static reading of the private repository `483-AI-final`, from a read-only mirror. The mirror was re-fetched on 2026-11-26; there were no new commits since 2026-11-14.

**Starting point:** `docs/483_CALL_PACK.md` §1 and PR #121. Every item was re-checked in the code.

**Not done:** nothing was run, no key was set, and no provider was called.

**Branches read:**
- `claude/cr84-answer-dashboard` (newest, 2026-11-14), shown as "newest" below;
- `claude/candidate-9-1102` (the release branch the hand-off names as serving UAT);
- `main` (last commit 2026-07-31).

**File paths** are under `backend/app/` unless shown otherwise, and line numbers are on the newest branch.

**Who checked what:** a helper agent did the line-by-line re-check; its full report is in the session hand-off. I then checked six of its claims against the code myself: the Tavily off switch, the Gemini fallback, the hourly OpenAI embedding job, the Data V2 router, and the deep-reasoning layer's missing on/off check. All six match.

## 1. The short answer

- **Code shows only what *can* be sent. What *was* sent depends on each server's settings and keys, which are not in git** (section 5).
- **Gemini:**
  - 8 paths: indexing, search queries, answers, an automatic fallback, "Explain simply", related questions and OCR.
  - **None has a guard** beyond whether a key is present.
  - The fallback fires on its own whenever the primary model fails and a Gemini key is set.
- **OpenAI:** more paths than the call pack listed. Three matter most:
  - **an hourly background job** that sends pending document chunks to OpenAI embeddings, on by default;
  - **a router that sends any unmatched question to OpenAI**, stopped only by the key and a budget ledger;
  - **a fallback to `gpt-4o`** when no model address is configured.
- **Tavily:**
  - **switched off in the code** on the release branches since 2026-10-10;
  - **live on `main`**, where it also fires automatically when search results score low.
- **Cohere:** **one live path**, re-ranking search results. It sends the question and the full text of every candidate passage whenever `COHERE_API_KEY` is set.
- **The call pack needs two corrections:**
  - it says every path is also on `main`; several OpenAI paths and every staging guard are not;
  - it missed the OpenAI paths in section 3.

## 2. Gemini

| # | Where (newest) | What data | When it runs | What enables it |
|---|---|---|---|---|
| G1 | `services/llm_adapter.py:216` (`_embed_batch_gemini`), from `ingestion/embedder.py` | Document chunks being indexed: 483 text, warning letters, guidance, and the PACA root-cause/CAPA collection (`core/config.py:27`) | When an index is built with `EMBEDDING_PROVIDER=gemini` | `EMBEDDING_PROVIDER` (default `openai_compatible`, `config.py:184`); key `GEMINI_API_KEY` or `EMBEDDING_API_KEY` (`llm_adapter.py:55-57`). Every production collection is sized 3,072, which matches Gemini embeddings (`db/vector_store.py:23`). **If the call fails, the code quietly uses dummy vectors** (`llm_adapter.py:192-195`) |
| G2 | `services/llm_adapter.py:117`, `:161` | The user's question | Any vector search with `EMBEDDING_PROVIDER=gemini` | Same switch. Whether live answers reach vector search was not traced |
| G3 | `services/answer_engine.py:490` → `:522` | System prompt, question and retrieved passages | `AI_MODEL_PROVIDER=gemini` | Default `mock` (`:381`). A value in `backend/.env` counts (`config.py:13`) |
| G4 | `services/answer_engine.py:499-505` | Same as G3 | **Automatically, whenever the primary model call fails and `GEMINI_API_KEY` is set** | Only the presence of the key. Inferred: a server set up from `.env.example` points the primary at a local address with nothing on it, so it fails and this fallback fires |
| G5 | `ai/model_client.py:128`, chosen at `:360` | Orchestrator, investigator, session-memory and knowledge prompts | `AI_MODEL_PROVIDER=gemini` | Default `openai_compatible` here (`config.py:214`), not `mock` |
| G6 | `api/routes/answer.py:13009-13011` | The full answer shown to the user, and the question | Every press of "Explain simply" (`POST /answer/explain`) | **Always Gemini**, no provider switch; model `gemini-2.5-flash` (`config.py:201`) |
| G7 | `services/related_questions.py:66`, chosen at `:50-52` | Question, the first 400 characters of the answer, and previews of 3 sources | After an answer | `AI_MODEL_PROVIDER=gemini` |
| G8 | `ingestion/fda483_extractor.py:404` → `:557` | Page images of 483 PDFs (public FDA documents) | At ingestion, only when local OCR finds too little text | `GEMINI_API_KEY` or `EMBEDDING_API_KEY` (`:571`) |

All eight are also on `main`.

## 3. OpenAI

| # | Where (newest) | On `main`? | What data | When it runs | What enables it |
|---|---|---|---|---|---|
| O1 | `services/deep_reasoning/provider.py:192` (sends `store: false`) | No | Instructions, question and checked records | Through callers O1a–O1e | `OPENAI_API_KEY` (`flags.py:26-28`); 10 USD budget (`flags.py:130`) |
| O1a | `services/deep_reasoning/layer.py:250` | No | Question and evidence rows | Called by narrative, premium-analysis and audit code | **The layer has no on/off check of its own**; only the budget ledger and the key stop it |
| O1b | `services/data_v2/router.py:344` | No | **The user's question** | **Every question no fixed pattern matched** (`answer.py:5238`) | Only the key and the budget ledger. The router does not check `DEEP_REASONING_ALL_QUERIES` |
| O1c, O1d | `services/presentation_seam.py:3065`; `ai/knowledge_fallback.py:443` | No | The finished answer; knowledge prompts | Answer wording; definition questions | Only when the staging programme `STAGE4_PROVIDER_TESTING` is on |
| O1e | `services/source_summary/summary.py:623` | No | Source records for "AI summary" | Think answers, or the "Generate AI summary" button | `SOURCE_SUMMARY_ENABLED` (on when unset), plus the staging programme |
| O2 | `services/knowledge/summarizer.py:1171` | No | 483 observation text | `POST /api/knowledge/summary` | `KNOWLEDGE_SUMMARY_ENABLED=1`, `KNOWLEDGE_MODEL=1`, `KNOWLEDGE_SUMMARY_API_KEY` |
| O2b | `services/knowledge/synthesis.py:975-981` | No | **CAPA/recurrence investigation dossiers**, question, firm label | Inspection-intelligence answers | `INVESTIGATION_SYNTHESIS_ENABLED=1`, a budget above 0, its own key |
| O3 | `ai/model_client.py:168` (calls `:264`, `:311`) | Yes | Question, passages and prompts | Provider `openai_compatible` / `ollama` / `vllm` | `AI_BASE_URL` or `AI_MODEL_BASE_URL`. **On the release branches the client also sends `OPENAI_API_KEY` as its key** (`:186-188`); on `main` it does not |
| O3b | `ai/model_client.py:190`, `:207-212` | Yes | **The full prompt, with no key** | Before every model call | Same address as O3. If that address is an outside provider, the prompt also goes to its `/tokenize` path (inferred) |
| O4 | `embedding/service.py:121-129`, run by `jobs/recovery_job.py:91-93` | Yes | Text of document chunks stuck as pending | **An hourly background job started with the app** (`main.py:104-106`) | **On by default** (`AUDITMIND_BACKGROUND_JOBS`, `recovery_job.py:263-264`). Always OpenAI `text-embedding-3-small` with `OPENAI_API_KEY`, **whatever `EMBEDDING_PROVIDER` says** |
| N1 | `services/llm_adapter.py:326-341` (`gpt-4o`) | Yes | Evidence package (up to 6,000 characters) and question | Regulatory synthesis, when no model address or model name is set | A real `OPENAI_API_KEY` (`:332`); `AI_BASE_URL` default empty (`config.py:217`) |
| N2 | `retrieval/llm_planner.py:276` | No | Question and minimal context | The "FAST" planner, including shadow mode | `FAST_LLM_PLANNER_ENABLED` / `_SHADOW_MODE`, both off by default (`planner_flags.py:93-103`) |
| N3 | `services/web_mode/provider.py:329`, `:336` | No | **The user's question; OpenAI then searches the web** | Web or Both mode | OpenAI key and a per-account web budget |
| N4 | `services/premium/llm.py:137` | No | Premium "Think" prompts | Premium answers | `PREMIUM_ANSWERS_THINK` or `INTEL_CHAT_ENGINE`, and only with the staging governor running (`:65-69`) |
| N5 | `backend/scripts/` (pilot, summary and synthesis scripts) and `ops/release/` | No | Whatever they are run on | Only when someone runs them by hand | A key given at run time |

## 4. Tavily and Cohere

| # | Where | What data | When | What enables it |
|---|---|---|---|---|
| Tavily, release branches | `services/web_search.py:19`, POST `:156` | The user's question, limited to fda.gov, federalregister.gov and regulations.gov | — | **Switched off in code:** `WEB_SEARCH_VERIFIED = False` (`:96`), checked before the key (`:132-135`), since commit `d1d4350c` (2026-10-10). The newest frontend also always sends `include_web: false` |
| Tavily, `main` | `services/answer_engine.py:663`, `:898` | The user's question | **Automatically when the best search score is below 0.6** (`:103`), and in web/both mode | `TAVILY_API_KEY` only (`config.py:59`); 10 calls a minute |
| Cohere | `services/reranker.py:136-160`, chosen at `:241-253` | **The question and the full text of every candidate passage** | Search with re-ranking (on by default), from the search route and the default dataset search | `COHERE_API_KEY` (default empty, `config.py:207`). Same on all three branches |

## 5. Guards, and what the code cannot tell

**Guards found:**
- the Tavily off switch;
- budget ledgers on deep reasoning, the planner and web mode;
- `mock` defaults on some answer paths;
- placeholder-key checks;
- `store: false` on some OpenAI calls (whether that changes OpenAI's retention is a matter of OpenAI's current terms, not code);
- a staging programme (`STAGE4_PROVIDER_TESTING`) that, when on, allows only `api.openai.com`, blocks embeddings and caps paid calls at 20.

The staging guards and the credential guard exist on the release branches only, and the credential guard covers only the staging test worker. **No guard was found for any Gemini path.**

**What the code cannot tell:**
- Which settings and keys each server had, which branch was deployed when, and therefore which paths actually ran. The Tavily answer alone differs completely between `main` and the release branches after 2026-10-10.
- Whether the production collections were really built with Gemini. Their size strongly suggests it; Google's usage records would prove it.
- Whether the Gemini fallback, the OpenAI router, the `/tokenize` call or the hourly job ever fired. That needs server logs, the budget ledgers and the providers' usage records.
- How long each provider keeps the data. That depends on the account tier and the provider's terms.

**To find out, check in the provider accounts and on the server** (as in `docs/483_CALL_PACK.md` §1.4):
- Google Cloud usage by API and by day;
- OpenAI usage by model and by day;
- the Cohere and Tavily dashboards;
- the server's `.env` (the names of the keys and switches above, never their values) and its deployed commit.
