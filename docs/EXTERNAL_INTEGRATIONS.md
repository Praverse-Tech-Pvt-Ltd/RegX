# External integrations

> **A CONNECTOR IS A TECHNICAL DESTINATION.** `ACTIVE` means a tenant has
> enabled it. It is not approval, not validation of the remote system, not
> qualification, and there is deliberately no `APPROVED` state.

> **NO TRANSFER IS A SUBMISSION.** An execution records a technical transfer
> attempt against an endpoint a tenant configured. It is not an agency
> submission, not a filing, not a gateway transmission. `SUCCEEDED` means the
> endpoint accepted the bytes — nothing about what it did with them.

> **No agency format and no gateway ships.** No eCTD, no sequence generation, no
> regional module, no NeeS, no ESG or gateway transmission, no FDA or EMA
> validation, no electronic signature, no Part 11 or GxP claim.

---

## 1. What this milestone is

A reusable framework for moving content between RegX and systems nobody in RegX
controls, with two operations implemented on top of it:

```
IMPORT_DOCUMENT       fetch bytes -> the normal document pipeline
PUSH_FROZEN_PACKAGE   an exact frozen M13 snapshot -> a configured endpoint
```

Everything else is the framework: connector configuration, credential
references, destination policy, bounded transport, execution lifecycle,
idempotency, retries, external-object identity, audit, and a database floor.

## 2. What it is not

No production SharePoint, Microsoft Graph, Google or Gmail credentials. No
agency gateway. No automatic dossier submission, QA approval or electronic
signature. No SSO/OIDC/SAML, no row-level security, and nothing from the
deferred owner-policy or security packages.

**And no free-form automation.** There is no user-supplied Python, no shell
command, no template, no expression, no importable dotted path, and no generic
"call this URL with this body" operation. A connector describes *where* to talk;
it says nothing about how this process behaves.

## 3. Connector types

**`GENERIC_HTTPS` only.**

SFTP was scoped and dropped. Doing it properly needs pinned host keys, an
explicit known-hosts policy, no agent forwarding and no `ProxyCommand`; doing it
improperly means `AutoAddPolicy` and a connector that trusts whatever answers on
port 22. One connector type with a defensible security model beats two where the
second is a placeholder. Vendor names are absent for the same reason: an enum
member with no working transport is a promise the code does not keep, and a
tenant selecting `SHAREPOINT` would reasonably expect SharePoint.

The enum is open for a later milestone to extend.

## 4. Destination policy — the security case

A connector lets an authenticated tenant user cause the RegX server to make an
outbound request. That is server-side request forgery unless every destination
is proved acceptable first, and the server sits inside a private network next to
an unauthenticated metadata endpoint that hands out credentials to anything that
asks.

| Rule | Behaviour |
|---|---|
| Scheme | `https://` only. No `http`, `file`, `ftp`, `gopher`, `data`, `javascript`, `ws`, unix sockets. **No development-only escape hatch** — one that exists in the code exists in production |
| Credentials in URL | `https://user:pass@host/` refused |
| Port | 443 and 8443 only, so the connector cannot report reachability of arbitrary services by timing |
| Address | **Every** resolved address must be public. Private, loopback, link-local, multicast, reserved and unspecified are refused |
| Literal addresses | `127.0.0.1`, `[::1]`, `169.254.169.254`, and the integer (`2130706433`), hex (`0x7f000001`) and octal (`0177.0.0.1`) spellings never reach the resolver |
| Redirects | **Not followed.** A 3xx is the destination nominating a new destination, and the destination does not get to choose |
| TLS | Verification always on. `verify_tls: false` is refused by the schema; there is no flag and no environment override |
| Proxies | None, and environment proxy variables are not consulted — a proxy is a destination that was never checked |

### Text validation is not enough

`evil.test` can resolve to `169.254.169.254`. So the hostname is resolved, every
answer classified, and the connection made **to a checked address**.

**A mixed answer set refuses the whole destination.** Picking the one public
address out of an answer that also contains a private one would be choosing to
run the race rather than avoiding it.

### The residual window, and how it is closed

The standard HTTP client resolves the name again inside itself, which reopens
the rebinding window. `transport` therefore uses a small `HTTPSConnection`
subclass that connects the socket to the **checked address** while TLS and the
`Host` header still carry the **hostname** — so certificate validation is
unaffected and the DNS answer that was checked is the one actually used. That is
the whole reason this app does not use a higher-level HTTP client.

