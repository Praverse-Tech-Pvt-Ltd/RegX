# REGX — External Blocker Readiness

> **What this is:** a decision and input checklist. For each remaining blocker it
> records what already exists, the exact decision or specification that is
> missing, who must supply it, and what engineering may begin once it arrives.
> **What this is not:** a phase, a readiness claim, a validation record or an
> approval. **Nothing here approves, activates or authorises anything.**
> **Verified at** `regx-main` `eb6aa76621b6859b7665793baa73214629c1f5a4`.
> Every blocker below was re-checked against code at this SHA, not assumed to
> survive from the report that first recorded it.
> **Companions:** [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md),
> [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md),
> [WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md),
> [STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md),
> [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md)

## 0. How to read this

**Engineering gap vs owner gap.** These are not the same kind of problem and
cannot be closed the same way.

| Class | Meaning | Closed by |
|---|---|---|
| **ENGINEERING GAP** | The decision exists; the code does not | Engineering capacity |
| **OWNER / GOVERNANCE GAP** | The code is not the obstacle; a decision an accountable non-engineering owner must make is missing | That owner deciding |

**Every one of the six items below is an owner/governance gap.** None is blocked
on engineering capacity, and none can be unblocked by writing code. That is the
single most important fact in this document: adding engineering effort to any of
these six changes nothing.

**On naming owners.** The repository names *roles*, never individuals. Where
this document says "a named regulatory authority" or "an accountable business or
data owner", that is the repository's own phrasing for a role that **is not
currently filled by any named person in any tracked document**. Identifying the
person is itself part of what is missing.

## 1. Blocker summary

| # | Item | Class | Blocked on | Status |
|---|---|---|---|---|
| 1 | **P9** — SOW 2.3 HTML calculators | Owner | Formula specification **and** separately approved engineering scope | BLOCKED |
| 2 | **P10** — Word Add-in | Owner | 13 product/security contract decisions | BLOCKED |
| 3 | **P11** — Stability / impurity assistant | Owner | Feasibility determination and product specification | BLOCKED |
| 4 | **P13c** — Legacy RATools disposition | Owner | Accountable business/data owner decision | BLOCKED |
| 5 | **Approval Register Items 13 / 14** | Owner | Regulatory authority (calculation bindings) | PENDING |
| 6 | **Production regulatory content gate** | Owner | Regulatory authority (all 20 items + sign-off) | OPEN — **0 of 20** |

Items 5 and 6 are related but **not interchangeable** — see §6.3.

---

## 2. P9 — SOW 2.3 HTML calculators

**Status: BLOCKED ON CLIENT INPUT.** Two separate approvals are required and
neither substitutes for the other.

### What already exists

The **SOW 2.2 calculation engine** exists, is specified and is tested — a
different deliverable that is often mistaken for progress on 2.3. Verified at
this SHA, `CALCULATION_BINDING_REGISTRY` holds **exactly six** identifiers:
`percentage_w_w`, `daily_exposure`, `percentage_of_iid_potency`,
`difference_from_iid_potency`, `percentage_of_iid_mde`,
`difference_from_iid_mde`. It is `Decimal`-only, versioned, fail-closed and
provenance-bound.

**For SOW 2.3 itself: nothing exists.** No dissolution, impurity or
stability/shelf-life calculator, and no approved formula specification for one,
in this repository or the legacy codebase. Re-verified at this SHA: the only
first-party matches for `dissolution` / `shelf_life` are **two test fixture
strings** (`backend/deficiencies/tests/conftest.py:81`,
`backend/templates_registry/tests/conftest.py:148`) — deficiency and question
text, not computation. `ICH Q3A` / `Q3B` / `Q1A` threshold logic: **zero
occurrences**. This is not a port; there is nothing to port.

### Exact missing decision

1. **An approved formula specification per calculator** (dissolution, impurity,
   stability/shelf-life), and
2. **Separately approved engineering scope** to build outside the six-formula
   registry. `SCOPE-OUT-18` caps it: *"New calculation formulas beyond the six
   approved functions | Never in 4D."*

### Who must provide it

Formula specification — **client / regulatory content owner**. Engineering scope
— **the scope approval authority that set `SCOPE-OUT-18`**. Two different
decisions, two different owners.

### Minimum information required to unblock engineering

Per calculator, all eleven. **A blank item blocks that calculator; partial input
does not authorise a partial build.**

