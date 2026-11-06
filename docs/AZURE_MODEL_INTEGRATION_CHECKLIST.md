# Azure model integration checklist

**For:** the owner of the Azure deployment that will serve REGX's AI features.
**From:** REGX engineering. **Date:** 2026-11-06.
**Status:** information request. **No AI code will be written until this list is answered** (owner instruction, 2026-11-06).

Fill in the **Answer** column, or attach a document that answers the item. "Unknown" is an acceptable answer; a guess is not. Where a value differs between dev and prod, give both.

## 1. Endpoint and model

| # | Item | Why we need it | Answer |
|---|---|---|---|
| 1.1 | Service type: Azure OpenAI, Azure AI Foundry (model inference), or another Azure service | Decides the client library, request format and auth method | |
| 1.2 | Endpoint URL for **dev** and for **prod** (the base URL, not a key) | Configuration | |
| 1.3 | Deployment name(s) for each model | Azure routes by deployment name, not model name | |
| 1.4 | Model name **and exact version** behind each deployment (e.g. family, version date) | Results and benchmarks are only valid for one version | |
| 1.5 | Version policy: pinned, or auto-upgraded by Azure? Who is told before a version changes, and how much notice? | A silent upgrade can change regulatory text output | |
| 1.6 | Which deployment is for "Fast" and which for "Think" (or one deployment with different settings) | The two tiers have different latency targets (section 8) | |
| 1.7 | Embeddings model, if any (name, version, dimensions) | Only if search/retrieval is in scope | |

## 2. Request format

| # | Item | Answer |
|---|---|---|
| 2.1 | API and API version string (e.g. chat completions, responses API) | |
| 2.2 | Authentication: API key, or Microsoft Entra ID (managed identity / service principal)? Entra ID is preferred: no long-lived key | |
| 2.3 | Supported features we may rely on: system messages, structured (JSON schema) output, tool/function calls, streaming | |
| 2.4 | Any reasoning-effort or similar setting for the "Think" tier, and its allowed values | |
| 2.5 | A sample request and response (with no real data) from the deployment, so we can write the client against the real shape | |

## 3. Context window and output limits

| # | Item | Answer |
|---|---|---|
| 3.1 | Maximum input context (tokens) per deployment | |
| 3.2 | Maximum output tokens per request | |
| 3.3 | Maximum request body size, and any file/attachment limits | |
| 3.4 | Behaviour when a request is too long: error code, or silent truncation? | |

## 4. Rate and concurrency limits

| # | Item | Answer |
|---|---|---|
| 4.1 | Tokens-per-minute (TPM) and requests-per-minute (RPM) quota per deployment, dev and prod | |
| 4.2 | Deployment type: Standard (pay-as-you-go), Provisioned (PTU), Global or Data Zone | |
| 4.3 | Maximum concurrent requests, if limited separately | |
| 4.4 | What happens at the limit (HTTP 429 with `Retry-After`?), and whether the quota is shared with other applications | |
| 4.5 | Who can raise the quota, and how long it takes | |

## 5. Region and data residency

| # | Item | Answer |
|---|---|---|
| 5.1 | Azure region of each deployment | |
| 5.2 | Whether requests can be processed outside that region (Global or Data Zone deployment types route across regions) | |
| 5.3 | Any customer or regulatory requirement on where client documents may be processed | |

## 6. Credentials: separate dev and prod, secure delivery only

| # | Item | Answer |
|---|---|---|
| 6.1 | **Separate credentials for dev and prod.** A dev credential must not work against prod | |
| 6.2 | If keys: who generates them, and the rotation schedule (Azure keeps two keys so one can be rotated at a time) | |
| 6.3 | If Entra ID: tenant, client id, the role assigned (least privilege, e.g. a user role on the one resource), and where the identity lives | |
| 6.4 | **Delivery channel.** Credentials are delivered only through a secure channel agreed in advance (for example a password manager share or Azure Key Vault access). **Never by e-mail, chat, ticket, document, screenshot, or in the repository.** | |
| 6.5 | Who on the REGX side receives prod credentials, and who can revoke them | |
| 6.6 | Where REGX will hold them at runtime (environment variable on the server, or Key Vault reference). They never go in git, compose files, images or logs | |

