# Word Add-in / Contextual Drafting — Gap Report

> **Scope:** SOW 2.7 (Word plug-in / contextual drafting), read against REGX as
> it stands, with the adjacent platform requirements §§4.2–4.4.
> **Type:** inspection record. No code, migration, UI, security-configuration,
> API or approval-status change accompanies this document.
> **Inspected at:** `regx-main` `d323084e211f560289226e268b66b0a50698b825`.
> **Status:** **BLOCKED ON PRODUCT / SECURITY CONTRACT.**
> **Companions:** [SOW_SECTION_2_STATUS.md](SOW_SECTION_2_STATUS.md),
> [SECURITY_BASELINE.md](SECURITY_BASELINE.md),
> [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md),
> [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md)

## 1. How to read this report

Three kinds of evidence appear below and they are **not interchangeable**. Each
section states which kind it is.

| Level | What it is | How far it can be trusted |
|---|---|---|
| **1. Primary repository evidence** (§3) | What this codebase actually contains, verified by inspection at the SHA above | Checkable by anyone, by re-reading the cited file and line |
| **2. Relayed SOW requirements** (§4) | What SOW §2.7 and §§4.2–4.4 require, **relayed by the project owner** — see the limitation notice | Requirement intent, pending verification against the primary document |
| **3. Secondary corroboration** (§5) | An earlier status assessment of a different codebase that cites the same SOW | Corroborating only. Never a substitute for the SOW |

The distinction matters because this report's conclusion is that work is
blocked. A blocking conclusion drawn from a misread requirement would be as
costly as building the wrong thing, so the strength of each claim is labelled
rather than levelled up by proximity to the others.

## 2. Summary

| Dimension | Status |
|---|---|
| Functional purpose | **Specified** (relayed) |
| Backend data boundary | **Partly specified** |
| Version-control intent | **Specified** (relayed), with a granularity gap |
| Security / auth / insertion / deployment contract | **Not specified** |
| Architecture | **Separate Office Add-in deliverable** |
| Implementation status | **BLOCKED ON PRODUCT / SECURITY CONTRACT** |

No Office Add-in code exists in this repository or in the legacy codebase, and
none is added by this report.

## 3. Primary repository evidence

Verified at `d323084`. Every claim names a file so it can be re-checked.

### 3.1 There is no Office Add-in, in either codebase

Searched across `backend/`, `frontend/`, `company_site/`, `docs/` and the
compose and workflow definitions, excluding vendored directories:

| Marker | Occurrences |
|---|---|
| `office.js`, `Office Add-in`, `taskpane`, `manifest.xml`, `Word.run`, `Office.context`, `insertText`, `insertHtml`, `insertFileFromBase64`, `Microsoft 365` | **0 each** |

The legacy `origin/main` branch returns **0** for `Office.context`, `Word.run`,
`office.js` and `taskpane`.

Two search results are **not** Add-in code and are recorded so they are not
mistaken for it later:

* **`addin` — 309 files.** A false positive: the substring occurs inside
  `p·addin·g`. Confirmed by extracting the matched text.
* **`WordprocessingML` / `Open XML` — 5 files.** `documents/validators.py` and
  its tests: DOCX **format validation** (content-type sniffing, macro
  detection). Generating or validating a `.docx` is not a Word Add-in.

Also distinguished, per the classification this inspection was asked to make:
the 59 `company_site/templates/RATools/*.html` files are **document
generators**; `company_site/static/documents/*.doc` is a **downloadable
template**. Neither is an Add-in.

### 3.2 Authentication

`backend/regx/settings/base.py:210` — `DEFAULT_AUTHENTICATION_CLASSES` contains
exactly one entry, `rest_framework.authentication.SessionAuthentication`. The
backend contains **no** `TokenAuthentication`, no SimpleJWT, no
`JWTAuthentication`, and no OAuth. Auth endpoints are `csrf/`, `register/`,
`login/`, `logout/`, `me/`. MFA exists (`identity/mfa_urls.py`,
[MFA.md](MFA.md)).

**No SAML, OIDC or SSO implementation exists anywhere in the backend.**

### 3.3 Current architectural constraints

These are **statements of the deployed security posture**, recorded because any
Add-in design must account for them. They are **not** presented as defects, and
this report makes **no recommendation to change any of them**.

* **`SESSION_COOKIE_SAMESITE = "Lax"`** — `settings/base.py:170`, restated at
  `settings/production.py:18` with the comment *"Inherited from base; explicit
  here for audit"*. A `Lax` cookie is not sent on cross-site subrequests.
* **`frame-ancestors 'none'`** — [SECURITY_BASELINE.md](SECURITY_BASELINE.md)
  line 19: *"REGX pages cannot be embedded in iframes."*
* **`CORS_ALLOWED_ORIGINS`** is an explicit allowlist with
  `CORS_ALLOW_ALL_ORIGINS=False`; `CORS_ALLOW_CREDENTIALS = True`.

