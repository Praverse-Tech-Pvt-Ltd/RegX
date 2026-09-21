# Word Add-in — Product / Security Contract Intake

> **What this is:** a blank decision form for the product, security and
> regulatory owners. Completing it is what unblocks the Word Add-in.
> **What this is not:** an implementation, a design, an approval, or a
> recommendation. **No decision field below is pre-filled, and engineering may
> not fill one.**
> **Verified at** `regx-main` `0c7c2bb447025117af602e22ba4f70fd276798a8`. Every
> platform fact in §1 was read from code at this SHA.
> **Companions:** [WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md),
> [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md),
> [DOCUMENT_PLATFORM.md](DOCUMENT_PLATFORM.md), [TENANCY.md](TENANCY.md)

## 0. How to read this

**Present capability and missing contract are different things,** and this
document keeps them apart everywhere. Each item states what the platform already
does (fact, from code) before it states what is undecided (contract, owned by
someone else). A capability being absent is **not** by itself a defect: several
absences below are deliberate architectural positions, and the decision may
legitimately be to leave them absent.

**Engineering may explain options and consequences. Engineering may not choose.**
Where a field is blank, blank means undecided — it does not mean "engineering's
discretion" and it does not default.

| Owner role | Scope |
|---|---|
| **Security owner** | Items 1, 3, 6, 8 · dependencies A, C, D |
| **Product owner** | Items 2, 4, 7, 10, 11, 12 · dependency B |
| **Regulatory owner** | Items 5, 9, 13 · dependencies E, F |

Several items need two of the three. Each item names its own.

## 1. Platform facts, read from code at this SHA

Stated so that decisions are made against what exists rather than what is
assumed. **These are facts, not constraints on your decision** — a decision may
require changing one, which is then a scoped engineering consequence to record
in that item.

### 1.1 Authentication and session

| Fact | Value | Source |
|---|---|---|
| DRF authentication classes | `SessionAuthentication` **only** | `regx/settings/base.py:210` |
| Default permission | `IsAuthenticated` | `base.py:213` |
| Session cookie | `HttpOnly = True`, `SameSite = Lax`, age **28800 s (8 h)** | `base.py:169` |
| CSRF cookie | `HttpOnly = False` (frontend JS reads the token), `SameSite = Lax` | `base.py:174` |
| Production | `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True` | `production.py:16` |
| MFA | TOTP `MFADevice`, per-user `mfa_required` flag, encrypted secret, single-use `RecoveryCode` | `identity/models.py:36,70,111` |
| SSO | **Not implemented.** No SAML, OIDC or OpenID anywhere in first-party backend | verified absent |

> **`SameSite = Lax` and `HttpOnly = True` together are the central technical
> fact for item 1.** An Office Add-in runs in a webview on a different origin, so
> the session cookie is not sent on its cross-site requests, and its JavaScript
> cannot read the cookie to forward it. This is not a bug to route around; it is
> the control working as configured. Any Add-in authentication answer must say
> what it does about this.

### 1.2 Origin and embedding controls

| Fact | Value | Source |
|---|---|---|
| `CSP_FRAME_ANCESTORS` | `('none',)` | `base.py:201` |
| `CSP_DEFAULT_SRC` / `CSP_CONNECT_SRC` | `('self',)` | `base.py:195,200` |
| `CORS_ALLOW_ALL_ORIGINS` | `False` — explicit, never wildcard | `base.py:183` |
| `CORS_ALLOW_CREDENTIALS` | `True` | `base.py:182` |
| `CORS_ALLOWED_ORIGINS` | Environment allowlist | `base.py:181` |
| Extra allowed header | `x-tenant-slug` | `base.py:190` |

> **`frame-ancestors 'none'` means the existing REGX UI cannot be embedded in a
> Word task pane iframe at all.** An Add-in cannot reuse the current frontend by
> framing it. Items 1, 7 and 8 must be answered knowing that.

### 1.3 Tenancy

Tenant is resolved from the **`X-Tenant-Slug` request header**
(`tenancy/middleware.py:19`), not from a cookie. Isolation is enforced per-app in
service and view layers and is covered by tests. Because it is header-based, an
external client *can* supply it — **which value it should supply, and on what
authority, is undecided** (item 2).

### 1.4 Documents, versions and structure