### Paths

A connector configures `allowed_path_prefix`; an operation's path may only
*extend* it. Absolute paths, scheme-relative `//host/x`, absolute URLs, `..`,
and percent- or double-percent-encoded separators are all refused. `urljoin`
would honour several of those and send tenant content somewhere nobody
configured, so nothing here uses it.

## 5. Credentials

RegX stores the **name** of a secret, never a secret.
`ConnectorCredentialReference` has no value column — a structural guarantee
rather than a convention: a column that does not exist cannot be written by a
raw cursor, leaked by a serialiser, or carried into a database backup.

Resolution reads an environment variable, derived from the connector's public id
or named explicitly. **No default, no development fallback, no hard-coded value.**
A missing secret is a loud enumerated failure, never an empty string that
produces an unauthenticated request nobody notices.

The credential adapter owns the `Authorization` header, which is why it is not a
configurable static header: a configurable auth header is a plaintext secret in
a JSON column with extra steps.

### This is not a secret manager

It has no rotation, no versioning, no access log of its own, no envelope
encryption and no per-tenant key separation. It reads an environment variable.
Saying so plainly is the point.

**Consequence, documented rather than hidden:** a retry after a rotation
resolves the *current* value, because nothing anywhere records which value was
used. Pinning a credential version is secret-manager work and is out of scope.

## 6. Configuration

JSON, because different connector types need different fields — and that is the
only reason. Every key is named, every value typed and bounded, and an unknown
key is an error rather than something quietly carried along.

**Validated twice, deliberately.** Once on write, and again in `transport`
before a request is built. The second pass is not redundant: it covers a row
written by a raw cursor, a migration, or a code path that did not exist when the
validator was written.

| Field | Bound |
|---|---|
| `base_url` | https, public destination, allowed port |
| `allowed_path_prefix` | absolute, no traversal |
| `connect_timeout_seconds` | 1–15 |
| `read_timeout_seconds` | 1–120 |
| `max_response_bytes` | 1 KiB – 512 MiB |
| `verify_tls` | must be `true` |
| `static_headers` | ≤ 8, from an allow-list (`accept`, `accept-language`, `x-client-id`, `x-request-source`) |

Rejected outright: `Authorization`, `Proxy-Authorization`, `Cookie`, `Host`,
`Content-Length`, `Transfer-Encoding`, `Connection`, and anything not on the
allow-list. One message covers "forbidden" and "not listed", because naming
which branch fired would describe the forbidden list.

### Configuration versioning

Every real change bumps `configuration_version`; a no-op save does not, because
a number that moved on every write would be meaningless. An execution records
the version it was created under **and a snapshot of the safe configuration**,
so an edit between queue and run cannot silently redirect a transfer somebody
already authorised. A database trigger refuses a configuration change that does
not bump the version.

## 7. Transport

* Bounded reads, enforced **while streaming** rather than from `Content-Length`
  — a header is a claim, and a hostile endpoint can send more than it declares.
* Refusal, never truncation. A document silently missing its last megabyte still
  hashes to something, gets stored, and looks fine.
* Connect and read timeouts always set. Never infinite.
* `GET`, `HEAD`, `POST`, `PUT`. `DELETE` is absent because this milestone
  performs **no destructive remote operation at all**; `TRACE` and `CONNECT`
  because they exist to make a server do something other than serve a resource.
* `Accept-Encoding: identity`, so the byte cap bounds content rather than
  compressed content.
* Nothing the remote said is returned verbatim. A status code, bounded bytes
  when bytes were asked for, and two sanitised identity headers. A remote error
  body is attacker-influenced text: it is drained, mapped to an enumerated code,
  and dropped.

## 8. Operations

### `IMPORT_DOCUMENT`

Fetched bytes go to `documents.ingest.ingest_new_document` — **the same function
the upload endpoint calls**. That function was extracted from the upload view
during this milestone precisely so there would be one pipeline: two
implementations of "validate, hash, store, version, scan" drift, and the one
that drifts is the one nobody is looking at.

There is no `trusted_source` parameter and no way to skip a step. Filename and
size rules, declared-vs-detected MIME agreement, Office container and macro
inspection, archive checks, SHA-256 over the real bytes, storage that verifies
that checksum, and the malware scan all apply. A version arrives `PENDING` and
the scan is queued, exactly as for a browser upload.

