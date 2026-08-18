# Operational Logging

**Scope: structured operational telemetry.** Did a request arrive, did it
finish, how long did it take, did something raise.

Verified against `regx-main` `96d9485c7c73bbf31361aac275b7e4c1c20b67d6`.

---

## 1. This is not the audit trail

The two are separate systems and must stay separate.

| | Operational logs | Regulated audit trail |
|---|---|---|
| Where | stdout, JSON lines | `audit.models.AuditEvent`, database rows |
| Written by | `common.structured_logging` and library loggers | application code, deliberately |
| Purpose | diagnosing a running system | regulated evidence |
| Durability | whatever the container runtime keeps | immutable rows, backed up |
| Authoritative for | nothing regulated | user actions, approvals, checklist decisions, signatures |

**Operational logs are never the authoritative record** for regulated user
actions, approvals, checklist decisions, signatures, audit history or regulatory
evidence. The audit trail does not read from logging and does not depend on a
log being written; losing every log line would not damage it.

**Audit payloads are deliberately not duplicated into logs.** Copying them out
of the database into stdout would create a second, weaker, non-immutable copy of
regulated content — and the copy would inevitably drift.

---

## 2. Before this change

| Area | State |
|---|---|
| `LOGGING` in settings | none, except `LOGGING = {}` in `test.py` to silence tests |
| Effective configuration | Django's built-in default, in development and production alike |
| First-party log calls | 8, across `documents/scanner.py` and `documents/tasks.py` |
| Stray `print()` in application code | none |
| Correlation identifier | none anywhere — not in Django, not in nginx |
| Format | unstructured text |
| Never-log policy | not stated anywhere |

The 8 existing call sites were checked individually. All log UUIDs, statuses and
exception strings; none logs a credential or a governed payload. Nothing had to
be removed.

---

## 3. Format

One JSON object per line on stdout. `json` from the standard library; **no
logging package was added**.

```json
{"timestamp":"2026-08-18T09:14:22.581Z","level":"INFO","logger":"regx.request","service":"backend","event":"request completed","request_id":"7c1f...","method":"GET","path":"/api/regx/v1/formulations/products/","status_code":200,"duration_ms":18.4}
```

| Field | Always | Meaning |
|---|:-:|---|
| `timestamp` | yes | UTC, millisecond precision |
| `level` | yes | `DEBUG` … `ERROR` |
| `logger` | yes | logger name, e.g. `regx.request`, `celery.worker.strategy` |
| `service` | yes | `backend` or `celery` — same image, so `REGX_SERVICE_NAME` distinguishes them |
| `event` | yes | the message |
| `request_id` | in a request | see §4 |
| `method`, `path`, `status_code`, `duration_ms` | request events | see §5 |
| `task_name`, `task_id`, `outcome` | task events | |
| `exception_class`, `stack` | error events | see §6 |

**Absent fields are omitted, not emitted as null.** A schema-shaped blob of
nulls on every line is noise, not structure.

### The formatter is an allow-list, and that is load-bearing

Only the field names above are ever emitted. `record.__dict__` is never
serialised and arbitrary `extra` keys are never passed through. This is not
tidiness:

> `celery.worker.strategy` logs `Task <name>[<id>] received` and attaches
> `extra={'data': {..., 'args': ..., 'kwargs': ...}}`. Celery's own text
> formatter never renders that dict, so task arguments stay out of the log. **A
> JSON formatter that dumped extras would silently start logging task
> arguments** — which in this system can be document identifiers and governed
> payloads.

A test asserts this directly (`test_task_args_attached_as_extra_are_not_emitted`).

---

## 4. Request correlation

**Header: `X-Request-ID`**, accepted inbound and always returned outbound. No
identifier existed anywhere before, so nothing had to be matched.

- **Inbound values are accepted only if they parse as a UUID.** Anything else is
  discarded and replaced. That header is attacker controlled: without the check
  a caller could embed newlines and forge whole log lines, or push a megabyte of
  text into every record for the request. Requiring a UUID makes the value
  structurally incapable of both.
- Otherwise a server-side UUID4 is generated.
- Held in a **`ContextVar`** — correct under threads *and* under async, with an
  independent copy per context. Not a module global, and not a thread-local.
- Stamped onto every `LogRecord` **at creation**, via a chained
  `logging.setLogRecordFactory`, not looked up at format time. A formatter runs
  whenever its handler gets round to it; for a queued, buffered or
  test-captured handler that is after the request ended and the context was
  reset, which would silently lose correlation on precisely the records that
  matter most. Creation-time binding also correlates records this project does
  not emit — `django.security`, Celery's own loggers.