| Fact | Value | Source |
|---|---|---|
| `DocumentStatus` | **`ACTIVE` · `ARCHIVED` only** | `documents/models.py:25` |
| **Draft / approved state** | **Does not exist on documents** | verified absent |
| `DocumentVersion` | `version_number` (unique per document), `sha256_checksum`, `scan_status`, `processing_status`; file metadata immutable once processed | `models.py:109` |
| `ScanStatus` | `PENDING` · `CLEAN` · `INFECTED` · `SCAN_FAILED` · `SCANNER_UNAVAILABLE` · `QUARANTINED` | `models.py:92` |
| `DocumentLocator` | **Per `DocumentVersion`.** `locator_type`, `locator_id`, `display_label`, `structured_metadata`, `extracted_text`, `ordering` | `models.py:198` |
| `LocatorType` | `PAGE` · **`SECTION`** · `PARAGRAPH` · `TABLE` · `SHEET` · `ROW` · `COLUMN` · `SLIDE` · `OBJECT` | `models.py:186` |

> **Two facts here are easy to conflate and must not be.**
>
> **Section *addressing* already exists and is version-bound.** `DocumentLocator`
> carries a `SECTION` type and per-locator `extracted_text`, hung off a specific
> `DocumentVersion`. Retrieval at section granularity is structurally possible
> today.
>
> **Section *versioning* does not exist.** Locators belong to a version; there is
> no independent section-version history. A section re-uploaded becomes new
> locators under a new document version, not a new version of that section.
> Dependency **B** is the decision between these, and it is a real choice rather
> than a hypothetical one.

### 1.5 Permissions

`CanCreateDocument`, `CanViewDocument`, `CanArchiveDocument`,
`CanRestoreDocument` (`documents/permissions.py`). Capability codenames per app,
role-mapped.

### 1.6 Audit

Centralized append-only `AuditEvent`, immutable at two layers — ORM guard plus
two PostgreSQL triggers ([AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)).

`DocumentEvent` declares **16** event types at this SHA, covering upload, scan,
processing, version creation, document creation, archive, restore and duplicate
detection (`documents/audit_events.py`). **None records a read, view, retrieval,
download or export** — confirmed by enumerating the constants.

> **`CanViewDocument` exists and emits nothing.** Authorisation for reading is
> implemented; audit of reading is not. That pairing is the precise shape of
> dependency **C**, and it is stated as a fact, not solved here.

### 1.7 Requirement-source limitation

SOW §2.7 and §§4.2–4.4 requirements were **relayed by the project owner on
2026-09-16** from pages 7–9 of the SOW PDF, which was not available to the gap
report's author ([WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md) §4). They
**must be verified against the primary document** when it becomes available.
Decisions recorded here against a relayed requirement should note that
dependency in their evidence field.

## 2. Decision record format

Every item below carries this block. **Blank means undecided.**

| Field | Meaning |
|---|---|
| **Status** | `DECIDED`, `PENDING`, or `NOT APPLICABLE` — and *why*, if the last |
| **Decision** | The decision itself, in enough detail to implement without a follow-up conversation |
| **Owner** | The named accountable person, not only a role |
| **Evidence / approval reference** | The approval itself, not an assertion that one exists |
| **Effective version / date** | Which version of this decision is in force, from when |
| **Implementation consequence** | What engineering will build, change or not build as a result |

---

# 3. The thirteen contract items

## Item 1 — Word-compatible authentication flow

**Decision required.** How an Office Add-in authenticates to REGX.

**Why it matters.** Every other item assumes an authenticated caller. Nothing can
be specified until this is settled, and getting it wrong either breaks the Add-in
or weakens the session model for every existing user.

**Existing capability.** `SessionAuthentication`, `IsAuthenticated` by default,
8-hour session, TOTP MFA with recovery codes.

**Current constraint.** `SameSite=Lax` + `HttpOnly` means the session cookie is
neither sent nor readable cross-site from an Add-in webview (§1.1). No SSO
exists. `frame-ancestors 'none'` blocks reusing the current UI in a task pane.

| Allowed option | Trade-off |
|---|---|
| Add-in uses its own credential exchange distinct from browser sessions | New authentication surface to design, threat-model and operate |
| Add-in depends on a future SSO/IdP position | Blocks on dependency **A**; Add-in timeline becomes SSO timeline |
| Add-in is not supported outside an already-authenticated REGX browser context | Narrowest surface; may not satisfy the SOW intent |
| Session cookie policy is relaxed for Add-in origins | **Weakens a current control for all users.** Recorded as an option because it is technically available, *not* as a recommendation |