An Office Add-in taskpane runs in an embedded browser — WebView2 on Windows
desktop, a WebView on Mac, an iframe in Word Online — and each of those is a
different browsing context from the user's own browser. How an Add-in would
authenticate against the posture above is a **product and security decision
that has not been made**, and it is recorded here as an open contract item
(§6), not as a change to propose.

### 3.4 Documents: what is and is not reachable

`documents/urls.py` exposes list/create, detail, version list/create, version
detail, version status, locators, archive and restore.

**No governed API currently exposes document bytes or approved insertable
content to an external Word client.**

Storage backends implement `retrieve()` and `presigned_url()`
(`documents/storage.py`), but **no view exposes either**. Storage-level
capability does not establish that external exposure is intended; whether such
an endpoint should exist is a product and security decision, recorded in §6.

The only endpoints in the platform that return file bytes are the two governed
exports: `iig-checklists/executions/<id>/export/` (canonical, checksummed,
`PERM_EXPORT_CHECKLIST`) and `submission-packages/<id>/export/` (ZIP). Both
emit whole artifacts, not insertable fragments.

**`DocumentLocator`** (`documents/models.py:198`) is the one structure that
holds insertable-shaped text today: per-`page`/`section`/`paragraph`/`table`
reference points with `extracted_text` (`models.py:210`), populated by
`documents/tasks.py:302` and capped at 10,000 characters. It is served behind
`CanViewDocument` and refuses `QUARANTINED` content. Whether it is the right
source for drafting insertion is undecided; it is recorded as the existing
capability closest to the requirement.

### 3.5 Documents have no approval state

`DocumentVersion` carries `scan_status` and `processing_status`. Both are
technical. **Neither is a regulatory approval state, and no other field on the
model is.**

Approval exists elsewhere: `workflows.WorkflowItem.State.APPROVED`, and
`iig_checklist` execution statuses. `submission_packages.PackageStatus` says in
its own docstring *"Deliberately NOT an approval flow."*

Consequently the question *"may this content be inserted as approved?"* has **no
answer at the document level today**, because the distinction does not exist
there.

### 3.6 Audit

`AuditEvent` rows are append-only, enforced at two layers: an ORM guard
(`save()` raises on update, `delete()` always raises) and two PostgreSQL
triggers ([AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)).

The `documents` domain declares **16** event types, covering upload, scan,
processing, version creation, document creation, archive, restore and duplicate
detection. **None of them records a read, view, retrieval or download.**

The platform's only read-path audit event is
`iig_checklist.gap_analysis.generated`, which is specific to gap analysis.

So an insertion of document content into Word would, with today's events, leave
**no audit trail**.

### 3.7 Tenant isolation

`tenancy/middleware.py` resolves the tenant from the `X-Tenant-Slug` request
header. Isolation is enforced per-app in the service and view layers and is
covered by tests. Because it is header-based rather than cookie-based, an
external client can supply it — but **which tenant an Add-in should select, and
how, is unspecified** (§6).

### 3.8 Backend data that a drafting feature would draw on

* **Deficiency corpus — exists and is governed.** `deficiencies/models.py`:
  `DeficiencyRecord` with corpora `ANDA` ("ANDA Deficiency Roadmap") and
  `MAJOR_CR` ("Major CR Roadmap"), a PROTECT foreign key to
  `fda_data.FDADataSourceRelease` for provenance, an `import_deficiencies`
  management command, and list/facets endpoints behind `CanViewDeficiencies`.
* **Checklist gap analysis — exists and is governed.** Immutable snapshots with
  a canonical input hash, exact checklist-version binding and factual counts
  (see [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) for the related
  calculation position). **Scoped carefully:** this is a *reusable backend
  capability*. It does **not** establish that SOW 2.7's Word-contextual gap
  analysis and resolution requirement is fulfilled — the Word-contextual
  application and the resolution workflow remain **unimplemented**.
* **Document version control — exists, at document granularity.**
  `DocumentVersion.version_number`, SHA-256 duplicate cross-referencing within a
  tenant, and a `document.duplicate.detected` audit event.
* **Checklist content — built but unapproved.** The engine exists; the
  production regulatory content approval register stands at **0 of 20
  approved**.

## 4. Relayed SOW requirements

> **Requirement source limitation:** The authoritative SOW PDF was not available
> to the author of this report. Requirements attributed to SOW §2.7 and
> §§4.2–4.4 below were relayed by the project owner on 2026-09-16 after
> reviewing pages 7–9 of
> `SOW - Praverse (Pratham) iCretegy_April 22, 2026.pdf`. They shall be verified
> against the primary document when it becomes available.

When the primary document is available, §4 should be replaced with direct
citations and a narrow source-verification pass run against it. That pass need
not reopen the architecture analysis in §3 or §6 unless the wording materially
changes it.

### 4.1 SOW §2.7 — as relayed

* Word integration **comparable to ISI Writer / Copilot in MS Office**.
* **Contextual, section-wise drafting guidance.**
* **Predictive deficiency flagging.**
* **Gap analysis and resolution based only on backend data.**
* **Reference-material suggestions.**
* **"Zero hallucination."**
* **Version control when the same section is uploaded multiple times.**
* **iCretegy to provide** ANDA/DMF checklists, a deficiency database, FDA
  guidance and similar material as the backend source for those outcomes.