Streamed to a temporary file and **handed on as that file**. Everything
downstream reads with `seek`/`read` in bounded chunks -- the validators, the
checksum, the storage backend -- so nothing needs the content in memory and
nothing puts it there. The temporary file is closed on success and on failure,
and the document platform's storage owns the bytes from then on. There is no
second integration-owned file store.

> **Review finding (PR #42).** This originally built a `SimpleUploadedFile` from
> `handle.read()`, which materialised the entire import in the worker and made
> the temporary file pointless -- a worker-stability risk as soon as two large
> imports overlapped. Two tests hold it shut: one asserts the object reaching
> `ingest` has a real file descriptor (a `BytesIO`-backed upload does not), and
> one watches the temporary handle itself for an unbounded `read()`. The second
> is watched at the handle rather than inside `ingest`, because the defect read
> the body *before* handing it on and a downstream watcher would have seen
> nothing.

The import ceiling is `DOCUMENT_MAX_UPLOAD_BYTES` rather than a number chosen
here: reading far more than the platform will accept is work a hostile endpoint
can make the worker throw away, and two numbers that must agree would drift.

#### The same request validation, not just the same pipeline

Sharing `ingest` is only worth doing if both callers are held to the same rules
*above* it too. `document_type` is the same `ChoiceField(DocumentType.choices)`
the upload endpoint uses, and it is **required**, because the upload endpoint
requires it and there is no honest value to guess for a remote object.

This was found by comparing the two paths rather than by a test failing, and the
defect was **systemic rather than edge-case-only**.

The connector import path did not merely accept invalid document types; it
defaulted omitted `document_type` values to `"other"`, which is not present in
`DocumentType` — the enum is `pdf`, `docx`, `xlsx`, `pptx`. Because model
`choices` are not enforced by `objects.create()`, every import omitting the field
could persist an invalid document type. A hostile or mistaken *supplied* value
was only one manifestation; the default fired on the ordinary path, every time
the field was left out.

M14 now requires `document_type`, validates against `DocumentType.choices` at the
API boundary, and revalidates against `DocumentType.values` in the
worker/operation path.

The operation checks again before ingesting, for the same reason the
configuration is re-validated before a request: a stored summary is still a
stored value, and `run_import_document` is reachable from a task, a retry, and
any future caller that never met the serializer. An invalid type there is an
enumerated `PAYLOAD_INVALID`, not a `KeyError` surfacing as `INTERNAL_ERROR`.

A parity test asserts
`set(upload choices) == set(import choices) == set(DocumentType.values)`, so
drift on *either* side fails and neither side can grow a hand-maintained list.

### The declared content type reaches the worker

> **Review finding (PR #42).** `declared_mime` was accepted by the serializer and
> then dropped: the view never put it in the request summary, so the worker
> always fell back to guessing the type from the filename.
>
> That is not a cosmetic loss. The document platform stores a *declared* and a
> *detected* type in order to compare them, and a guess derived from the same
> filename the detection ran on can never disagree in the way the check exists to
> catch. A remote system claiming `application/pdf` while serving something else
> would have passed unnoticed. The value is now carried through, and a test
> declares a spreadsheet while serving a PDF and requires the import to be
> refused.

The fallback remains when the caller declares nothing -- a browser derives the
type from the file too -- so an omitted optional field does not refuse an
otherwise valid import. A declared type is never *trusted over* the bytes:
detection still runs, and a macro-bearing archive named `.pdf` is refused however
it is labelled.

### `PUSH_FROZEN_PACKAGE`

Milestone 13 produces the archive. This module never reconstructs a package,
never selects "the latest revision", and never touches a package that is not
`FROZEN`.

The execution binds to `package_public_id`, `snapshot_public_id` **and**
`manifest_checksum` at creation. If either has moved when the worker runs, this
is not the transfer that was authorised and it is refused. If M13's exporter
refuses to produce the archive — a missing file, manifest drift — the failure
happens locally, before any remote call.

### What is not claimed

A 2xx means the endpoint accepted the bytes. It does not mean the remote system
stored them, indexed them, or will still have them tomorrow.

Remote checksum comparison happens **only when the endpoint returns one**. When
it does not, `remote_checksum_verified` is `false` and stays that way. Silence is
recorded as silence.

## 9. Permissions

| Action | Requires |
|---|---|
| view connectors | `external_integrations.view` |
| create / edit | `external_integrations.create` / `.edit` |
| enable / disable | `external_integrations.enable` |
| test connection | `external_integrations.test` |
| run a connector | `external_integrations.execute` |
| view history | `external_integrations.view_history` |
| **import a document** | `external_integrations.execute` **+ `documents.create`** |
| **transfer a package** | `external_integrations.execute` **+ `submission_packages.export` + `documents.view`** |

**Connector permission is never content permission.** A caller who could not
read a document through the documents API must not be able to read it by asking
a connector to send it somewhere, and a caller who could not create a document
must not be able to create one by asking a connector to fetch it. Each gate is
checked against its own app's role map, never a copy.

Target-domain gates run **before the target is resolved**, so absent,
cross-tenant and unauthorised are one indistinguishable answer. A connector
endpoint that answered 403 for a package in another tenant would let a caller
enumerate package ids across the deployment.

Configuring a destination is elevated: `create`, `edit` and `enable` sit with
`TENANT_ADMIN` alone. `DOER` can run an existing connector and read history;
`REVIEWER` and `VP` observe; `PLATFORM_SUPPORT` can see that connectors exist,
cannot run one, and holds no document permission anywhere.

## 10. Execution lifecycle

```
QUEUED ──► RUNNING ──► SUCCEEDED / FAILED / CANCELLED
QUEUED ──► CANCELLED / FAILED
RUNNING ──► QUEUED        (a transient failure returning for another attempt)
```

No `APPROVED`. Terminal states are permanent.

**Claimed under a row lock.** A second worker that arrives while the first is
running sees a status that is no longer `QUEUED` and stops — before any remote
call. The connector is re-read at start: one disabled between queue and run ends
the execution `CANCELLED` with no remote call, because a transfer that left
after somebody turned the connector off would make the switch a lie.

### Idempotency

The key is a SHA-256 over the connector public id, the operation, and
identifiers of what is being moved — for a package, the snapshot public id and
the manifest checksum. **The package name is deliberately absent:** it is
display text a user may edit, and a key that moved on a rename would let the
same transfer run twice. `(tenant, idempotency_key)` is unique in the database.

Repeating an identical request returns the execution that already exists (200),
not a second one.

**No exactly-once claim.** The remote endpoint is offered an
`X-Idempotency-Key` header; whether it honours it is the remote system's
business, and nothing here records delivery as if it were guaranteed.

### Retries

Bounded at three attempts. Only genuinely transient failures are retried —
timeout, connection reset, 429, 502, 503, 504. A 400, 401, 403, 404 or a
semantic refusal is not: repeating an identical wrong request is a loop, not a
retry. A plain 500 is not retried either; 502/503/504 are, because they say
something about the path rather than the request.

## 11. What is stored

Allow-listed summaries only.

* **Request**: operation, resource ids, checksum, path, title, declared MIME.
* **Response**: status code, bytes transferred, latency, external reference,
  remote checksum and whether it was verified.

**No raw response is ever persisted** — not the body, not the headers, not the
URL, not an exception string. A remote error page can contain another tenant's
data, an internal hostname, a stack trace, or markup that will one day be
rendered somewhere. Storing it "for debugging" means storing all of that
permanently on the assumption nobody looks.

Nested structures are dropped from summaries rather than coerced: a nested value
is how "just a small summary" becomes a copy of the remote payload.

## 12. External object links

Identity only: "this RegX object and that remote object are the same thing". No
remote payload, no cached content, no mirrored metadata — a copy of a remote
record is a second source of truth that nothing keeps correct.

Remote identifiers are bounded strings. An `external_url` is stored **only if it
passes the same destination policy a connector does**, and dropped otherwise
rather than stored-and-flagged; the UI shows the identifier as plain text when
there is no safe URL.

## 13. Audit

`external_connector.created / updated / enabled / disabled / archived / tested`,
`external_execution.created / started / succeeded / failed / cancelled`,
`external_object.linked`.

Payloads are allow-listed and bounded. Public ids, checksums, enumerated codes,
counts and statuses travel. A secret value, an environment variable's contents,
a remote response body, a remote header, a base URL, a filename and a raw
exception string do not — and neither does the connector's own name, which is
free text a tenant wrote.

## 14. Logging

Structured, with `correlation_id`, `execution_public_id`,
`connector_public_id`, `operation`, `status`, `attempt` and an enumerated code.
The correlation id is carried from the request that created the execution, so a
transfer that happens minutes later still joins up with the click that asked for
it.

Never logged: any `Authorization` value, API key, password, private key, raw
document content, or a full remote response. An unexpected exception goes to the
log with `exc_info` — where the repository's redaction filter applies — and the
execution row gets an enumerated code and nothing else.

## 15. Tenant isolation

Every connector, credential reference, execution and object link is
tenant-scoped, and cross-tenant is 404 rather than 403. Database triggers refuse
a credential reference, an execution or an object link whose tenant differs from
its connector's, so tenant A cannot name tenant B's credential even through a
raw cursor.

## 16. Database governance

`0002` — 8 plpgsql functions, 9 triggers.

| Trigger | Enforces |
|---|---|
| `guard_insert_connector` | positive configuration version; configuration is a JSON object |
| `guard_update_connector` | tenant and type immutable; version never decreases; a configuration change must bump the version |
| `guard_insert_credential_reference` | same tenant as its connector |
| `guard_insert_execution` | same tenant as its connector; a configuration version that exists; `QUEUED` as the only starting state; an idempotency key present |
| `guard_update_execution` | identity and provenance frozen always; a terminal execution refuses every UPDATE; only documented transitions; attempt count never decreases |
| `no_delete_execution` / `no_delete_external_object_link` | history is never deleted (one shared function, two triggers) |
| `guard_insert_external_object_link` | same tenant as its connector; names a remote object |
| `guard_update_external_object_link` | which RegX resource a link is about never moves |

`Model.save()` resolves through `_base_manager`, so no manager restriction covers
a bare `save()`, and a raw cursor never runs a line of Python. The triggers are
the floor, and the tests go around the ORM to prove it.

### What the database cannot prove

It cannot tell whether a `configuration` is *safe* — that a `base_url` resolves
to a public address, that a header is on the allow-list, that a prefix does not
traverse. Reproducing `netpolicy` and `config_schema` in plpgsql would be two
implementations of a security policy in two languages, and the one that drifts
would be the one nothing tests. The trigger checks shape; Python checks policy,
on write and again on use.

It also cannot tell whether a remote system stored anything, and nothing here
records that as if it were known.

## 17. Deletion

Connectors are **archived**, never deleted: executions reference them under
`PROTECT`, and that history is evidence of what was transferred. Terminal
executions and object links cannot be deleted at all.

There is no remote delete operation. Inbound and outbound only.

## 18. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — four `CreateModel`s, no `RunPython`/`RunSQL`, no existing table altered | **CLASS C — DATA RESTORE REQUIRED** once execution history exists |
| `0002_integration_db_governance` | **Class A** — 8 functions, 9 triggers; no table altered, no row read or written | **Class A on its own terms** |

> Reversing `0001` destroys every execution — the record that a document or a
> package left this deployment, under which configuration and with what result.
> The remote system may or may not still have the bytes; RegX's statement about
> what it sent exists only here. Removing `0002`'s protection does **not** make
> reversing `0001` safe.

The `0002` counts are asserted against the generated SQL by a symmetry test that
ships with the migration — and that test caught this migration's own docstring
claiming six functions where there are eight.

## 19. Backup and restore

The new tables are ordinary PostgreSQL tables and are covered by the existing
database backup. **No new persistent file store is added**: imported bytes go to
the document platform's storage, and outbound archives are built into a
temporary file and discarded.

Integration execution history and external object links are recoverable from a
database restore. **Remote systems are not.** Nothing RegX backs up can restore
what a third-party endpoint did or did not keep.

## 20. Testing

**Backend**: destination policy against every private range, literal
spelling and rebinding shape; URL, path and header rules; configuration schema
bounds; credential resolution and every way a secret could escape; the socket
path against a loopback server; connector lifecycle and versioning; execution
permissions with each target-domain gate removed in turn; tenant isolation
across service, API and raw SQL; idempotency and duplicate suppression;
config-change and disable-during-queue behaviour; the import pipeline against a
macro document, a malformed archive, oversized content, mismatched MIME and an
empty response; package transfer exactness; retry classification; response
retention; database governance; migration symmetry; audit and structured
logging; regulatory boundaries; and query-cost invariance.

**Frontend**: 14 unit, 24 new accessibility checks (104 → 128), 17 Playwright.

### Mutation testing

Every guard was removed in turn; each turned tests red, and all twelve touched
files were restored md5-identical.

| Mutation | Red |
|---|---|
| Private-address classification always true | 35 |
| Response-summary allow-list removed | 12 |
| Service tenant assertion neutered | 8 |
| Terminal-execution immutability removed | 7 |
| Redirects treated as ordinary responses | 6 |
| Path containment removed | 5 |
| DNS answers no longer classified | 4 |
| Response reads unbounded | 4 |
| Missing secret becomes an unauthenticated request | 4 |
| Every 4xx made retryable | 4 |
| Package target-domain permission gates removed | 3 |
| Exact-snapshot binding removed from package push | 2 |
| TLS verification made configurable | 2 |
| Credential resolvability returns the value | 2 |
| Idempotency lookup removed | 1 |
| Connector no longer re-checked when the worker starts | 1 |
| Execution uses today's config instead of its snapshot | 1 |
| Connector import loses the upload path's type constraint | 14 |
| Worker stops re-checking the document type it was handed | 4 |
| Import materialises the body instead of streaming | 2 |
| Declared content type dropped before the worker | 2 |
| Scan dispatch removed from the document pipeline | 1 |

**Four mutations initially turned nothing red. All four were real defects.**

1. **The service's tenant assertion.** Neutering `_assert_tenant` changed
   nothing, because every endpoint scopes by tenant in the queryset and the
   service was never reached with a mismatched tenant. That is not a reason to
   delete the check — the service is importable, callable from a task, and will
   be called from a future endpoint by somebody who assumes it is safe. Seven
   tests now exercise it where it lives.

2. **Terminal-execution immutability.** The test rewrote `status`, which the
   *transition* rules already refuse, so the terminal guard never had to fire.
   Eight tests now rewrite `error_code`, `external_reference`, `attempt_count`,
   the timestamps and the response summary — fields the transition rules say
   nothing about, so only "a finished execution cannot be changed" can refuse
   them. That is the property that matters: an execution whose *result* could be
   edited afterwards would record what somebody last said happened.

3. **Path containment was a tautology.** `full_path.startswith(prefix)` compared
   a string against the prefix it had just been built from, so it could never
   fail. It is now checked on the `normpath`-resolved path, which makes it a
   real guard that fires if the traversal rejection is ever weakened — and it is
   tested with that rejection deliberately disabled, since with both active no
   input reaches it.

4. **The summary allow-list.** The tests only ever passed keys that were already
   allowed, or nested values the *type* filter would drop anyway. They now pass
   a plain string under a key nobody named — which is the shape a remote body
   actually arrives in, and the only thing the allow-list can refuse.

A mutation that turns nothing red is a finding about the tests, or about a guard
that cannot fire. Both were present here.

Three further defects came from reviews rather than mutations. Two were raised
against the pushed code in PR #42 -- the import was not actually streamed end to
end, and `declared_mime` was accepted and discarded (§8) -- and the third, the
most serious, came from comparing the shared ingest paths. Comparing the connector import path against the upload path
it shares `ingest` with showed the connector's *request validation* was not
merely looser: its default for an omitted `document_type` was `"other"`, a value
outside `DocumentType`, and `objects.create()` does not enforce `choices`. Every
import that omitted the field could persist an invalid type. See §8.

### What the tests deliberately do not do

They never contact a real external service, and never a metadata endpoint.
`169.254.169.254` appears as a string being refused, never as a socket. The
transport double records what *would* have gone out; `netpolicy` is never
doubled, because a stub that always said "fine" would make every SSRF test
vacuous.

## 21. Known limitations

* **HTTPS only.** No SFTP, no vendor connectors.
* **Not a secret manager.** Environment variables, no rotation or versioning; a
  retry after a rotation uses the current value.
* **No exactly-once delivery** unless the remote endpoint implements the
  idempotency key it is offered.
* **No proof of remote storage.** A 2xx is acceptance of bytes, nothing more.
* **No remote checksum verification** unless the endpoint returns a checksum.
* **Internal destinations are refused**, including legitimate ones. Allowing
  them would be an owner-policy decision, and this milestone makes none.
* **The database cannot validate a destination.** That check lives in Python and
  runs twice.
* Not a validated production interface, and no transfer here is a regulatory
  submission.