**Owner role.** Security owner, with product owner on scope.

**Required evidence.** Threat model for the chosen flow; explicit statement of
MFA behaviour; sign-off from the security owner.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 2 — Tenant-selection behaviour

**Decision required.** Which tenant the Add-in operates as, and how that is
established and constrained.

**Why it matters.** Tenant is the isolation boundary. A client that chooses its
own tenant header without constraint is a cross-tenant risk.

**Existing capability.** Tenant resolved from `X-Tenant-Slug`; isolation enforced
per-app and tested; `x-tenant-slug` is an allowed CORS header.

**Current constraint.** Header-based resolution means an external client *can*
supply any value; what authorises a given value for a given user is not part of
this decision's existing implementation and must be stated.

| Allowed option | Trade-off |
|---|---|
| Single tenant fixed at Add-in configuration time | Simplest; no in-session switching for multi-tenant users |
| User selects from tenants they are entitled to, per session | Requires an entitlement source of truth the Add-in can read |
| Tenant inherited from the authenticating context of item 1 | Couples this item to item 1's outcome |

**Owner role.** Product owner, with security owner on entitlement enforcement.

**Required evidence.** Statement of how a supplied tenant is validated against
user entitlement, and what happens when validation fails.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 3 — Governed content-retrieval API

**Decision required.** **Whether such an API should exist at all**, and if so what
it may expose.

**Why it matters.** This is the gating item. Items 4, 5, 6, 9 and dependencies D
and E are all unanswerable until it is settled, because they describe the
behaviour of an interface whose existence is undecided.

**Existing capability.** No document-content API exists. Documents, versions and
locators exist behind `CanViewDocument`.

**Current constraint.** `CSP_CONNECT_SRC = 'self'` and a CORS allowlist mean any
new origin must be added deliberately. Nothing today exposes document bytes or
extracted text to an external client.

| Allowed option | Trade-off |
|---|---|
| No content API; Add-in works only from already-authorised in-product context | Preserves the current boundary; most of SOW §2.7's intent unmet |
| Governed read-only API, constrained by dependency **D** | Requires D, E and C to be decided first |
| Broad document API | **Largest new attack surface**, recorded for completeness, not recommended |

**Owner role.** Security owner, with regulatory owner on what content may leave
the platform.

**Required evidence.** Approved data-exposure boundary (dependency D), and the
security owner's sign-off on the resulting surface.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 4 — Document / version / section selection semantics

**Decision required.** Exactly how a caller names the content it wants.

**Why it matters.** "The latest version" is ambiguous the moment a new version is
uploaded mid-session, and an inserted passage that cannot be tied to an exact
version cannot be audited or reproduced.

**Existing capability.** `DocumentVersion.version_number` unique per document;
`sha256_checksum` per version; `DocumentLocator` addressable per version with a
`SECTION` type and per-locator `extracted_text` (§1.4).

**Current constraint.** Locators are bound to a version. There is no section
version history (dependency **B**).

| Allowed option | Trade-off |
|---|---|
| Exact version pinning required on every request | Unambiguous and auditable; caller must handle "a newer version exists" |
| Latest-at-time-of-request, with the resolved version returned and recorded | Convenient; the recorded version becomes the authoritative answer |
| Locator-addressed within a pinned version | Most precise; depends on locator extraction quality for that document type |

**Owner role.** Product owner, with regulatory owner on reproducibility.

**Required evidence.** Written selection semantics including behaviour when the
requested version is archived, superseded or quarantined.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 5 — Draft vs approved insertion rule

**Decision required.** Whether unapproved content may be inserted into a Word
document, and how the user is told what they received.

**Why it matters.** Inserting unapproved content that *looks* approved is a
regulatory misrepresentation, and it is the failure mode
[WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md) §7 prohibits first.

**Existing capability.** Workflow approval exists for workflow objects
([WORKFLOW_ENGINE.md](WORKFLOW_ENGINE.md)).

**Current constraint — stated precisely.** `DocumentStatus` is **`ACTIVE` or
`ARCHIVED` only**. **Documents carry no draft or approved state at all** (§1.4).
So "insert only approved content" is **not expressible against documents today**.
This is a fact about the current model, not a defect and not a request to build
an approval workflow.