- **One case needs more than the factory.** Django logs every 4xx/5xx response
  through `django.request` from `BaseHandler.get_response`, which runs *after*
  the middleware chain has returned — so the ContextVar is already reset and the
  factory finds nothing to stamp. Those records arrive carrying
  `extra={"request": <HttpRequest>}`, and the middleware puts `request_id` on
  the request object, so a small handler filter recovers it from there. It reads
  that one attribute and nothing else; the allow-list still keeps the request's
  headers, cookies and body out. Verified live: a 403 now carries the same
  `request_id` on both the `regx.request` and the `django.request` line.

### Why `request_id` and not `correlation_id`

`correlation_id` is **already taken** in this codebase as a *domain* field:
`documents.DocumentJob` and the FDA import models each carry one to tie a
processing chain together. Reusing that name for an HTTP concern would collide
with an existing regulated concept in exactly the place someone would go looking.

---

## 5. Request logging

One completion event per request: `request_id`, `method`, `path`,
`status_code`, `duration_ms`.

Level follows the outcome: `INFO` for 2xx/3xx, `WARNING` for 4xx, `ERROR` for
5xx.

**Health probes are the exception.** Successful requests to
`/api/regx/v1/health/` and `/api/regx/v1/readiness/` drop to `DEBUG`. Docker
polls these every few seconds for several services; at `INFO` they would be most
of the volume and would bury real traffic. **A failing probe is not quietened** —
a health endpoint returning 500 is exactly what a reader needs to see.

**`request.path` is recorded, never `request.get_full_path()`.** No query string
ever reaches a log. Today's query parameters happen to be benign (`status`,
`dataset_type`, `export_format`…), but logging the path alone means a sensitive
parameter added years from now cannot leak through this code.

---

## 6. Exceptions

An unhandled exception is logged with `request_id`, `exception_class`, the
message and the stack trace — then **re-raised untouched**, so Django's own
handling is unchanged. Logging observes; it never swallows.

Not included: request body, response body, headers, cookies, or a model dump. A
standard Python traceback contains frames and source lines, not variable values,
so a credential sitting in a local does not travel with it.

`django.request` logs 4xx/5xx and attaches the `HttpRequest` object to the
record. The formatter's allow-list is what keeps that object — and its headers,
cookies and body — out of the output.

---

## 7. Never-log policy

Never written to an operational log:

passwords · API keys · bearer, access and refresh tokens · session cookies ·
CSRF tokens · MFA secrets · MFA recovery codes · encryption keys · SMTP
credentials · database passwords · the `Authorization` header · the `Cookie` and
`Set-Cookie` headers · request bodies · response bodies · uploaded file contents
· document binary or base64 content · complete regulatory answers or payloads ·
raw checklist response values · full exception locals · connection URLs
containing credentials · raw query strings

**The control is that these values are never handed to a logger.** No code path
here reads a body, a header, a cookie or a query string. That is the guarantee;
everything below is a second line of defence.

### Redaction is defence in depth, not permission

A filter blanks obvious secret-bearing patterns in message text —
`password=…`, `"token": "…"`, `Authorization: Bearer …`,
`redis://user:pass@host` — replacing the value with `[REDACTED]` while keeping
the key, so the line stays diagnosable.

**It makes no promise of perfect detection.** It cannot recognise a secret that
does not look like one. It exists to catch a third-party library that
interpolates something careless into a message, not to make logging a request
acceptable. Do not log the thing in the first place.

---

## 8. Celery

The worker no longer hijacks the root logger
(`CELERY_WORKER_HIJACK_ROOT_LOGGER = False`), so its output goes through the
same JSON formatter and the same allow-list, tagged `service: celery`.

Celery's own startup banner is printed before logging is configured and stays
plain text. Everything after it is JSON.

**Task arguments are not logged as arguments.** Verified against Celery's own
source rather than assumed:

- `LOG_FAILURE` and `LOG_INTERNAL_ERROR` are
  `Task %(name)s[%(id)s] %(description)s: %(exc)s` — name, id, exception. No
  args.
- `LOG_RETRY` is `Task %(name)s[%(id)s] retry: %(exc)s`. No args.
- `LOG_RECEIVED` is `Task %(name)s[%(id)s] received`. No args in the message —
  **but** args and kwargs reprs ride along in `extra['data']`, which is why the
  formatter allow-list in §3 matters.

Confirmed live: a task dispatched with a sentinel argument produced
`Task documents.tasks.scan_document_version[<id>] received` with **no argument
anywhere in the record**.

> **But an exception message can still echo an argument.** The same dispatch
> failed, and Django's error text was
> `ValueError("Field 'id' expected a number but got 'TEST_DO_NOT_LOG_TENANT_888'.")`.
> Celery's `LOG_FAILURE` includes `%(exc)s`, so the value travelled inside the
> exception message. See §13 — this is inherent to exceptions, not to Celery
> argument logging, and it is pinned by a test.