| # | Required | # | Required |
|---|---|---|---|
| 1 | Calculator name | 7 | Acceptance / interpretation rules |
| 2 | Exact formula, written unambiguously | 8 | Source document |
| 3 | Variable definitions and value origin | 9 | Source version and date |
| 4 | Units per variable and for the result | 10 | Named regulatory / client owner |
| 5 | Rounding rules — precision, direction, step | 11 | Approval evidence, not an assertion that one exists |
| 6 | Edge and error behaviour, and what the user sees | | |

Items 6 and 7 are not optional detail: a calculator without defined edge
behaviour will either guess or emit a misleading number.

### What engineering can start immediately once supplied

Once **both** approvals exist: implement each calculator against the same
properties the existing engine already proves — `Decimal`-only arithmetic,
explicit formula and binding versions, fail-closed blocked statuses with reason
codes, recorded inputs — plus its UI and tests. The existing engine is the
working reference for how a governed calculation behaves here.

### What must NOT be inferred or invented

- **No formula may be derived from regulatory guidance.** Reading a threshold
  out of ICH Q3A/Q3B/Q1A and encoding it is engineering choosing a regulatory
  parameter.
- No formula reconstructed from a legacy spreadsheet, or inverted from example
  outputs.
- **No seventh calculation added to `CALCULATION_BINDING_REGISTRY`** to satisfy
  content, however good the formula is.
- Formula specification alone does not authorise a build; scope approval alone
  does not supply a formula.

### Evidence

[CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) §3 (searches), §3.5
(eleven inputs), §3.6 (`SCOPE-OUT-18`) · `backend/iig_checklist/calculation_registry.py:218`

---

## 3. P10 — Word Add-in

**Status: BLOCKED ON PRODUCT / SECURITY CONTRACT.** Functional intent is
specified; the implementation contract is not.

### What already exists

Backend capabilities an Add-in would draw on, all governed: the **deficiency
corpus** (`DeficiencyRecord`, corpora `ANDA` and `MAJOR_CR`, provenance FK to
`FDADataSourceRelease`), **gap analysis** as immutable snapshots, **document
version control** at document granularity, **tenant isolation** (met), and
**granular RBAC** (met).

Verified absent at this SHA: **no Office Add-in artifact** (no `manifest.xml`,
no `office.js` usage) and **no SSO implementation** — zero first-party matches
for SAML, OIDC or OpenID in `backend/`. Authentication is `SessionAuthentication`
only.

**A read-path audit gap is confirmed in code.** `DocumentEvent` in
`backend/documents/audit_events.py` declares **16** event types at this SHA,
covering upload, scan, processing, version creation, document creation, archive,
restore and duplicate detection. **None records a read, view, retrieval or
download** — confirmed by enumerating the constants, not by a search returning
nothing. An insertion of document content into Word would today leave no audit
trail.

### Exact missing decision

**Thirteen contract items**, none of them an engineering task:

| # | Open item | # | Open item |
|---|---|---|---|
| 1 | Word-compatible authentication flow | 8 | Office manifest permission scope |
| 2 | Exact tenant-selection behaviour | 9 | Provenance attached to inserted content |
| 3 | Governed content-retrieval API — whether one should exist, and what it may expose | 10 | Post-insertion modification expectations |
| 4 | Document / version / section selection semantics | 11 | Add-in distribution / deployment model |
| 5 | Draft vs approved insertion rule | 12 | iPharmaAI as a second delivery target |
| 6 | Audit semantics for query, retrieval, insertion, response | 13 | Definition and verification method for "zero hallucination" |
| 7 | Word Desktop vs Word Online support | | |

### Who must provide it

**Product owner** (items 2, 4, 7, 10, 11, 12), **security owner** (1, 3, 6, 8),
**regulatory owner** (5, 9, 13). Item 1 also depends on the SAML/OIDC SSO
position, which is a platform-level decision rather than an Add-in one.

### Minimum information required to unblock engineering

A written decision on each of the thirteen, plus: a resolution of **SOW §4.3
SAML/OIDC**, since an Add-in authentication design that assumes session cookies
may be invalidated by it; and a **section-granularity decision** for version
control, because versioning exists at document granularity and the relayed
requirement is per-section.

**Requirement-source limitation.** SOW §2.7 and §§4.2–4.4 requirements are
recorded as **relayed by the project owner on 2026-09-16** from pages 7–9 of the
SOW PDF, which was not available to the report's author. They must be verified
against the primary document when it becomes available.

### What engineering can start immediately once supplied

Nothing before item 3 is decided, because every other item depends on whether a
governed content-retrieval API may exist at all. **After** items 1, 3 and 6:
specify and build that API with read-path audit events, then the Add-in against
it. Items 5 and 9 must be settled before any insertion path is built, not after.

### What must NOT be inferred or invented

