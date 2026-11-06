# Legacy FDA-483 summariser: redesign proposal

**For:** Pratham (owner). **Status:** proposal only; nothing in this document is built. **Date:** 2026-11-06.
**Scope:** the observation summariser in the legacy company site (`company_site/`), not REGX.
**Evidence:** `PROJECT_OVERVIEW.md` §11 #10e (call sites, from PR #104) and the measurements in §6.

---

## 1. What happens today

- The summariser lives in `company_site/AIDatabase/observation_summary.py`. It writes one summary per *observation block* (consecutive spreadsheet rows with the same observation and company), using OpenAI `gpt-4.1-mini`, with up to 3 attempts per block.
- It is **called during page loads**. Fifteen routes, starting with `GET /`, load the FDA-483 spreadsheet through `get_cached_df()`. On a cold cache, or after the spreadsheet changes, the page runs `process_observation_summary` (`company_site/AIDatabase/views.py:559`) **before it can answer**.
- Every block without a summary is sent to the model, one after another, inside that request.
- **Only one thing stops this today:** `OPENAI_API_KEY` is unset. With no key, each block is skipped. With a key, generation starts immediately on the next page load.
- **Size today** (measured on the local copy of the client spreadsheet; see §6): 8,362 blocks, of which 2,700 already have a summary. **5,662 would be generated on one cold page load.**

## 2. Why this is unsafe

It is unsafe for **any** model, OpenAI or our own.