Do not run the worker at `--loglevel=debug` in production; debug output is
outside what has been reviewed here. Compose uses `--loglevel=info`.

---

## 9. Levels

| Environment | Root | `regx.*` | Notes |
|---|---|---|---|
| development | INFO | DEBUG | our own code is verbose; nothing else is |
| production | INFO | INFO | |
| test | WARNING | WARNING | handler is `NullHandler`; tests attach their own |

`django.security` at WARNING and above. `django.request` at WARNING and above.

**`django.db.backends` is pinned at WARNING everywhere, including development.**
At DEBUG that logger emits every SQL statement executed, which means parameter
values.

**The sensitive-data policy is identical in development.** A request body is no
less confidential because `DEBUG=True`. Nothing here logs bodies in any
environment.

---

## 10. Destination and retention

Containers log to **stdout/stderr**. No file handler, no log directory, no
rotation configured in the application.

| Decision | Status |
|---|---|
| Log aggregation | **PENDING IT / OPERATIONS DECISION** |
| Operational-log retention | **PENDING QA / IT / SECURITY APPROVAL** |

No SIEM, vendor, shipping pipeline, archival policy or retention period is
assumed or invented here.

**This is not regulated audit-record retention**, which is a separate question
about `AuditEvent` rows and their backups — see `BACKUP_RESTORE_DR.md`.

---

## 11. Operator examples

```bash
docker compose logs -f backend
```

```bash
docker compose logs backend | grep '"level":"ERROR"'
```

Follow one request across services, given an `X-Request-ID` from a response:

```bash
docker compose logs backend celery | grep '7c1f8e2a-0b44-4a1e-9f30-6d2c5b8e1a77'
```

Slowest requests in the current log:

```bash
docker compose logs backend | grep '"event":"request completed"' | sort -t: -k1
```

Field-wise, with `jq` on the host:

```bash
docker compose logs --no-log-prefix backend | jq -r 'select(.status_code >= 500) | "\(.request_id) \(.path) \(.status_code)"'
```

---

## 12. Failure behaviour

Logging must not be able to break the application.

- The formatter catches its own exceptions and falls back to a minimal, still
  parseable JSON line rather than raising inside `logging`.
- The redaction filter never drops a record; if redaction fails, the record
  still goes out.
- Setting the response header is guarded — some streaming responses reject item
  assignment, and failing to attach a diagnostic header must not fail a request.
- **No database query is performed to enrich a log line.** Every field comes
  from the request object or the record itself.

---

## 13. Limitations

- **Not monitoring, alerting or an SLA.** Nothing here pages anyone, aggregates,
  or measures against a target.
- **Redaction is best-effort** and cannot recognise an arbitrary secret. §7 is
  the control.
- **An exception message can contain the value that caused it.** Libraries
  interpolate offending input into error text —
  `ValueError("Field 'id' expected a number but got 'X'.")` — and that message is
  logged. This is inherent to Python exceptions, applies to the HTTP path as
  much as to Celery, and predates structured logging: the same text was emitted
  before, merely unstructured. Redaction cannot help, because the value does not
  look like a secret. Suppressing exception messages entirely would remove most
  of the diagnostic value of an error log, so the behaviour is documented and
  pinned by a test rather than hidden. **A caller must not pass a secret where an
  exception could name it** — for example as a lookup key.
- **Only the backend and worker are covered.** nginx writes its own access log
  in its own format, and the company site is unchanged — it is carried in
  verbatim from a read-only source.
- **No request id is propagated to the frontend or into nginx**; correlation
  starts at the Django boundary.
- **Log volume is not bounded** by the application. Retention belongs to
  whatever runs the containers — see §10.
- **`duration_ms` measures the Django middleware stack only**, not time spent in
  nginx or on the network.

---

## 14. Tests

`backend/common/tests/test_operational_logging.py` — 43 tests. Most are
negative: they assert a specific string is *absent* from formatted output.

Synthetic sentinels only, never real credentials: `TEST_DO_NOT_LOG_PASSWORD_123`,
`TEST_DO_NOT_LOG_TOKEN_456`, `TEST_DO_NOT_LOG_COOKIE_789`,
`TEST_DO_NOT_LOG_BODY_012`.

Covered: identifier present on request and response · hostile inbound headers
rejected (including an embedded newline and a 5,000-character value) ·
completion event fields · query strings excluded · eight genuinely concurrent
requests keeping distinct identifiers · `Authorization`, `Cookie`, password,
token and body sentinels absent from a full request cycle including its error
path · exception correlation, class and trace · exceptions re-raised unchanged ·
health probes at DEBUG while a failing probe stays at ERROR · Celery task args
in `extra` not emitted · redaction patterns · formatter robustness against an
unrenderable message.