| Allowed option | Trade-off |
|---|---|
| Insertion permitted regardless of status, with status surfaced in provenance | No new model; relies entirely on dependency **E** being honoured |
| Insertion restricted to a content class that *does* carry approval | Narrower and safer; excludes plain documents entirely |
| A document approval state is introduced | **New model and workflow** — separate scope, not authorised by this document |

**Owner role.** Regulatory owner, with product owner on user experience.

**Required evidence.** Explicit rule, and the required user-visible indication of
source status at the moment of insertion.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 6 — Audit semantics for query / retrieval / insertion / response

**Decision required.** Which Word operations must produce regulated audit events,
and what each records.

**Why it matters.** The relayed §4.4 requirement is an immutable audit log for
every query, response, export, user action and admin change. Today a document
read produces no event at all (§1.6), so a Word insertion would leave no trail.

**Existing capability.** Centralized append-only `AuditEvent`, immutable at two
layers. 16 `DocumentEvent` types, none on the read path.

**Current constraint.** Adding event types is engineering work that follows this
decision; it is **not** performed by this document. See dependency **C**.

| Allowed option | Trade-off |
|---|---|
| Audit insertion only | Smallest volume; a query that returned content is not recorded |
| Audit retrieval and insertion | Matches the relayed §4.4 intent more closely; higher volume |
| Audit query, retrieval, insertion and response | Fullest trail; volume and payload-content questions need answers |

**Owner role.** Security owner, with regulatory owner on sufficiency.

**Required evidence.** Named operations, the fields each event records, and a
retention position. **Payload content must be constrained deliberately — the
audit table cannot be redacted after the fact.**

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 7 — Word Desktop vs Word Online support

**Decision required.** Which Word hosts are in scope, and on which platforms.

**Why it matters.** Desktop and Online differ in webview, storage, authentication
behaviour and available Office APIs. A flow that works in one can fail in the
other, and "Word" alone does not pick.

**Existing capability.** None — no Add-in exists.

**Current constraint.** Item 1's outcome may behave differently per host; this
decision and item 1 constrain each other.

| Allowed option | Trade-off |
|---|---|
| Desktop only (state Windows / macOS) | Narrower test matrix; excludes browser users |
| Online only | Simpler auth story; excludes offline and desktop-only users |
| Both | Largest matrix; every other item must hold in both |

**Owner role.** Product owner.

**Required evidence.** A support matrix naming host, platform and minimum
version, with which combinations are supported, unsupported or best-effort.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 8 — Office manifest permission scope

**Decision required.** The exact manifest permission level and declared domains.

**Why it matters.** Manifest permissions decide what the Add-in may do to the
user's document and which origins it may reach. They are a security boundary
declared in a shipped artifact, and changing them later means re-distribution.

**Existing capability.** None.

**Current constraint.** Declared domains must be consistent with the CORS
allowlist and `CSP_CONNECT_SRC = 'self'` (§1.2); a new origin is a deliberate
change, not an incidental one.

| Allowed option | Trade-off |
|---|---|
| Read-only document access | Cannot insert; likely insufficient for §2.7 |
| Read/write document access | Required for insertion; broader authority over user content |
| Read/write plus additional host capabilities | Each additional capability needs its own justification |

**Owner role.** Security owner.

**Required evidence.** **The named permission level and the explicit domain
list.** "Minimum required" is not an answer — see rejection criteria.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 9 — Provenance attached to inserted content

**Decision required.** What provenance is attached to every insertion, where it
lives, and whether it is visible to the reader.

**Why it matters.** Once text is in a Word file it leaves the platform. If it
carries no provenance, no later reader can tell what it was, which version it
came from, or whether it was approved.

**Existing capability.** `sha256_checksum` per version, `version_number`,
locator identity, tenant binding — all the identifiers needed exist.

**Current constraint.** Nothing today writes provenance into an external
document, and `DocumentStatus` carries no approval state to record (§1.4).

| Allowed option | Trade-off |
|---|---|
| Visible provenance in the inserted text | Auditable by any reader; affects document appearance |
| Hidden provenance (document property or content control) | Unobtrusive; can be stripped by the user |
| Provenance recorded server-side only, keyed to the insertion | Survives document edits; invisible to an offline reader |

**Owner role.** Regulatory owner.

**Required evidence.** The minimum field list from dependency **E**, approved.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 10 — Post-insertion modification expectations

**Decision required.** What the platform asserts about inserted content after a
user edits it.