An Add-in must never represent inserted content as approved unless the source
record is approved; fabricate sign-offs; silently promote drafts; bypass
workflow permissions; mutate governed document versions; or claim 21 CFR Part 11
compliance because an audit trail exists. Additionally: **do not weaken CSP,
CORS or session settings to accommodate an Add-in** — those are architectural
constraints, not obstacles to route around.

### Evidence

[WORD_ADDIN_GAP_REPORT.md](WORD_ADDIN_GAP_REPORT.md) §3.6 (read audit), §4
(relayed requirements and source limitation), §6 (thirteen items), §7
(boundaries) · `backend/documents/audit_events.py` (16 event constants)

---

## 4. P11 — Stability / impurity assistant

**Status: BLOCKED** — feasibility and product specification unresolved.

### What already exists

**No implementation, and no AI generation capability in the backend at all** —
re-verified at this SHA with zero first-party matches for OpenAI, Anthropic or
LangChain in `backend/`.

The **deficiency corpus exists and is governed**, and contains FDA wording about
impurities, assays and degradants. It is **source data, not tooling**;
retrieving a precedent is not assessing a stability or impurity question, and
its existence is not progress on SOW 2.9.

### Exact missing decision

1. **A feasibility determination.** The SOW itself is recorded as marking 2.9
   *feasibility-TBD* — so the requirement may not be buildable as written, and
   that question is open, not assumed closed.
2. **A functional specification**, and with it: an accuracy and verification
   standard, a data boundary, and a **regulatory position on what an assistant
   may assert**.

### Who must provide it

Feasibility — **client / SOW owner**. Specification — **product owner**.
Assertion boundary and accuracy standard — **regulatory owner**.

### Minimum information required to unblock engineering

Feasibility resolved to yes/no with reasoning; then what the assistant may and
may not state; what data it may read; how accuracy is measured and what
threshold is acceptable; and what a user sees when it cannot answer. **An
accuracy standard with no defined measurement method does not unblock anything.**

### What engineering can start immediately once supplied

Nothing until feasibility is determined. After a yes plus a specification:
retrieval over the existing governed corpus with provenance, and the fail-closed
"cannot answer" path — deliberately before any generative behaviour, since the
retrieval and boundary layers are what make the rest assessable.

### What must NOT be inferred or invented

No AI work is authorised by any current document. Do not treat the deficiency
corpus's existence as partial delivery of 2.9. Do not infer an accuracy standard.
**Do not build a generative path before the assertion boundary is decided** —
that boundary determines the design, not the reverse.

### Evidence

[STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md)
§A.1–A.4

### 4.1 The related Part 11 retention question — NOT DETERMINED

`percentage_w_w` and `daily_exposure` sit outside the governed
`AssessmentSnapshot` path; their `CalculationOutcome` is updated in place, and
the audit event records identifiers and status rather than a historical copy of
prior input/output values. **The 4D-3 engineering specification permits this
design.** Four distinctions are held apart deliberately and must survive any
summary:

1. the implementation **conforms** to 4D-3;
2. **no engineering defect is established**;
3. the SOW 2.9 regulatory expectation *may* be broader than the engineering
   specification;
4. **engineering must not decide that Part 11 question itself.**

This is a regulatory/governance determination. It is **not** a defect, a CAPA or
a validation deviation.

---

## 5. P13c — Legacy RATools disposition

**Status: BLOCKED on an accountable business or data owner.**
**Default until then: retain-and-freeze.**

### What already exists

A **seven-level approval flow stored as strings** across 7 models
(`approved_by_checkers_level_1..7`, `CharField` holding `'False'`/`'True'`/
`'Done'`), re-verified at this SHA — **49 occurrences** in
`company_site/RATools/models.py`. **Signature images** (`ImageField`,
`upload_to='signatures/'`) stored alongside regulatory applicant details. Five
SQLite database files in `company_site/`.

**No audit infrastructure exists anywhere in `company_site`** — re-verified at
this SHA: no `AuditLog` class and no `log_event` function.

### Exact missing decision

**The authority status of the legacy approval states and signature images.** The
codebase cannot establish whether they remain authoritative records for any
client or process. That is a business and data question, not an engineering one.

### Who must provide it

**An accountable business or data owner.** No such owner is named in any tracked
document.

### Minimum information required to unblock engineering

A disposition decision selecting one of: **retain-and-freeze**, **migrate with
provenance**, **archive externally**, or **decommission after a documented
retention decision** — plus the retention period and the record of who decided.

### What engineering can start immediately once supplied

Nothing before the decision. After it, the work is determined by which option
was chosen — migration tooling with provenance, an export path, or a documented
decommission. **No code shall be written for P13c until that decision exists.**