Background: three OpenAI keys were committed to this repository's legacy `main` branch (`docs/CREDENTIAL_INVENTORY.md`). The rules above exist so that does not happen again.

## 7. Data handling: settings to verify

For each item, say what the setting is **and how it was verified** (portal screenshot, Microsoft contract term, support ticket).

| # | Item | Answer | How verified |
|---|---|---|---|
| 7.1 | **Storage:** are prompts or completions stored by the service (e.g. stored completions, stateful APIs, files, threads)? Which features would store data, and are they off? | | |
| 7.2 | **Logging:** what the service logs about requests (metadata only, or content?). Is diagnostic logging to our own Log Analytics on, and does it capture content? | | |
| 7.3 | **Retention:** how long any stored or logged data is kept, and how to delete it | | |
| 7.4 | **Inspection / abuse monitoring:** is human review of prompts for abuse monitoring active? Has a modified abuse-monitoring exemption been applied for or granted? Who at Microsoft could see content, and under what conditions? | | |
| 7.5 | **Training:** written confirmation that prompts and outputs are not used to train or improve models | | |
| 7.6 | Content filters: which filter configuration is applied, and whether it can block legitimate regulatory text (e.g. adverse-event language) | | |
| 7.7 | Network: public endpoint, or private endpoint / IP allow-list? Which REGX hosts must be allowed? | | |

Microsoft's current terms on 7.1–7.5 should be read from Microsoft's own documentation for the specific service and deployment type at the time of answering; they have changed before.

## 8. Monitoring

| # | Item | Answer |
|---|---|---|
| 8.1 | Which Azure metrics are available to us (latency, tokens, 429s, errors) and who can see them | |
| 8.2 | Alerts the deployment owner will set (quota exhaustion, error rate, spend) and who receives them | |
| 8.3 | Spend: budget and alert threshold per month, dev and prod | |
| 8.4 | Incident contact on the Azure side, and expected response time | |
| 8.5 | What REGX should log on its side (we propose: request id, deployment, model version, token counts, latency, status; **no prompt or document content**) | |

## 9. Benchmark plan

**Targets (owner, 2026-11-06):** Fast **< 5 s p95**, Think **< 10 s p95**, measured **end to end**: from REGX receiving the user's request to REGX returning the answer, including our own processing, not just the model call.

Plan (to run once sections 1–7 are answered and dev credentials are delivered; nothing below is built yet):

1. **Environment:** dev deployment only, same region and deployment type as prod. Synthetic or public data only (no client documents) until 7.1–7.5 are verified.
2. **Workload sets:**
   - **Short:** typical single-question prompts (~1–2k input tokens).
   - **Typical:** a realistic document section plus instructions (~8–16k input tokens).
   - **Long context:** inputs near 50% and near 90% of the context window (3.1), to see how latency grows.
   - Output lengths matching each feature (short answer vs. long draft).
3. **Concurrency:** 1, 5, 10 and 25 concurrent users (to be adjusted to the expected real load and the quota in 4.1), each level held for long enough to collect at least 200 requests.
4. **Measure:** p50, p95, p99 end-to-end latency; time to first token if streaming; model-side latency; tokens in/out; 429 and error rate; cost per request.
5. **Pass/fail:** Fast p95 < 5 s and Think p95 < 10 s at the agreed concurrency level, with error rate below an agreed threshold. Report long-context results separately: a long-context request may legitimately miss the target, and the product then needs a different behaviour (e.g. a progress indicator or background job), which is a product decision.
6. **Repeat** after any model version change (1.5) or quota change (4.5).
7. **Output:** a short report with the raw numbers, the exact model version, region, deployment type and quota at test time.

## 10. Sign-off

| Role | Name | Date |
|---|---|---|
| Azure deployment owner | | |
| REGX owner | | |