**Why it matters.** A user can edit inserted text immediately. If provenance
remains attached to text that no longer matches the source, the provenance
becomes a false claim — worse than none.

**Existing capability.** Version immutability and checksums server-side; **no
control whatsoever over a Word document after insertion.**

**Current constraint.** Word is outside the platform's trust and control
boundary. Any expectation here is best-effort by construction.

| Allowed option | Trade-off |
|---|---|
| No assertion after insertion; provenance describes the moment of insertion only | Honest and simple; a later reader must not over-read the provenance |
| Detect modification where the host permits and mark it | Partial coverage; may fail silently on some hosts |
| Lock inserted content | Intrusive; user can usually remove the protection anyway |

**Owner role.** Product owner, with regulatory owner on what may be asserted.

**Required evidence.** An explicit statement of what the provenance means *after*
editing, worded so it cannot be read as a guarantee of current accuracy.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 11 — Add-in distribution / deployment model

**Decision required.** How the Add-in reaches users, and who administers it.

**Why it matters.** Distribution determines tenant administration, update
mechanics, review requirements and lead times, and it constrains item 1.

**Existing capability.** None.

**Current constraint.** Distribution channels impose their own review and
manifest rules, which may constrain item 8's answer.

| Allowed option | Trade-off |
|---|---|
| Centralised deployment by each tenant's Microsoft 365 administrator | Tenant-controlled; requires admin cooperation per tenant |
| Organisational catalogue | Internal control; per-organisation setup |
| Public marketplace listing | Widest reach; external review and publication constraints |
| Sideloading for named users | Fastest to pilot; unsuitable as a production model |

**Owner role.** Product owner.

**Required evidence.** The named channel, who administers it, and the update
path. **"Microsoft Office" is not a channel** — see rejection criteria.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 12 — iPharmaAI as a second delivery target

**Decision required.** Whether the same capability must also be delivered into
iPharmaAI, and if so on what terms.

**Why it matters.** The relayed §2.7 includes this, and
[WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md) §4.3 records it as **a
second delivery target not previously recorded in REGX planning**. Scope implied
but never decided is scope that surfaces late.

**Existing capability.** iPharmaAI is a **separate legacy codebase** with no
common git ancestor and no shared code
([LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md)). Nothing built in REGX applies to it
automatically.

**Current constraint.** Every decision in this document would need to be made
again for that target, against a different platform with different controls.

| Allowed option | Trade-off |
|---|---|
| REGX only | Clear scope; the relayed requirement remains unmet |
| Both, same contract | Requires the contract to hold on a platform that does not share these controls |
| Both, separate contracts | Honest about the difference; roughly doubles the decision work |
| Deferred, recorded as out of current scope | Explicit and revisitable; must be an actual decision, not silence |

**Owner role.** Product owner.

**Required evidence.** A scope decision naming the target and its timeline.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## Item 13 — Definition and verification method for "zero hallucination"

**Decision required.** What the term means here, and how conformance is measured.

**Why it matters.** It is an acceptance criterion in the relayed SOW with no
definition and no verification method. Undefined, it cannot be built to, tested
against, or signed off — and it cannot be claimed met.

**Existing capability.** **REGX contains no AI generation capability in the
backend** — verified absent at this SHA. There is therefore no generative path to
evaluate today.

**Current constraint.** The gap report records this requirement as **not
exercised and not verified**, and it stays that way until an acceptance method
exists. **Engineering must not define this term.**

**Allowed options.** See dependency **F**, which sets out what the owner must
define. No option is proposed here.

**Owner role.** Regulatory owner, with product owner on scope.

**Required evidence.** A measurable acceptance method, a test corpus, a pass/fail
criterion, and a named signatory.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

---

# 4. Platform-level dependencies

Separate from the thirteen because each is a platform position that outlives the
Add-in, and several items become unanswerable without them.

## A. SSO decision

**Not presented as a defect.** Session-only authentication is the current
architecture, and the relayed §4.3 SAML/OIDC requirement is unmet rather than
broken. Whether to implement SSO is a platform decision with its own scope; this
dependency exists because **item 1's answer may or may not be allowed to depend
on it**.

Required sub-decisions:

