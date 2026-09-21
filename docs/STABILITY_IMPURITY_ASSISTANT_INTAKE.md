# SOW 2.9 — Stability / Impurity Assistant: Feasibility and Specification Intake

> **What this is:** a blank two-gate decision form. **Gate 1** asks whether the
> assistant is feasible at all. **Gate 2** defines the implementation contract,
> and becomes implementation-authorising **only if Gate 1 is formally FEASIBLE
> and Gate 2 is authorised.**
> **What this is not:** an implementation, a design, a recommendation or an
> approval. **No decision field below is pre-filled, no model or provider is
> selected, no accuracy target is proposed, and no stability or impurity guidance
> is interpreted into product logic.**
> **Verified at** `regx-main` `0c7c2bb447025117af602e22ba4f70fd276798a8`. Every
> platform fact in §2 was read from code at this SHA.
> **Companions:**
> [STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [P0_P14_HANDOFF.md](P0_P14_HANDOFF.md),
> [FDA_DATA_GOVERNANCE.md](FDA_DATA_GOVERNANCE.md),
> [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md), [TENANCY.md](TENANCY.md)

> ## ⚠ Two gates, in order
>
> ### GATE 1 — Is this feasible at all? **FEASIBLE / NOT FEASIBLE / DEFERRED**
> ### GATE 2 — Only if Gate 1 is FEASIBLE **and** Gate 2 is authorised
>
> **Nothing in Gate 2 authorises implementation while Gate 1 is unanswered.**
> Gate 2 may be drafted in parallel, but a completed Gate 2 with an unanswered
> Gate 1 is not authorisation — it is a proposal for something not yet agreed to
> be feasible.

## 1. Why feasibility comes first

SOW 2.9 is recorded as **feasibility-TBD in the SOW itself**
([STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md)
§A.2, as secondary corroboration). So the requirement may not be buildable as
written, and that question is **open, not assumed closed**.

Treating it as settled would create AI scope by assumption. This document does
not do that: Gate 1 exists precisely so "should this exist?" is answered by the
people who own it, before anyone specifies what it does.

**Source retrieval and generation are different products** and are kept apart
throughout. A system that finds and shows you an approved source is not the same
system as one that composes an answer, and they carry different regulatory
weight. Gate 1 item 2 and Gate 2 items A–C keep that distinction explicit.

> **Requirement-source limitation.** The authoritative SOW PDF was not available
> to the gap report's author. SOW 2.9 content is **secondary corroboration
> relayed via a legacy status record**, and must be verified against the primary
> document when available. A Gate 1 decision made against a relayed requirement
> should say so in its evidence field.

## 2. Platform facts, read from code at this SHA

Facts, not constraints on your decision. A decision may require changing one;
that becomes a scoped engineering consequence to record in the item.

### 2.1 AI capability

| Fact | Value |
|---|---|
| Generative AI capability in the backend | **None.** No provider SDK, no client, no generation path |
| Provider/framework references | **2 matches across 550 first-party `.py` files — both comments, no code** (positive control: 345 files match `django`) |
| Embeddings / vector search | **None.** Zero matches for `pgvector`, `embedding`, `faiss`, `vector_store`, `cosine_similarity` |
| Assistant / chat / prompt / completion model | **None in production code** |
| Existing free-text search | Plain database `icontains`, no ranking (`inspections/views.py:138`) |

The legacy LLM query-expansion was **deliberately not reproduced**
(`inspections/views.py:116`): it made a paid API call on every keystroke and
silently matched nothing on failure. That is a recorded design position, not an
oversight.

### 2.2 AI-derived content already present — read this before answering §5 and §6

**Two distinct models hold AI-derived summary content, and they differ in how it
gets there.** Both are read behind `CanViewInspections`.

| | `Form483Observation.summary` | `WarningLetter.summary` |
|---|---|---|
| Evidence it is AI-derived | Model comment: *"LLM-generated abstract, populated by a separate pipeline"* (`models.py:84`) | Populated from a source column named **`ai_summary`** |
| In-repo write path | **None.** No construction or assignment anywhere in this repository | **Yes** — `import_inspections.py:155`, `summary=_text(row["ai_summary"])` |
| Ingestion shape | External pipeline, outside this codebase | First-party management command; full `delete()` then `bulk_create` |
| Exposed via | `Form483ObservationSerializer` (`serializers.py:13`) | `WarningLetterSerializer` (`serializers.py:76`) |
| Searched at | `views.py:138` — `Q(content__icontains) \| Q(summary__icontains)` | `views.py:171` — `Q(body__icontains) \| Q(summary__icontains)` |
| Provenance stored | **None** — no model, prompt, version, timestamp, review status or support state | **None** — the same |

**Neither model generates anything, and this does not contradict "no AI
generation capability in the backend"** — a field is not a capability, and no
code here produces the text. What it does establish is that **AI-derived content
of unrecorded provenance is already readable and searchable through the governed
API today**, and that for `WarningLetter` it enters through a **first-party
import path in this repository**, not only an external one.

**Nothing here is a defect, a CAPA or a validation deviation**, and none of it is
evidence that an assistant capability exists or that this content is an approved
source. It is recorded solely because the data-boundary decision (§1.5) must rule
on whether such content may ever ground assistant output.

Neither [STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md](STABILITY_IMPURITY_AND_CALCULATION_AUDIT_GAP_REPORT.md)
nor [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md) records this.
It is raised here because Gate 1 §5 asks which sources are allowed, and **both
are already in the read path whether or not the assistant is ever built.**

### 2.3 Deficiency corpus

| Fact | Value |
|---|---|
| Model | `DeficiencyRecord`, corpora `ANDA` and `MAJOR_CR` |
| Provenance | `source_release` FK, `on_delete=PROTECT`, to `FDADataSourceRelease` |
| Tenancy | **Deliberately not tenant-scoped.** Published FDA reference material; every tenant reads the same corpus and no tenant may own or edit a record |
| Access | List and facets endpoints behind `CanViewDeficiencies` |

> **The corpus is shared, not tenant-owned.** Any tenant-isolation answer in
> Gate 2 §B must say how a shared reference corpus and tenant-scoped content are
> treated differently, because the usual "filter by tenant" rule does not apply
> to it.

It contains FDA wording about impurities, assays and degradants. **It is source
data, not tooling**, and its existence is not progress on SOW 2.9.

### 2.4 External-source provenance architecture — the existing governed pattern

`FDADataSourceRelease` (`fda_data/models.py:60`):

| Fact | Value |
|---|---|
| Statuses | `registered` · `staged` · `validated` · `under_review` · `approved` · `active` · `superseded` · `rejected` |
| Immutability | Content and provenance fields are **immutable** once `APPROVED`, `ACTIVE`, `SUPERSEDED` or `REJECTED`; only status, `superseded_by_release` and `updated_at` may change |
| Integrity | `source_checksum_sha256` over the exact supplied bytes, plus recorded size |
| Supersession | A new release is a **new row**; releases are never replaced in place |
| Actor record | `imported_by`, `approved_by`, `activated_by` |

**This is the platform's existing answer to "how is an external source governed",
and it already provides most of what a provenance contract would need.** Gate 1
§6 and Gate 2 §B should be answered against it rather than inventing a parallel
scheme.

### 2.5 Audit

Centralized append-only `AuditEvent`, immutable at two layers — ORM guard plus
two PostgreSQL triggers ([AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)).
**13 audit domains** exist (`documents`, `fda_data`, `workflows`,
`iig_checklist`, `templates_registry` and others). **There is no assistant, AI,
query or retrieval audit domain.**

### 2.6 Tenancy and access

Tenant resolved from the `X-Tenant-Slug` header (`tenancy/middleware.py:19`),
isolation enforced per-app and covered by tests. Capability-based RBAC per app —
`CanViewInspections`, `CanViewDeficiencies`, `CanViewDocument` and others.

---

# GATE 1 — FEASIBILITY DETERMINATION

**Nothing in Gate 2 becomes implementation-authorising unless Gate 1 item 10 is
formally FEASIBLE and Gate 2 is authorised.**

## 1.1 Is the assistant required at all?

| | |
|---|---|
| **Decision** | `[ ] YES`   `[ ] NO`   `[ ] DEFERRED` |
| Rationale | |
| Owner | |
| Evidence | |
| Date / version | |

> `NO` is a legitimate and complete answer. `DEFERRED` must carry the condition
> that would reopen it.

## 1.2 Intended purpose

**Nothing is preselected.** Mark each; more than one may apply.

| Purpose | In scope? |
|---|---|
| Source retrieval only | |
| Source summarisation | |
| Comparison assistant | |
| Trend interpretation support | |
| Question answering | |
| Drafting support | |
| Other (describe) | |

> **Retrieval and generation are different products.** "Source retrieval only"
> needs no generative capability and carries a different regulatory weight from
> summarisation or question answering. Marking several without saying which is
> primary is not a complete answer.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.3 Allowed regulated subject matter

**No category is pre-authorised.** Each requires an explicit YES or NO.

| Subject matter | Allowed? | Constraints if YES |
|---|---|---|
| Stability | | |
| Degradation products | | |
| Impurities | | |
| Residual solvents | | |
| Elemental impurities | | |
| Genotoxic impurities | | |
| Specifications | | |
| Analytical results | | |
| Trend data | | |
| Other (describe) | | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.4 Assertion boundary

**What the assistant MAY state and MUST NOT state.** Each line needs an explicit
answer; blank is not "no".

| Assertion type | May state? | Exact permitted wording, if any |
|---|---|---|
| Numerical conclusions | | |
| PASS / FAIL | | |
| Compliance statements | | |
| Shelf-life conclusions | | |
| Impurity qualification conclusions | | |
| Specification acceptance | | |
| Regulatory filing conclusions | | |
| Recommended corrective actions | | |
| **Human-only decisions** (list them) | | |

> This is the single most consequential section in Gate 1. An assistant that may
> state a shelf-life conclusion is a different regulated object from one that may
> only show a retrieved passage. **Engineering will not infer this boundary.**

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.5 Data boundary

**Every source class requires YES or NO. Nothing is assumed.**

| Source class | Allowed? | Constraints if YES |
|---|---|---|
| Internal approved documents | | |
| Internal drafts | | |
| Deficiency corpus (tenant-shared — §2.3) | | |
| FDA source releases | | |
| Pharmacopeial content | | |
| Uploaded client documents | | |
| External web content | | |
| **Model prior knowledge** | | |
| **`Form483Observation.summary` — existing AI-derived content (§2.2)** | | |
| **`WarningLetter.summary` — imported from an `ai_summary` column (§2.2)** | | |
| Other (describe) | | |

> Three rows deserve deliberate attention. **Model prior knowledge** decides
> whether answers may contain anything not traceable to a supplied source. The
> two **`summary`** rows are AI-derived content already in the read path with no
> provenance — allowing either as a source means allowing ungoverned AI output to
> ground new AI output. They are listed separately because they arrive by
> different routes (§2.2) and may reasonably be decided differently.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.6 Provenance requirement

Must every answer carry these? **Decide each.** §2.4 shows what the platform
already records for governed external sources.

| Provenance element | Required? |
|---|---|
| Source document | |
| Exact version | |
| Source section / page / locator | |
| Source status | |
| Retrieved timestamp | |
| Source checksum | |
| External-source release ID | |
| Confidence / support state | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.7 Failure behaviour

**What happens in each case.** An unanswered row becomes an engineering guess.

| Condition | Required behaviour |
|---|---|
| No source exists | |
| Sources conflict | |
| Source version is superseded | |
| Source is draft | |
| Source is quarantined | |
| Tenant mismatch occurs | |
| Source provenance is incomplete | |
| Answer cannot be fully supported | |
| Model / provider is unavailable | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.8 Human review requirement

| Question | Decision |
|---|---|
| Which outputs require review | |
| Who may review | |
| What approval / release step exists | |
| May unreviewed output be exported or copied? | |
| Does reviewed output become a governed record? | |

> "Human in the loop" without a named review step and owner is not an answer —
> see rejection criteria.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.9 Model / provider feasibility

**Is any external model or provider allowed?**

| | |
|---|---|
| **Decision** | `[ ] YES — external provider permitted`   `[ ] NO — no external generative path authorised` |

**If NO:** record explicitly that **no external generative path is authorised**.
Gate 2 §C then does not apply, and the assistant is bounded to retrieval and
whatever §1.2 permits without generation.

**If YES**, every line below is required:

| Requirement | Decision |
|---|---|
| Approved provider | |
| Approved model class | |
| Data residency | |
| Retention policy | |
| Training on customer data — prohibited or permitted | |
| Subprocessors | |
| Encryption (in transit and at rest) | |
| Tenant isolation at the provider | |
| Secrets management | |
| Outage behaviour | |
| Contractual approval | |

> **No provider or model is named in this document, and engineering will not
> choose one.** A provider named without the data and security lines completed
> is a rejection condition.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## 1.10 Feasibility acceptance decision

> ### This is the gate.

| | |
|---|---|
| **Status** | `[ ] FEASIBLE`   `[ ] NOT FEASIBLE`   `[ ] DEFERRED` |
| Owner | |
| Evidence | |
| Date / version | |
| **Gate 2 authorised to proceed?** | `[ ] YES`   `[ ] NO` |

**Both boxes matter.** `FEASIBLE` with Gate 2 not authorised means the assistant
could be built but is not yet approved to be specified for build.

---

# GATE 2 — PRODUCT / REGULATORY SPECIFICATION

> **Applies only if Gate 1 is FEASIBLE and Gate 2 is authorised.** Completing
> Gate 2 while Gate 1 is unanswered authorises nothing.

## A. Functional modes

**Explicit YES/NO each. Nothing preselected.**

| Mode | Allowed? | Notes |
|---|---|---|
| Retrieval | | |
| Extractive answer | | |
| Summarisation | | |
| Comparison | | |
| Trend explanation | | |
| Drafting | | |
| **Generative answer** | | |
| Recommendation | | |
| Workflow action | | |

> If **generative answer** is NO, §C does not apply. If **workflow action** is
> YES, the assistant stops being advisory and becomes part of a governed
> workflow — with the audit and approval consequences that follow.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## B. Retrieval contract

| Requirement | Decision |
|---|---|
| Searchable source types | |
| Approved / draft status rules | |
| Exact-version semantics | |
| Tenant boundary (**note the shared corpus, §2.3**) | |
| Section / locator usage | |
| Ranking rules | |
| Number of sources returned | |
| Stale / superseded source handling | |
| No-result behaviour | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## C. Generation contract

> **Generation is not assumed to be allowed.** This section applies only if
> §A "generative answer" is YES **and** §1.9 permits a provider.

| Requirement | Decision |
|---|---|
| Source-grounded only, or model knowledge permitted | |
| Paraphrase allowed? | |
| Synthesis across sources allowed? | |
| Unsupported completion behaviour | |
| Citation granularity | |
| Quotation limits | |
| Deterministic settings, if required | |
| Prompt / version governance | |
| Output schema | |
| Disallowed statement categories | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## D. Accuracy / verification standard

> **No target is proposed here.** An accuracy standard with no measurement method
> does not unblock anything.

| Requirement | Decision |
|---|---|
| Metric | |
| Test corpus | |
| Expected answers | |
| Source-grounding test | |
| Unsupported-claim test | |
| Conflicting-source test | |
| No-source test | |
| Stale-source test | |
| Tenant-isolation test | |
| **Acceptance threshold** | |
| Evaluator | |
| Sign-off authority | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## E. "Cannot answer" contract

Exact statuses and reason codes the owner requires. **These are recorded as owner
decisions — this document does not predeclare which must exist in
implementation.**

| Condition | Required status / reason code | User-visible wording |
|---|---|---|
| `source_unavailable` | | |
| `source_conflict` | | |
| `unsupported_claim` | | |
| `review_required` | | |
| `provider_unavailable` | | |
| `prohibited_scope` | | |
| `stale_source` | | |
| `provenance_incomplete` | | |
| `tenant_mismatch` | | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## F. Audit contract

Which operations must create regulated audit events. **No event is implemented by
this document**, and §2.5 records that no assistant audit domain exists.

| Operation | Audit event required? | Fields recorded |
|---|---|---|
| Query | | |
| Retrieval | | |
| Source selection | | |
| Prompt assembly | | |
| Model invocation | | |
| Response generation | | |
| Response rejection | | |
| Human review | | |
| Export / copy / download | | |
| Approval | | |
| Regeneration | | |
| Provider failure | | |

> **Audit payloads cannot be redacted after the fact.** What a prompt or response
> event records must be constrained deliberately, especially if prompts may
> contain client document content.

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## G. Record status

What an assistant output **is**. Nothing preselected.

| Status | Selected? |
|---|---|
| Transient | |
| Evidence | |
| Draft governed record | |
| Approved governed record | |
| Never persisted | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## H. Retention

> **Separate from the existing calculation-retention question** in the special
> section below. They are different questions about different objects and must
> not be answered as one.

| Object | Retention rule |
|---|---|
| Prompts | |
| Retrieved source IDs | |
| Model responses | |
| Model metadata | |
| User feedback | |
| Review decisions | |
| Rejected / blocked responses | |
| Provider request IDs | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## I. Security / privacy

| Requirement | Decision |
|---|---|
| PHI / PII — prohibited or allowed | |
| Confidential client data | |
| Secrets redaction | |
| Prompt injection handling | |
| File-content sanitisation | |
| External-provider transmission | |
| Logging and redaction | |
| Tenant isolation | |
| Client-side caching | |
| Export controls | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## J. UI / UX

| Requirement | Decision |
|---|---|
| Where the assistant appears | |
| Source panel | |
| Citation display | |
| Unsupported-answer warning | |
| Human-review indicator | |
| Copy / export controls | |
| Draft watermark or label, if needed | |
| Provider outage state | |

| Owner | | Evidence | | Date / version | |
|---|---|---|---|---|---|

## K. Governance

| Role / field | Value |
|---|---|
| Product owner | |
| Regulatory owner | |
| Security owner | |
| Technical owner | |
| Approved specification version | |
| Approval evidence | |
| Effective date | |
| Superseded version handling | |

## L. Implementation authorisation

> ## ALL applicable approvals must be complete before implementation starts.

| | Approval |
|---|---|
| `[ ]` | Gate 1 **FEASIBLE** |
| `[ ]` | Gate 2 **authorised** |
| `[ ]` | Product specification approved |
| `[ ]` | Regulatory assertion boundary approved |
| `[ ]` | Security / data boundary approved |
| `[ ]` | Model / provider approved **if applicable** |
| `[ ]` | Accuracy / verification method approved |
| `[ ]` | Audit / retention contract approved |

**"If applicable" is not a loophole.** If §1.9 is NO, the provider line is not
applicable and §C does not apply — but every other line still stands.

---

# SPECIAL SECTION — The existing calculation retention question

> **This is a separate question about a different object, and it is deliberately
> not folded into the assistant scope.** It concerns the existing six-function
> calculation engine, which exists and is in use today. It would remain open even
> if Gate 1 were answered NO.

## Current engineering fact

* The **existing implementation conforms to the approved 4D-3 engineering
  specification.**
* `percentage_w_w` and `daily_exposure` sit **outside `AssessmentSnapshot`
  population**. Their `CalculationOutcome` is updated in place, and the audit
  event records identifiers and status rather than a historical copy of prior
  input and output values.
* **Part 11 sufficiency remains NOT DETERMINED.**

## Four distinctions to preserve in any summary

1. The implementation **conforms** to 4D-3.
2. **No engineering defect is established.**
3. The SOW 2.9 regulatory expectation *may* be broader than the engineering
   specification.
4. **Engineering must not decide that Part 11 question itself.**

## Required regulatory decision

**Does SOW 2.9 expect anything broader than the 4D-3 specification provides for
calculator input/output retention?**

| | |
|---|---|
| **Status** | `[ ] NO — 4D-3 retention is sufficient`   `[ ] YES — broader expectation`   `[ ] NOT DETERMINED` |
| If YES, what is expected | |
| Owner | |
| Evidence | |
| Date / version | |
| Implementation consequence | |

> **This is not a defect, not a CAPA, and not a validation deviation.** It is a
> regulatory determination that has not been made. No current implementation is
> changed by this document, and **no Part 11 compliance claim is made or implied.**

---

## Engineering handoff criteria

The exact minimum before implementation may begin. A conjunction — every
applicable line.

| # | Required |
|---|---|
| 1 | **Gate 1 FEASIBLE** |
| 2 | **Gate 2 authorised** |
| 3 | Allowed modes approved (§A) |
| 4 | Source / data boundary approved (§1.5, §I) |
| 5 | Assertion boundary approved (§1.4) |
| 6 | Retrieval rules approved (§B) |
| 7 | Generation rules approved **if applicable** (§C) |
| 8 | **Measurable** accuracy method approved (§D) |
| 9 | Test corpus defined (§D) |
| 10 | Failure behaviour approved (§1.7, §E) |
| 11 | Provenance contract approved (§1.6) |
| 12 | Audit contract approved (§F) |
| 13 | Retention approved (§H) |
| 14 | Provider / security approval **if applicable** (§1.9, §I) |
| 15 | UI behaviour approved (§J) |
| 16 | **Named accountable owners** — a named person, not a role alone |
| 17 | Approval evidence — the approvals themselves |
| 18 | Specification version |

## Engineering rejection criteria

Return the package if any of these occur. **Interpreting an ambiguous
specification is how engineering ends up setting a regulatory boundary it does
not own.**

| Rejected | Why |
|---|---|
| **"AI assistant" is the only functional description** | Does not distinguish retrieval from generation — two different products with different regulatory weight |
| **"Use approved sources" without defining approved** | No document status means "approved" today; the term has to be defined before it can be enforced |
| **"Zero hallucination" without a measurable method** | Cannot be built to, tested, or signed off, and no conformance claim may be made |
| **"High accuracy" without metric and threshold** | Unmeasurable, therefore unverifiable |
| **"Human in the loop" without review step and owner** | Names an aspiration, not a control |
| **Source version semantics missing** | Ambiguous the moment a source is superseded; answers become unreproducible |
| **Model prior knowledge boundary unspecified** | Decides whether answers may contain untraceable content — the core grounding question |
| **Conflict or no-source behaviour missing** | The two cases most likely to produce a confident wrong answer |
| **Provider named without data and security approval** | A provider selection is a data-processing decision, not a technical preference |
| **Audit requirement says only "log activity"** | Names no operation, field or retention; payloads cannot be redacted later |
| **Retention unspecified** | Prompts and responses may contain client content; undefined retention is undefined exposure |
| **Regulatory assertion boundary ambiguous** | The difference between showing a passage and asserting a shelf-life conclusion |
| **Test corpus absent** | An acceptance method with nothing to run against is not a method |
| **Approvals asserted without evidence** | "Approved" without the approval is not an approval |

## What this document does not do

It implements nothing: no AI, no retrieval, no embeddings or vector search, no
prompts, no model-provider code, no audit events, and no change to code, config,
authentication or security controls. It selects no model or provider, invents no
accuracy target and no acceptance threshold, and defines no regulatory assertion
boundary. It interprets no stability or impurity guidance into product logic. It
fills no decision field and records no approval. **It creates no AI scope by
assumption** — Gate 1 exists so that scope is granted deliberately or not at all.

It does not collapse the Part 11 calculation-retention question into the
assistant scope, and it makes **no 21 CFR Part 11 compliance claim**.

## Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** The codebase declines it explicitly;
   an immutable audit mechanism is not compliance.
2. **No validated-production claim for the calculation engine.** The six formulas
   are governed by an approved *engineering* specification, not a traceable
   external regulatory source, and the calculation tests are engineering
   evidence, not validation evidence in the regulated sense.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status,
   and P11 leaves Part 11 sufficiency **NOT DETERMINED**.
