# AI integration runbook

How to connect REGX's AI gateway to a real model once the details arrive, how to benchmark it, and the data rule that applies until then.

**Status (2026-11-17):**
- The gateway exists and runs on the offline **stub** provider only.
- No real model has been called and no key exists in any environment.
- Hosting: the model runs on the E2E Networks server (reported by Maanav on 2026-11-17, pending Pratham's written confirmation). OpenAI is for development only.
- The E2E endpoint details and every API key have been requested from Pratham. None have arrived.

## 1. What exists

| Piece | Where |
|---|---|
| Provider interface (prompt in, text out, plus metadata) and the offline stub | `backend/ai_gateway/providers.py` |
| OpenAI-compatible HTTP adapter, used for both E2E and OpenAI | `backend/external_integrations/ai_http.py` (the only outbound network edge; registered into the gateway at start-up) |
| Settings, and the check for a missing value | `backend/ai_gateway/config.py`, `backend/regx/settings/base.py` |
| The call path: tenant check, off switch, configuration, breaker, retries, record, log | `backend/ai_gateway/service.py` (`generate()`) |
| Versioned prompts (id + version on every call) | `backend/ai_gateway/prompts.py` |
| Platform switch, health check, metrics | `GET/PUT /api/regx/v1/ai/switch/` (superuser), `POST /api/regx/v1/ai/health-check/` (Tenant Admin, needs `X-Tenant-Slug`), `GET /api/regx/v1/ai/metrics/?days=7` (superuser) |
| Benchmark | `python manage.py ai_benchmark` (section 4) |

**AI runs only when both of these are on:**
- the `REGX_AI_ENABLED` setting;
- the platform switch, set through `PUT /ai/switch/` by a superuser.

Both are off by default. Every call checks both, so turning the switch off stops AI immediately, with no redeploy.

When AI is off, misconfigured or down, callers get HTTP 200 with a `status` other than `ok` and a message to show: "AI is disabled.", "AI is not configured." or "AI unavailable. The rest of this page works as normal." The page itself never fails because of AI.

## 2. Values needed

Every value is empty or off by default.

| Variable | What it is | Who provides it | Needed for |
|---|---|---|---|
| `REGX_AI_ENABLED` | `true` to allow AI calls (the platform switch must also be on) | Us | All |
| `REGX_AI_PROVIDER` | `stub` (default), `e2e` or `openai` | Us | All |
| `REGX_AI_E2E_BASE_URL` | Base URL of E2E's OpenAI-compatible API, up to and including the version path (for example ending in `/v1`). Must be `https://`. | Pratham / E2E account owner | E2E |
| `REGX_AI_E2E_API_KEY` | The E2E API key or token, sent as `Authorization: Bearer …` | Pratham, over a secure channel | E2E |
| `REGX_AI_E2E_MODEL` | The model name E2E expects in the request body | Pratham / E2E | E2E |
| `REGX_AI_OPENAI_API_KEY` | A development-only OpenAI key, never one of the leaked legacy keys | Pratham | OpenAI (development) |
| `REGX_AI_OPENAI_MODEL` | The OpenAI model name for development | Us / Pratham | OpenAI (development) |

**Assumptions to confirm with E2E (not yet confirmed):**
- E2E's endpoint speaks the OpenAI chat-completions format: `POST {base}/chat/completions` with `model`, `messages` and `max_tokens`, answering with `choices[0].message.content` and `usage`. If it does not, the adapter needs a small change.
- The endpoint is reachable over `https://`. The adapter refuses plain `http://` to anything except the local machine. If E2E offers only plain HTTP on a private network, that is a security decision for the owner, not a configuration change.
- How the key is rotated, and which network the REGX server will call from (IP allow-listing).

## 3. Where the values go

- **Local `.env` only**, on the machine that runs the backend. It is already ignored by git.
- Compose passes them to the **backend container only**. Never set them for `company_site`, which must keep `OPENAI_API_KEY` unset as well.
- **Never** put a real value in a committed file, a PR, an issue, a chat, a log line or the review hand-off.
  - The hand-off builder fails if any `REGX_AI_*` value other than empty, `false` or `stub` appears in a file it collects.
- The gateway never logs or stores the key, the prompt or the response.
  - `AICallRecord` has no text column.
  - Log lines carry tenant, user id, provider, model, prompt id and version, latency, tokens and outcome only.
- In a deployed environment the values come from that environment's secret store. No secret store is chosen yet.

## 4. Turning it on and benchmarking (when the values arrive)

1. Put the values in the local `.env`. Set `REGX_AI_PROVIDER` to `e2e` (or `openai` for development) and `REGX_AI_ENABLED` to `true`.
2. Rebuild and restart the backend. The image bakes the source, and compose reads the environment at container start:

   ```bash
   docker compose up -d --build backend && docker compose restart nginx
   ```

3. As a superuser, turn the platform switch on: `PUT /api/regx/v1/ai/switch/` with `{"switch_enabled": true}`. `GET` on the same URL shows:
   - `effective_enabled`;
   - any `configuration_problem` code, such as `API_KEY_MISSING`.

4. Check connectivity: as a Tenant Admin, call `POST /api/regx/v1/ai/health-check/` with `X-Tenant-Slug`. Expect `"status": "ok"`.
5. Run the benchmark (Windows Git Bash needs `MSYS_NO_PATHCONV=1`):

   ```bash
   MSYS_NO_PATHCONV=1 docker compose exec backend python manage.py ai_benchmark --tenant demo --json-out /tmp/ai_benchmark.json
   ```

   - **It sends the fixed synthetic prompt set** (`backend/ai_gateway/benchmark_prompts.py`): short questions measured against **Fast** (p95 under 5 s), and long regulatory-style and long-context prompts measured against **Think** (p95 under 10 s).
   - **Load:** every prompt is sent once per worker at concurrency 1, 5 and 10. That is 80 calls with 5 prompts, plus 15 calls for the consistency check.
   - **It reports for each level and mode:** p50 and p95 end-to-end latency, error rate, input and output tokens, and MEETS or MISSES against the target.
   - **Consistency:** each prompt is sent 3 times in a row, and the command reports how many prompts gave identical answers (compared by hash; no answer text is printed or stored).
   - **Options:** `--concurrency 1,5,10`, `--repeats 3`, `--fast-target 5`, `--think-target 10`.
   - **Cost:** about 95 model calls per run.

6. **It refuses to send anything** when:
   - AI is not configured (it stops with "not configured", including with the default empty values or the offline stub);
   - AI is off;
   - the tenant does not exist.

7. **Report any MISSES** against Fast < 5 s / Think < 10 s before more development depends on the model (`docs/EXECUTION_PLAN_2026-11.md` section C).

**Proven so far without a real model:** the command runs end to end against the local fake server (`backend/ai_gateway/tests/fake_openai_server.py`).
- A fast fake meets both targets.
- A slow fake misses its target and the report says MISSES.
- An erroring fake is counted as errors.

See `ai_gateway/tests/test_benchmark_command.py`.

## 5. Data rule

**Synthetic data only until the data checks are done.** Until the "before synthetic data" questions in `docs/EXECUTION_PLAN_2026-11.md` section E.1 are answered in writing (where the model runs, retention, training on inputs, region, contract terms), **nothing but synthetic text may be sent to any real model**. Synthetic means written for the purpose, as in `benchmark_prompts.py` and `prompts.py`.

That rules out:
- client documents and tenant data;
- the development database, including the demo seed's IID-derived data;
- client checklists;
- text from the separate 483 codebase (`483-AI-final`);
- anything else that came from a client or a real inspection.

The benchmark prompt set is written to this rule. Keep it that way.

## 6. Not built yet (deliberately)

- Retrieval, chat UI, and any AI feature.
- Streaming.
- Caching.
- A prompt management UI.
- Cost dashboards.
- Feedback (thumbs up or down).
- The internal company_site → REGX AI endpoint and its service credential (`docs/EXECUTION_PLAN_2026-11.md` section C).

The provider interface is small (one `complete()` method) so that a provider from the separate 483 codebase can be registered later with `ai_gateway.providers.register_provider`.

## 7. Tests that guard this

| Test file | What it checks |
|---|---|
| `backend/ai_gateway/tests/test_service.py` | Off by default, both gates, missing configuration, tenant refusal, prompt id and version on every record, retries, circuit breaker, a provider bug giving "unavailable" rather than a crash, no text column |
| `backend/ai_gateway/tests/test_http_provider_end_to_end.py` | Against the local fake server: request format (path, headers, model, limit), parsing, timeouts, 429/500/401/400, malformed JSON, oversized and long answers, connection failure, and that no log line or record carries the prompt, the response or the key |
| `backend/external_integrations/tests/test_ai_http.py` | URL rules (https, or http to loopback only), registration, error bodies dropped |
| `backend/ai_gateway/tests/test_views.py` | Switch and metrics are superuser-only; the health check answers 200 with "AI unavailable" when the provider is down |
| `backend/ai_gateway/tests/test_prompts_and_guard.py` | Prompt fingerprints pinned per version; the session-wide guard (`backend/common/network_guard.py`, installed by `backend/conftest.py`) fails any test that connects to a non-local address |
| `backend/ai_gateway/tests/test_benchmark_command.py` | Refuses when not configured or off; end to end on the fake server, including a slow case that misses the target |