| # | Sub-decision |
|---|---|
| A1 | SAML2 / OIDC position — which, if either, and on what timeline |
| A2 | Whether Add-in auth **may depend on current session auth** given §1.1's `SameSite=Lax` + `HttpOnly` |
| A3 | MFA interaction — whether an Add-in session requires MFA, and how TOTP or recovery codes are presented in a webview |
| A4 | Token / session lifetime for Add-in contexts, against the current 8-hour session |
| A5 | Tenant binding — whether identity carries tenant, or tenant stays a separate assertion (item 2) |
| A6 | Logout and revocation — what revokes an Add-in session, and how quickly it takes effect |

**Owner:** security owner.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## B. Section granularity

**Current fact.** Document versioning is at document level. Section
**addressing** exists via `DocumentLocator` bound to a `DocumentVersion`, with a
`SECTION` locator type and per-locator `extracted_text` (§1.4). Section
**versioning** does not exist.

The relayed §2.7 asks for version control when the same **section** is uploaded
multiple times. An explicit decision is required between:

| # | Option | Consequence |
|---|---|---|
| B1 | **Section-level versioning is needed** | New model, migration and history semantics — significant scope |
| B2 | **Section references are derived locators only** | Uses what exists; "section history" is expressed as locators across document versions |
| B3 | **A new section-version model is required** | Distinct from B1 only if it is to sit beside document versions rather than replace them — the owner must say which |

**Owner:** product owner, with regulatory owner on whether B2 satisfies the
version-control intent.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## C. Read-path audit

**Current fact, stated and not solved.** `DocumentEvent` has **no read, view,
retrieval or download event** (§1.6). `CanViewDocument` authorises reading and
emits nothing.

**Required decision:** which Word operations must create regulated audit events.
Engineering will not choose which reads are regulated.

**Owner:** security owner, with regulatory owner on sufficiency. Feeds item 6.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## D. Content retrieval boundary

Each line requires an explicit answer. **A blank line here blocks item 3.**

| # | Boundary question |
|---|---|
| D1 | Which document statuses may be retrieved (`ACTIVE`, `ARCHIVED`) |
| D2 | Draft vs approved — noting no such state exists on documents today (§1.4) |
| D3 | Quarantined content — `INFECTED`, `QUARANTINED`, `SCAN_FAILED`, `SCANNER_UNAVAILABLE` |
| D4 | Whether `extracted_text` may be exposed, and at what granularity |
| D5 | Whether binary document bytes may be retrieved at all |
| D6 | Exact version selection semantics (with item 4) |
| D7 | Cross-tenant prohibition — stated explicitly, not assumed |
| D8 | Whether content may be cached client-side |
| D9 | Expiry rules for anything cached or issued |

**Owner:** security owner, with regulatory owner on D1–D4.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## E. Insertion provenance

**Required minimum fields for every insertion.** The owner may add to this list;
removing a field requires a stated reason.

| # | Field |
|---|---|
| E1 | Tenant |
| E2 | Document |
| E3 | Exact version |
| E4 | Section / locator |
| E5 | Source status at retrieval time |
| E6 | `retrieved_at` |
| E7 | `inserted_at` |
| E8 | User |
| E9 | Source checksum / version identifier |
| E10 | Audit event reference, if item 6 requires one |

**Owner:** regulatory owner. Feeds items 9 and 10.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

## F. Zero-hallucination acceptance contract

**This document does not define "zero hallucination", and engineering must not.**
The owner defines every line below.

| # | To be defined by the owner |
|---|---|
| F1 | Allowed source corpus |
| F2 | Retrieval-only vs generation |
| F3 | Whether paraphrase is allowed |
| F4 | Whether unsupported text must be blocked |
| F5 | Citation requirements |
| F6 | Expected failure behaviour when a question cannot be answered from the corpus |
| F7 | Measurable acceptance method |
| F8 | Test corpus |
| F9 | Pass / fail criterion |
| F10 | Who signs off |

**Until F7, F9 and F10 exist, the requirement remains unverified and no
conformance claim may be made.**

**Owner:** regulatory owner. Feeds item 13.

| Status | `[ ] DECIDED`  `[ ] PENDING`  `[ ] NOT APPLICABLE` |
|---|---|
| Decision | |
| Owner | |
| Evidence / approval reference | |
| Effective version / date | |
| Implementation consequence | |

---

# 5. Decision matrix

Each of the thirteen items appears exactly once, with its blocking dependencies.