* The **same capability to be integrated into iPharmaAI** for client use.

### 4.2 Adjacent platform requirements — as relayed

* **§4.2** — hard tenant isolation.
* **§4.3** — SSO via **SAML/OIDC**, and granular RBAC.
* **§4.4** — an **immutable audit log for every query, response, export, user
  action and admin change**.

### 4.3 Delta against §3

| Relayed requirement | Position at `d323084` |
|---|---|
| Word integration comparable to ISI Writer / Copilot | Nothing exists. Separate Add-in deliverable |
| Contextual section-wise drafting | Not implemented; depends on the unresolved content-retrieval contract |
| Predictive deficiency flagging | **Backend corpus exists and is governed.** Flagging logic does not exist |
| Gap analysis / resolution from backend data only | **Reusable backend capability exists.** Word-contextual application and resolution workflow **unimplemented** |
| Reference-material suggestions | `fda_data` exists; no suggestion logic |
| Zero hallucination | See §4.4 below |
| Version control on repeated **section** upload | Versioning exists at **document** granularity. **Granularity gap** |
| iCretegy-provided checklists / deficiency DB / guidance | Deficiency corpus imported. Checklist content **unapproved (0 of 20)** |
| Equivalent capability in **iPharmaAI** | A **second delivery target**, not previously recorded in REGX planning |
| §4.2 tenant isolation | **Met** |
| §4.3 SAML/OIDC SSO | **Not met.** No SSO implementation exists |
| §4.3 granular RBAC | **Met** — capability codenames per app, role-mapped |
| §4.4 immutable audit | **Mechanism met; coverage not.** No read/query audit for documents (§3.6) |

### 4.4 Zero hallucination

**Zero-hallucination requirement: not exercised and not verified.** REGX
currently has no AI generation capability in the backend, so there is no active
generative path to evaluate against this requirement. The SOW does not define a
verification method or acceptance criterion for "zero hallucination."

## 5. Secondary corroboration

An earlier assessment, `SOW-TECHNICAL-TOOLS-STATUS.md`, measured the legacy
iPharmaAI monolith against the **same** SOW section and pages. It is cited here
**only as a secondary record**. It is not the SOW, it does not stand in for the
SOW, and its status judgements describe a different codebase.

It corroborates four points:

1. The item title is rendered **"Word plug-in (contextual drafting)"** — fuller
   than this repository's own summary, which renders it "Word plug-in".
2. It records an Office Add-in as **"a separate deliverable, not a change inside
   this repo."**
3. It records **predictive deficiency flagging as spanning 2.7 and 2.8**, and
   notes it as *"feasibility-TBD in the SOW"*.
4. It cross-references **checklist version control to 2.7 and 2.10**.

Its other blocker for 2.7 — a hardcoded OpenAI key — was legacy-specific and
does not apply to REGX, which contains no OpenAI usage in the backend.

## 6. Open contract items

None of these is an engineering task today. Each is a product, security or
regulatory decision that must be made **before** an Add-in can be specified.

| # | Open item |
|---|---|
| 1 | **Word-compatible authentication flow** — how an Add-in authenticates, given §3.2 and §3.3, and how it relates to the SAML/OIDC SSO §4.3 requires |
| 2 | **Exact tenant-selection behaviour** from the Add-in |
| 3 | **Governed content-retrieval API** — whether one should exist, and what it may expose |
| 4 | **Exact document / version / section selection semantics** |
| 5 | **Draft vs approved insertion rule** — currently undecidable at document level (§3.5) |
| 6 | **Audit semantics** for query, retrieval, insertion and response |
| 7 | **Word Desktop vs Word Online support** |
| 8 | **Office manifest permission scope** |
| 9 | **Provenance attached to inserted content** |
| 10 | **Post-insertion modification expectations** |
| 11 | **Add-in distribution / deployment model** |
| 12 | **iPharmaAI as a second delivery target** |
| 13 | **Definition and verification method for "zero hallucination"** |

## 7. Regulatory boundaries for any future implementation

Recorded now so they are not rediscovered later. An Add-in must never:

* represent inserted content as approved unless the source record is actually
  approved;
* fabricate sign-offs;
* silently promote drafts;
* bypass existing workflow permissions;
* mutate governed document versions;
* claim 21 CFR Part 11 compliance merely because an audit trail exists.

The codebase already declines the Part 11 claim deliberately; nothing in this
report changes that, and no Part 11 claim is made here.

## 8. Conclusion

**BLOCKED ON PRODUCT / SECURITY CONTRACT.**

Functional intent is specified. The implementation contract is not. The
thirteen items in §6 are the gap, and none of them is closed by writing code.

Nothing in this report authorises building an Office Add-in, adding an
authentication mechanism, exposing a content endpoint, or altering the CSP,
cookie or CORS posture described in §3.3.