**Cost (OpenAI or any paid API):**
- One cold `GET /` starts 5,662 generations, up to 16,986 calls with retries.
- Anyone can trigger it, including an anonymous visitor or a crawler: `GET /`, `/aidatabase/form483/` and `/aidatabase/auditiq/` need no login. (The compose health check uses `/termsofuse/`, which doesn't trigger it.)
- There is no cap, no budget and no switch. The earlier incident (71 paid calls from one `GET /`) was this path with a small backlog; the backlog is now about 80 times larger.

**Page time and stability:**
- **The request can't finish.** Gunicorn kills a request after 120 seconds. At even 1 second per summary, 5,662 summaries take over 1.5 hours. The page times out and the visitor sees an error.
- **The work repeats.** Progress survives in a checkpoint file, so the next visitor's request picks up and runs again. Every page load becomes slow until the backlog is gone.
- **Calls are duplicated.** Three gunicorn workers can run the same backlog at the same time, so the same block can be summarised and paid for more than once.

**Self-hosted model (our Azure deployment):**
- No per-call bill, but the same request-time problem: GPU time is consumed by page loads, other users' pages stall, and timeouts still happen.
- A self-hosted model is also slower per request than a hosted API under concurrent load, which makes the page-time problem worse, not better.

**Data and audit:**
- Summaries are written back into the source spreadsheet as a side effect of viewing a page.
- No record exists of what was generated, when, by which model, or what failed.

## 3. Proposed design

**Principle:** pages only **read** stored summaries and never call a model. Generation is a separate, controlled background job.

1. **Storage.** A summary table keyed by a stable block key (company + observation + a hash of the detail text). Each row holds the summary, model name and version, prompt version, created time, status (`done` / `failed`) and failure reason. The spreadsheet is no longer modified.
2. **Pages read only.** Remove the summariser call from the page path (`_refresh_excel_cache_from_source_info`). Pages join stored summaries onto the data. A block without a summary shows "summary not yet available"; nothing is generated.
3. **Background batch job.** A management command, also runnable as a Celery task, that:
   - finds blocks with no stored summary;
   - generates them;
   - stores each result as soon as it's done.
4. **New 483s on import.** When a new 483 spreadsheet is uploaded (admin or importer), only the new blocks are queued for the job. This replaces today's admin/signal path, which re-runs everything.
5. **Kill switch.** A setting, `SUMMARY_GENERATION_ENABLED`, off by default. When it's off the job refuses to start and says why. It's checked before every block, so turning it off stops a running job at the next block.
6. **Per-run limit.**
   - `--max-blocks` (default, say, 200) and an optional `--max-minutes`, so one run can never spend without bound.
   - Concurrency is a setting (default 1).
7. **Progress and failures recorded.**
   - A run record holds: start and end time, model, counts (generated, skipped, failed), the limit hit, and who started it.
   - Per-block failures go into the summary table with a reason.
   - Failed blocks are retried on the next run, up to a maximum attempt count.
   - The audit trail never holds the observation text, only block keys and counts.
8. **Idempotent re-runs.** A run skips every block that already has a `done` summary. Stopping and restarting is always safe.
9. **Dry run.** `--dry-run` reports how many blocks would be sent and the estimated input size, without calling anything.

## 4. Model adapter

- One small interface, `summarise(text, limits) -> summary`, with two implementations:
  - **OpenAI** (today's SDK call, moved here);
  - **Azure-hosted model** (our deployment). I'm assuming an HTTPS chat-completion style endpoint; to confirm with the deployment owner.
- **Selection:**
  - One setting picks the implementation: `SUMMARY_MODEL_BACKEND = openai | azure | disabled`, default `disabled`.
  - Endpoint, deployment name and key come from environment variables, never from code.
  - A third, test-only implementation returns fixed text, so the job is testable with no network.
- **No client data used for training (SOW 4.2 b):**
  - **OpenAI:** use an API organisation or project with data sharing for training turned off. Record the setting and who confirmed it.
  - **Azure:** confirm the deployment does not log or retain prompts for training.
  - Write the confirmation into the run record's "model" field, so every stored summary can be traced to a confirmed configuration.
- **Same prompt for both.** The prompt and length rules move into one versioned place. A prompt change bumps the version, so old summaries can be found and regenerated deliberately, not silently.

## 5. Estimates

**These are estimates for one experienced developer, before review.**

| Piece | Size |
|---|---|
| Summary and run tables, read-only page change (remove the call, join stored summaries, "not yet available") | S–M (1–2 days) |
| Batch job: command and Celery task, kill switch, limits, progress, failures, idempotency, dry run | M (2–3 days) |
| Model adapter: OpenAI + Azure + test fake, one setting | S–M (1–2 days) |
| Import hook for new 483s | S (0.5–1 day) |
| Tests: no network, adapter fake, limits, kill switch, idempotency, page never calls a model | M (2 days) |
| **Total** | **about 1.5–2 weeks** |

**One-time backfill time.** Replace **S** with the measured seconds per summary for the chosen model.

> backfill hours = 5,662 blocks × S seconds ÷ concurrency ÷ 3,600

| Seconds per summary (S) | Concurrency 1 | Concurrency 4 |
|---|---|---|
| 1 s | about 1.6 h | about 0.4 h |
| **3 s (assumed placeholder)** | **about 4.7 h** | **about 1.2 h** |
| 6 s | about 9.4 h | about 2.4 h |
| 10 s | about 15.7 h | about 3.9 h |

- With a per-run limit of 200 blocks, the backfill takes about 29 runs (5,662 ÷ 200), which can be scheduled overnight.
- **Volume for cost planning (measured; see §6):**
  - **Input:** about 1.21 million words of observation text, plus a system prompt of roughly 300 words per call.
  - **Output:** about 0.36 million words at the 30 % target.
  - Convert to tokens and price with the chosen model's current rates. I have not quoted prices because they change; check the provider's page on the day.

## 6. Measurements behind the numbers

- **Source:** the client spreadsheet the code falls back to (`Final_File_FDA_Observations_15_12_2025.xlsx`). It is **git-ignored client data, not in the repository**; the measurement used the local copy, read-only, with the summariser's own block rules, in a container with no network.
- **Counts:** 13,576 rows → 8,362 blocks. 2,700 are already summarised, 5,662 need a summary, and 0 have no details.
- **Input per block:**
  - mean 1,381 characters, median 933, maximum 14,689 (the code cuts at 15,000);
  - mean 213 words, median 142, total 1,208,535 words.
- **Target output:** 362,560 words (30 % of input).
- The live spreadsheet on the server may differ. Re-run the measurement there before planning the backfill.

## 7. What must be true before any key or endpoint is set in company_site

1. The redesign above is merged and deployed: **no page calls a model**. A test proves it, extending the smoke test in PR #104 to assert the page path never reaches the adapter.
2. `SUMMARY_MODEL_BACKEND` defaults to `disabled` and `SUMMARY_GENERATION_ENABLED` defaults to off. Both are checked in tests.
3. The per-run limit and concurrency are set and reviewed. A dry run on the live spreadsheet reports the expected block count.
4. **No-training confirmation** (SOW 4.2 b) is recorded for the chosen provider, with who confirmed it and when.
5. A **budget owner and a spending limit** exist on the provider side (OpenAI usage limit, or GPU quota for Azure), separate from our own per-run limit.
6. The key or endpoint is stored only in the company_site environment, never in the repository, and never in the REGX backend container.
7. The company_site smoke tests (`company_site/run_tests.sh`) still run in CI **without** the key. CI must never receive it.
8. The first live run is a small, supervised one (for example `--max-blocks 20`), and someone reads the results before the backfill starts.
9. The legacy `AIDatabase/filters.py` key on the `main` branch stays the owner's call. This proposal doesn't depend on it.
10. **No route reachable without login can trigger generation.** Today `GET /`, `/aidatabase/form483/` and `/aidatabase/auditiq/` need no login and all run the summariser. After the redesign no page generates at all; until then, and as a standing rule afterwards, a test must prove that an anonymous request cannot start or queue a generation.
11. **Client data files reach a server only as mounted data or uploads, never inside a Docker image.** The local company_site image today contains 12 git-ignored client spreadsheets and a database backup (`PROJECT_OVERVIEW.md` §11 #10g); the summariser's fallback spreadsheet is one of them. Before any key is set, the image must be built without them and the spreadsheets supplied through a mounted volume or the admin upload, so a pushed image never carries client data.

## 8. Not covered

- **Summary quality and regulatory wording.** The prompt today asks for "concise FDA/regulatory language"; any user-facing wording must pass the regulatory-claim rules before REGX uses these summaries.
- **Moving the 483 data and summaries into REGX** (SOW Part 1 and §2.6). This proposal only makes the legacy path safe.