| # | Item | Owner | Blocked by |
|---|---|---|---|
| 1 | Word-compatible authentication flow | Security | A |
| 2 | Tenant-selection behaviour | Product | 1 |
| 3 | Governed content-retrieval API | Security | D |
| 4 | Document / version / section selection semantics | Product | 3, B |
| 5 | Draft vs approved insertion rule | Regulatory | 3 |
| 6 | Audit semantics for query / retrieval / insertion / response | Security | C |
| 7 | Word Desktop vs Word Online support | Product | 1 |
| 8 | Office manifest permission scope | Security | 1, 11 |
| 9 | Provenance attached to inserted content | Regulatory | E |
| 10 | Post-insertion modification expectations | Product | 9 |
| 11 | Add-in distribution / deployment model | Product | — |
| 12 | iPharmaAI as a second delivery target | Product | — |
| 13 | Zero-hallucination definition and verification | Regulatory | F |

**Items 11 and 12 are the only two blocked by nothing**, and can be decided
immediately.

## Engineering handoff criteria

The exact minimum before implementation may begin. A conjunction — every line.

| # | Required |
|---|---|
| 1 | **All 13 decisions completed** — `DECIDED` or `NOT APPLICABLE` with a stated reason. `PENDING` blocks |
| 2 | **SSO dependency resolved** (A) — including whether item 1 may depend on session auth |
| 3 | **Content retrieval boundary approved** (D) — all nine lines |
| 4 | **Insertion provenance contract approved** (E) — the minimum field list |
| 5 | **Audit semantics approved** (item 6 and C) — named operations and recorded fields |
| 6 | **Desktop / Online matrix approved** (item 7) — host, platform, minimum version |
| 7 | **Deployment model approved** (item 11) — named channel and administrator |
| 8 | **Zero-hallucination verification method approved** (F) — at minimum F7, F9, F10 |
| 9 | **Section-granularity decision approved** (B) |
| 10 | **Named accountable roles** — a named person per decision, not a role alone |
| 11 | **Approval evidence** — the approvals themselves, not assertions that they exist |

**Item 3 gates most of the rest.** Until the content-retrieval API question is
answered, items 4, 5, 6 and 9 describe the behaviour of something that may not
exist.

## Engineering rejection criteria

A package meeting any of these is returned rather than interpreted. **Interpreting
an ambiguous contract is how engineering ends up making a product or security
decision it does not own.**

| Rejected | Why |
|---|---|
| **Auth described only as "use SSO"** | Names a family, not a flow. Does not say what happens to `SameSite=Lax`, MFA, lifetime or revocation |
| **Tenant behaviour unspecified** | Tenant is the isolation boundary; an unspecified boundary is a cross-tenant risk |
| **"Latest document" without exact-version semantics** | Ambiguous the moment a version is uploaded mid-session; inserted content becomes unreproducible |
| **Draft/approved rule ambiguous** | Documents carry no approval state today (§1.4), so ambiguity resolves into engineering inventing one |
| **Audit wording says only "log activity"** | Does not name operations, fields or retention. Audit payloads cannot be redacted later |
| **Zero hallucination with no measurable acceptance method** | Cannot be built to, tested, or signed off; and no conformance claim may be made |
| **Desktop / Online support unspecified** | The hosts differ in webview, storage and auth behaviour; "Word" does not pick |
| **Manifest permissions "minimum required" without naming them** | A security boundary in a shipped artifact must be explicit, not inferred |
| **Client caching rules absent** | Content leaving the platform with no expiry rule is an unbounded exposure |
| **Provenance fields incomplete** | Partial provenance on content that has left the platform is a claim that cannot be checked |
| **Deployment says only "Microsoft Office"** | Not a channel. Does not say who administers, reviews or updates it |
| **iPharmaAI scope implied but not decided** | A separate codebase with no shared code; implied scope surfaces late |
| **Approvals asserted without evidence** | "Approved" without the approval is not an approval |

## What this document does not do

It implements nothing. No Office Add-in, no authentication mechanism, no SSO, no
content-retrieval API, no audit event, and no change to CSP, CORS or session
settings. It creates no API semantics and weakens no existing control. It fills
no decision field and records no approval. It makes **no 21 CFR Part 11
compliance claim** and infers no regulatory approval. **"Zero hallucination"
remains undefined and unverified**, and stays that way until an acceptance method
exists.

The absence of SSO is recorded as the current architectural position, **not as a
defect requiring immediate implementation.**

## Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** The codebase declines it explicitly;
   an immutable audit mechanism is not compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
