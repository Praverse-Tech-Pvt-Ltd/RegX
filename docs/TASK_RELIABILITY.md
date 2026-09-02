# Task reliability

Every Celery task in RegX, what happens when it is delivered twice, and what
happens when the worker dies partway through.

**Distributed ambiguity is documented, not hidden.** Where an outcome genuinely
cannot be known, this says so rather than picking the comfortable answer.

## The tasks

| Task | Idempotent | Retry | Attempts | Backoff | Side effect | Failure state |
|---|---|---|---|---|---|---|
| `documents.scan_document_version` | yes — returns early if `scan_status` is already CLEAN or QUARANTINED | yes | 3 | 30s | local only (status write) | `SCAN_FAILED`; **never** CLEAN |
| `documents.process_document_version` | yes — job row keyed on the version | yes | 3 | 30s | local only | `FAILED` on the job |
| `external_integrations.run_connector_execution` | yes — claimed under a row lock | transient failures only | 3 | 30s × attempt | **external** | `FAILED` with an enumerated code |

## Dispatch happens after commit

All four dispatch sites use `transaction.on_commit`:

```
documents/ingest.py          scan_document_version
documents/views.py           scan_document_version   (version upload)
documents/tasks.py           process_document_version
external_integrations/views  run_connector_execution
```

Measured before this changed, with a caller holding a transaction: the scan was
dispatched **1 time before commit and 0 times after**. A worker picking that
message up finds no row, logs "not found", and returns — so the version is never
scanned and nothing reports a failure.

That was latent rather than live: no caller wrapped `ingest_new_document` in a
transaction, and with `ATOMIC_REQUESTS` off the request path committed first.
It is fixed anyway because `ingest_new_document` became a shared public entry
point in Milestone 14, wrapping a service call in a transaction is an ordinary
thing to do, and the failure is silent. `on_commit` outside a transaction runs
immediately, so the ordinary path is unchanged.

## Duplicate delivery

A broker may deliver the same message twice. Neither task may produce duplicate
governed history.

* **Scan** — re-entering after the status is resolved returns immediately. A
  duplicate produces no second audit row and no second status write.
* **Connector execution** — `claim_execution` moves QUEUED → RUNNING under
  `select_for_update`. A second delivery finds a status that is not QUEUED and
  returns **before any remote call**. That is the property that matters: the
  duplicate costs a database round trip, not a second transfer.

## Worker crash windows

These are analysed one by one because the honest answer differs.

### Execution marked RUNNING, then the worker dies

The execution stays `RUNNING` with no worker attached. Nothing currently moves
it, and **that is deliberate rather than an oversight** — see below.

### Package archive built, then the remote call begins, then the worker dies

**The outcome is genuinely unknown.** The endpoint may have received every byte
and stored it, or received nothing. RegX cannot distinguish these from its side,
and no amount of local state makes it able to.

What the system does *not* do is guess. It does not mark the execution
`FAILED` — that would assert the transfer did not happen, which may be false and
would invite a resend that duplicates a real one. It does not mark it
`SUCCEEDED` — that would assert acceptance nobody observed.

The execution remains `RUNNING`, which is the only state that is true: it
started and its outcome was never recorded.

### Document stored, then the scan dispatch fails

The version exists with `scan_status = PENDING`. The document platform's own
rules govern what may be done with a version that has not been cleared, so the
failure mode is "unusable", not "wrongly trusted". This is the correct direction
to fail.

### Audit emitted, then the task dies

Audit rows are written inside the governed transaction that caused them, so a
task dying after the transaction leaves an accurate record of what happened up
to that point. An audit row never claims a later step that did not run.

## Why there is no automatic stale-work recovery

Milestone 15 considered adding a lease or heartbeat that would reclaim a
`RUNNING` execution after some interval. **It was deliberately not added**, and
the reasoning matters more than the decision.

Reclaiming means one of two things:

1. **Re-run it.** For `PUSH_FROZEN_PACKAGE` that means sending the archive
   again. The remote endpoint is offered an `X-Idempotency-Key` and may or may
   not honour it — RegX has no way to know, and Milestone 14 explicitly refuses
   to claim exactly-once delivery it cannot support. Automatically resending
   after a crash would turn "we do not know" into "we sent it twice".
2. **Mark it failed.** That asserts the transfer did not happen. It may have.

Both replace an honest unknown with a confident falsehood. A timer does not
produce information the system does not have.

What is provided instead:

* The execution's `started_at` makes stale work **visible** — a query finds
  every execution RUNNING for longer than any transfer should take.
* The `correlation_id` on the row joins it to the request that created it and to
  every structured log line the worker emitted, so an operator can see how far
  it got.
* An operator can cancel a QUEUED execution; a RUNNING one is deliberately not
  cancellable, because cancelling something that may already have sent bytes
  would record an outcome nobody observed.

**Finding stale work:**

```sql
SELECT public_id, connector_id, operation, started_at, correlation_id
  FROM external_integrations_connectorexecution
 WHERE status = 'running'
   AND started_at < now() - interval '1 hour'
 ORDER BY started_at;
```

The resolution is a person deciding, with the remote system's own records in
front of them, whether the transfer landed. That is a smaller ask than it
sounds, it happens rarely, and it is the only route to an answer that is
actually true.

An `OUTCOME_UNKNOWN` state was considered and rejected for this milestone: it
would rename the situation without adding information, and `RUNNING` with a
`started_at` in the distant past already says exactly that. Adding a state
because it sounds more sophisticated is how a status vocabulary stops meaning
anything.

## Retry classification

Retried: timeout, connection reset, 429, 502, 503, 504.

Not retried: 400, 401, 403, 404, a plain 500, and every semantic refusal
(`DOCUMENT_REJECTED`, `PACKAGE_INTEGRITY_FAILED`, `PAYLOAD_INVALID`). Repeating
an identical request that was refused on its merits is a loop, not a retry.

Attempts are capped at 3. A permanently broken endpoint costs a known amount of
work rather than an unbounded amount.
