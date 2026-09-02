# Capacity and limits

What RegX enforces, where the number comes from, and what happens at and beyond
it.

**A tested range is not a supported maximum.** The columns are kept separate on
purpose: "we ran this at 1200" and "this is the limit" are different claims, and
collapsing them is how a benchmark becomes a promise nobody meant to make.

## Enforced limits

| Area | Enforced limit | Source | Tested range | Behaviour at the limit | Behaviour above it |
|---|---|---|---|---|---|
| Document upload size | 50 MiB | `DOCUMENT_MAX_UPLOAD_BYTES` | up to the limit | accepted | `file_too_large`, 422, nothing stored |
| Connector response | 32 MiB default, 512 MiB ceiling | connector `max_response_bytes` | 1 B – 3 MB | accepted | `RESPONSE_TOO_LARGE`, refused **not truncated** |
| Connector import | the document upload limit | `operations.max_import_bytes()` | 3 MB | accepted | refused before ingest |
| Connector connect timeout | 1–15 s | connector config | 5 s default | — | config refused outside the range |
| Connector read timeout | 1–120 s | connector config | 30 s default | — | config refused outside the range |
| Connector retry attempts | 3 | `tasks.MAX_ATTEMPTS` | 3 | execution FAILED, `ATTEMPTS_EXHAUSTED` | never exceeded |
| Connector static headers | 8, from an allow-list | `config_schema` | — | accepted | config refused |
| Connector ports | 443, 8443 | `netpolicy.ALLOWED_PORTS` | — | — | `PORT_REJECTED` |
| API page size | 25 default, 100 max | DRF pagination | 100 | capped silently at 100 | request for more returns 100 |
| Attention queue scan | 500 per branch | `ATTENTION_SCAN_LIMIT` | 10 / 100 / 600 / 1200 sections | 500 rows, `truncated: true` | bounded in SQL; work does not grow |
| Activity feed | 50 | `ACTIVITY_LIMIT` | — | 50 rows | slice reaches SQL |
| Package entries | no hard cap | — | 10 / 50 / 120 (M13) | — | export refuses over `SUBMISSION_PACKAGE_MAX_ENTRIES` (2000) |
| Package export size | 5 GiB | `SUBMISSION_PACKAGE_MAX_TOTAL_BYTES` | small synthetic files | — | integrity check refuses, `too_large` |
| Dossier depth | as set in M9 | `submission_dossiers` | worst allowed depth | accepted | refused |
| Execution idempotency | unique per tenant | DB unique index | — | duplicate returns the existing execution (200) | second insert refused by the index |
| Database connect | 10 s | `DATABASES.OPTIONS.connect_timeout` | — | — | connection fails, readiness reports `unavailable` |
| Cache connect | 2 s | `REDIS_CONNECT_TIMEOUT_SECONDS` | — | — | `ConnectionError`, readiness reports `unavailable` |
| Cache read | 2 s | `REDIS_READ_TIMEOUT_SECONDS` | — | — | `TimeoutError`, readiness reports `unavailable` |

## Practical coverage, not guarantees

Where the "tested range" column says a number, that is what a test actually
built. It is evidence that the path behaves correctly at that size, not a
statement that the next order of magnitude is fine.

Specifically **not** claimed:

* That the attention queue is fast at a million sections. It is *bounded* there —
  the scan asks the database for 501 rows regardless — but the underlying query
  still has to find them, and no index work was done because no measurement
  called for it.
* That package export has been exercised at 500 files. Milestone 13 measured to
  120 entries with query-cost invariance; Milestone 15 did not extend that.
* That any of these are validated production limits. Nothing here is a validated
  system claim.

## Where a limit is deliberately absent

* **No cap on package entries at assembly time.** The export refuses beyond
  2000, but assembly does not, so a user is not blocked mid-build by a number
  they cannot see. The refusal happens where it can be explained.
* **No timeout on the total execution.** Individual connect and read timeouts are
  bounded and retries are capped, which bounds the work; a wall-clock ceiling on
  the whole operation would kill a large legitimate transfer partway through and
  leave exactly the ambiguity `TASK_RELIABILITY.md` describes.
* **No socket read timeout on the Celery broker**, which shares the cache's
  Redis URL. An idle worker holds a blocking pop open on purpose, so a read
  timeout there would tear down healthy connections as a matter of routine.
  Bounding the cache and bounding the broker are different problems.

## Why the cache bounds exist at all

Django's built-in Redis backend sets no socket timeout. Against a Redis that
accepts the connection and then stops answering, a cache call blocks until the
operating system gives up — so the `AllowAny` readiness probe *hung* rather than
returning 503. An orchestrator cannot act on a hang: it cannot tell "not ready"
from "still thinking", and because each probe holds a web worker for its whole
duration, a cache outage starved the web process through its own health checks.

The numbers are a ceiling on hanging, not a latency target. Sessions are
cache-backed, so a bound tight enough to trip under ordinary load would log
users out; normal Redis latency is sub-millisecond. redis-py is configured with
no retries, so one cache operation is one connect plus one command and the worst
case is the two bounds added together, not a multiple of them.

The option names are redis-py's, in lower case, because Django passes `OPTIONS`
straight into `ConnectionPool.from_url`. The upper-case `SOCKET_TIMEOUT`
spelling belongs to the third-party `django-redis` package, which is not
installed here — a key spelled that way would sit in the settings looking
correct and do nothing. `common/tests/test_dependency_timeouts.py` therefore
asserts on the connection pool the client actually builds, not on the settings
dictionary.