### What must NOT be inferred or invented

- **No synthetic or reconstructed audit event** for any historical approval
  change, signature upload or checklist transition. An audit trail invented
  after the fact is worse than an acknowledged absence, because it asserts a
  record that was never made.
- The absence of audit coverage is **a documented governance exposure**. It is
  **not** evidence that historical approvals are invalid.
- Records must not be deleted, rewritten or silently replaced by REGX workflow
  records.
- **Superseded is not removable.** REGX having a newer equivalent is not a reason
  to remove a legacy surface.

### Evidence

[LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) §4.1–4.4,
§5, §7 · `company_site/RATools/models.py`

---

## 6. Approval Register Items 13 / 14 and the content gate

Items 5 and 6 of this checklist are treated together because their relationship
is the thing most easily got wrong.

### 6.1 Item 13 — `SYSTEM_CALCULATED` bindings

**Status: PENDING. Interpretation risk: HIGH** — *"the wrong calculation
produces a wrong regulated number."*

**Exists:** the engine, its six identifiers, binding validation (binding required
for `system_calculated` and forbidden otherwise), and activation validation.

**Missing:** *which calculation applies to which question, and the regulatory
reason.* **Citation required: yes.**

**Owner:** JOINT regulatory + engineering — neither side can settle it alone.

**Minimum to unblock:** for every calculated question, the bound identifier
(from the six) plus the regulatory reason and citation. **Completion criterion:**
every calculated question bound to an approved identifier.

**Must not be invented:** no binding chosen by engineering on plausibility; **no
seventh calculation** added to satisfy a requirement — that is separate approved
engineering scope.

### 6.2 Item 14 — Calculation dependencies / ordering

**Status: PENDING, blocked on 12–13. Interpretation risk: LOW** — derived, not
authored.

**Exists:** dependencies are **registry-fixed**, and `build_graph()` validates
for cycles, depth ≤ 5 and nodes ≤ 10.

**Missing:** nothing authored. It unblocks mechanically once 12 and 13 are
approved.

**Engineering can start immediately once 13 is approved:** run the derivation and
graph validation for every `INCLUDE`d definition and record the output. This is
the one item on this page that is genuinely mechanical.

### 6.3 The production regulatory content gate

> **PRODUCTION REGULATORY CONTENT GATE: OPEN. 0 of 20 approved.**

Re-verified at this SHA: **20 items PENDING, 0 APPROVED.**

**Items 13 and 14 are two of the twenty — necessary, not sufficient.** Approving
both leaves the gate open at 2 of 20. The gate closes only when all twenty are
approved **and Item 20, formal sign-off, is signed.**

**No production regulatory checklist content may be authored, loaded or activated
until Item 20 is signed.**

**Who:** a **named regulatory authority**. None is named in any tracked document.

**The count changes only when a named regulatory authority supplies a real
approval. It is not advanced by document completeness, engineering readiness or
milestone progress** — and nothing in this document advances it.

**One constraint to read before approving Items 11 or 12:**
[MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md) **OQ-8** — which `AssessmentSnapshot` governs
execution-level `iid.*` values is not settled by any approved specification, so a
rule reading `iid.*` currently evaluates to `review_required` and an FDA-derived
binding records `source_unavailable`.

### Evidence

[MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md) §1
(ownership classes), Items 13 and 14, §4 (gate status) ·
[MILESTONE_4D_4_CONTENT_APPROVAL.md](MILESTONE_4D_4_CONTENT_APPROVAL.md)
(`4D4-DEC-001`, gate origin)

---

## 7. Standing non-claims — preserved unchanged

These are restated, not weakened, and must not be softened in any summary of
this document.

1. **No 21 CFR Part 11 compliance claim.** Declined explicitly in
   `backend/workflows/models.py`, [DOSSIER_BLUEPRINTS.md](DOSSIER_BLUEPRINTS.md)
   and [DOSSIER_UPGRADES.md](DOSSIER_UPGRADES.md) — verified present at this
   SHA. An immutable audit mechanism is not compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source, and the 279 calculation tests are engineering
   evidence, not validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing. They determine no regulatory status,
   and P11 leaves Part 11 sufficiency **NOT DETERMINED**.

## 8. What this document does not do

It approves nothing and activates nothing. It does not advance the gate count,
create a phase, name an owner the repository does not name, determine any
regulatory position, or authorise a formula, an Add-in, an AI capability or a
RATools change. It records what is missing and who must supply it — and where a
report says a question is **NOT DETERMINED**, this document leaves it that way.
