# SOW Section 2 — Technical Tools (Regulatory), AI Based
## Status against `regx-main`

- **Source:** `SOW - Praverse (Pratham)  iCretegy_April 22, 2026.pdf`, section 2 (pages 7–9), items 2.1–2.11
- **Codebase:** branch `regx-main`, commit `0da78c8` (PR #44, "Milestone 16 — Final Validation, Release Readiness")
- **Verified:** stack built and running locally — 7 services healthy, `readiness` reports `database: ok`, `cache: ok`
- **Date:** 2026-09-08

> **An earlier version of this assessment exists on the `main` branch** as
> `SOW-TECHNICAL-TOOLS-STATUS.md`. It measured the legacy iPharmaAI Django
> monolith, which shares **no common ancestor** with `regx-main` and is a
> different product. It is accurate about `main` and irrelevant to this codebase.
> This document replaces it for any question about REGX.

---

## The one-line summary

**REGX has built the regulated data platform and workflow engine that section 2
describes. It has built none of the AI.**

That is not a criticism — the two halves are separable, and the platform half is
the harder, more valuable foundation. But the SOW heading is "Technical Tools
(Regulatory) – **Ai Based**", and every AI-specific deliverable in it is absent.

---

## Scorecard

| Legend | |
|---|---|
| ✅ | Built |
| 🟡 | Substantially built, with a named gap |
| ⬜ | Not built |
| 💤 | SOW itself marks it "will see later if this point is feasible" |

| SOW | Item | Status | Evidence |
|---|---|---|---|
| 2.1 | Module architecture & toolkit | ✅ | 19 Django apps, React/TSX frontend, 200 API endpoints, docker compose |
| 2.2 | IIG checklist automation | 🟡 | `iig_checklist` (35.8k LOC) + `fda_data` IID models. Calculation engine is **built** — six approved formulas, 279 tests — but **content approval is PENDING**. See [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) |
| 2.3 | HTML calculators (dissolution/impurity/stability) | ⬜ | No implementation and **no approved formula specification** in either codebase. **Blocked on client input** — see [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md) |
| 2.4 | Role hierarchy: Doer / Reviewer / VP | ✅ | `authorization.Role.BuiltIn` + `workflows` with append-only transitions |
| 2.5 | FDA Orange Book integration | ✅ | `OrangeBookApplication` / `Product` / `ProductIngredient` + importer |
| 2.6 | Chatbot across workflow | ⬜ | 0 hits for `chatbot`, `openai`, `llm` in `backend/` or `frontend/src`. See **Note 2.6** — the legacy `company_site` chatbot was removed in P8 |
| 2.7 | Word plug-in | ⬜ | Not present |
| 2.8 | AI-driven gap analysis engine | ⬜ | 0 hits for `gap analysis`, `gap score`, `predictive`, `heatmap` |
| 2.9 | Stability & impurity AI + Part 11 audit trail | ⬜ / 🟡 | No AI. `audit.AuditEvent` is immutable at ORM **and** Postgres trigger level, but the codebase **explicitly disclaims** a Part 11 claim |
| 2.10 | Intelligent document management | 🟡 💤 | Versioning + duplicate detection built. No AI comparison, commentary or auto-tagging |
| 2.11 | Timeline | — | Their own roadmap runs to Milestone 16 |

---

## What is built ✅

### 2.5 Orange Book — done

`backend/fda_data/models.py` carries the full ingestion chain:

```
FDADataSourceRelease      versioned dataset releases with status
OrangeBookApplication
OrangeBookProduct
OrangeBookProductIngredient
RouteMapping / DosageFormMapping / UnitMapping    controlled terminology
SubstanceSynonymMapping
FdaImportRowResult        per-row import outcome
```

`fda_data/importer.py` and `adapters.py` do the loading. **23 API endpoints**, and a
frontend at `/fda-data/orange-book` and `/fda-data/releases` (verified 200).

This is the SOW's *"iCretegy shall provide the FDA database excel and Praverse
needs to update accordingly"* — built as a governed, versioned, reconcilable import
rather than a one-off script.

### 2.4 Role hierarchy — done, and stronger than the SOW asks

`backend/authorization/models.py:17`

```python
class BuiltIn(models.TextChoices):
    DOER = "doer", "Doer"
    REVIEWER = "reviewer", "Reviewer"
    VP = "vp", "VP"
    TENANT_ADMIN = "tenant_admin", "Tenant Admin"
```

The `workflows` app supplies the review gates: `WorkflowItem`, `WorkflowTransition`
(append-only, `_ImmutableTransitionQuerySet`), `WorkflowEvidence`. State is never
assigned directly — it moves only through `workflows.services` under a row lock.

Checklist and template versions carry the full gate set as API actions:
`submit-review`, `approve`, `reject`, `return`, `activate`, `retire`, `supersede`.

### 2.1 Module architecture — done

The SOW asks for *"a single premium toolkit rather than scattered utilities."*
That is what this is: one React app over a versioned REST API, 19 bounded Django
apps, PostgreSQL, Redis, Celery, nginx, all under compose.

---

## Substantially built, with a real gap 🟡

### 2.2 IIG checklist automation

**Built:** `iig_checklist` is the largest app in the codebase at **35,778 lines** —
`ChecklistDefinition`, `ChecklistVersion`, `ApplicabilityRule`, `ChecklistSection`,
`ChecklistQuestion`, `ChecklistExecution`, `ChecklistResponse`, plus
`ChecklistResponseHistory` with governed immutability. **32 API endpoints.**

The FDA side is there too — `fda_data` has `IIDIngredient`, `IIDPrecedentRecord`,
`IIDCalculabilityStatus`, `IngredientMappingLifecycle`, and `iid_assessment`
produces `AssessmentSnapshot`. IID is the Inactive Ingredient Database, which is
exactly the SOW's "FDA IIG database".

**The gap — corrected by P9.** This section previously reported the calculation
engine as a placeholder awaiting Milestone 4D-3, quoting the `CalculationOutcome`
docstring (`backend/iig_checklist/models.py:971`), which still reads *"Populated
with actual values in 4D-3"*.

4D-3 has since been delivered, so both the claim and that docstring are **stale**.
Re-inspected at `de15742`: `iig_checklist`/`iid_assessment` carry **six approved
formulas** — `Decimal`-only, versioned, fail-closed — under **279 tests** that
assert real computed values and every blocked status. The number that comes out of
the calculation is no longer a placeholder.

The remaining gap is a different one, and it is **not** engineering.
`MILESTONE_5A_APPROVAL_REGISTER.md` records **Item 13** (`SYSTEM_CALCULATED`
bindings — which calculation applies to which question, and the regulatory reason)
as **PENDING**, with interpretation risk **HIGH**: *"the wrong calculation produces
a wrong regulated number."* **Item 14** (dependencies and ordering) is **PENDING**
behind it, and the content gate overall stands at **0 of 20 approved**.

So: **engineering implementation complete, regulatory and content approval not.**
No validated or production-ready status is claimed for the calculation engine.
Detail in [CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md).

### 2.9 Part 11 audit trail

`audit.AuditEvent` is immutable at **two** levels — `save()`/`delete()` raise, and a
PostgreSQL trigger enforces it in `migrations/0001_initial.py`. That is a stronger
implementation than the legacy app's.

But the codebase repeatedly and deliberately declines the compliance claim:

- `backend/workflows/models.py:5` — *"confers no approval, and establishes no Part 11 claim"*
- `docs/DOSSIER_BLUEPRINTS.md:13` — *"No 21 CFR Part 11 compliance claim, no GxP"*
- `docs/DOSSIER_UPGRADES.md:16` — *"No Part 11 claim, no GxP validation claim"*

Whether that satisfies the SOW is a **contract question, not a code question**. The
mechanism exists; the attestation is explicitly withheld.

### 2.10 Document management

Built: `Document`, `DocumentVersion`, `DocumentLocator`, `DocumentProcessingJob`,
`DocumentDuplicateLink`, plus `ScanStatus` / `ProcessingStatus`.

Missing: the AI half — *"the AI summarizes what changed between versions"*,
*"side-by-side diff with AI commentary"*, *"auto-tagging by document type, CFR
relevance, product category"*. SOW marks this item feasibility-TBD anyway.

---

## Not built ⬜ — the entire AI surface

I searched `backend/`, `frontend/src`, `frontend/app` for every AI marker.
**These counts are for the REGX platform only and have never covered
`company_site/`**, which is a separate legacy service carried into this
repository. An earlier revision of this document reported them as holding
"anywhere", which was wrong — see **Note 2.6**.


| Term | Hits |
|---|---|
| `openai` | **0** |
| `anthropic` | **0** |
| `llm` | **0** |
| `chatbot` | **0** |
| `gap analysis` / `gap score` | **0** |
| `embedding` | **0** |
| `predictive` | **0** |
| `heatmap` | **0** |

No AI SDK appears in `backend/requirements/`.

The project states this itself. `docs/ROADMAP.md`, on the operations dashboard:

> **No regulatory judgement of any kind.** No CTD, eCTD, CEP, DMF, ANDA, USFDA or
> EMA structure or rules; no completeness engine; no submission validation; **no AI
> conclusions**. **A green dashboard does not mean a submission is acceptable to
> anyone**, and the screen says so in standing copy.

That is a deliberate scope boundary, held consistently, and it means SOW **2.6, 2.7,
2.8, and the AI half of 2.9 and 2.10 are entirely outstanding**.

### 2.3 Calculators

`impurity` 0 hits, `shelf-life` 0 hits, `stability` 3 hits, `dissolution` 1 hit —
none of them a calculator. The 454 `ICH` hits are terminology and test fixtures, not
ICH Q3A/Q3B threshold logic.

**Re-inspected for P9 at `de15742`, and the position is unchanged but now has a
reason.** There is no dissolution, impurity or stability/shelf-life calculator in
`regx-main`, and none in the legacy `main` branch either — the 59
`company_site/templates/RATools/*.html` files are document generators, not
calculators, so 2.3 is not a port. More decisively, there is **no approved formula
specification for any of the three** anywhere in this repository: no source
document, no version, no owner, no sign-off.

2.3 is therefore **blocked on client input, not on engineering capacity**. The
formulas must be supplied and owned; deriving them from ICH guidance would be
engineering choosing a regulatory parameter. The eleven required inputs, and the
reason SOW 2.3 cannot be built inside the existing six-formula registry
(`SCOPE-OUT-18`), are set out in
[CALCULATOR_GAP_REPORT.md](CALCULATOR_GAP_REPORT.md).

---

## Comparison: the two codebases against the same SOW

| SOW | `main` (legacy) | `regx-main` |
|---|---|---|
| 2.1 Toolkit architecture | ⬜ scattered routes | ✅ |
| 2.2 IIG automation | ⬜ manual text fields | 🟡 data + governance built, calc engine built, content approval PENDING |
| 2.3 Calculators | ⬜ | ⬜ blocked on client formula specification |
| 2.4 Doer/Reviewer/VP | ✅ basic | ✅ with append-only transitions |
| 2.5 Orange Book | ⬜ | ✅ |
| 2.6 Chatbot | ⬜ | ⬜ |
| 2.7 Word plug-in | ⬜ | ⬜ |
| 2.8 Gap analysis | 🟡 scoring for 2 of 6 checklist families | ⬜ none at all |
| 2.9 Part 11 trail | 🟡 model right, 3 call sites | 🟡 stronger mechanism, claim withheld |
| 2.10 Doc management | ⬜ | 🟡 versioning built |

**Note 2.6 (updated by P8).** REGX has no chatbot and none is planned by this
work; 2.6 remains unbuilt and deferred. **No governed chatbot or AI assistant
exists in REGX, and nothing here is validated or production-ready.**

What did exist was in the legacy `company_site` service, not REGX: seven
commented-out chatbot view functions, seven commented URL routes, an
unreferenced 1,566-line chat template, a `ChatMessage` and a `ChatHistory`
model, and a serializer. None of it was reachable — the routes had been
commented out since the service was carried into this repository — and had it
been re-enabled it would have exposed unauthenticated, CSRF-exempt destructive
endpoints. P8 deleted all of it. No replacement was added.

P8 also removed an *accidental* live dependency. `Form483Filter`'s observation
search called a ChatGPT helper to expand the query into synonyms before
searching, so an ordinary search submission on the Form 483 page reached a paid
external API. It was also broken: the helper returned a six-tuple that the
caller iterated as a flat list, so every search matched nothing. The search is
now a plain database `icontains`, the helper and its OpenAI import are gone,
and the behaviour is covered by tests that fail if the search touches a socket.

**One OpenAI integration remains in the repository**, found by searching after
the change: `company_site/AIDatabase/observation_summary.py`, which generates
Form 483 observation summaries during an Excel cache refresh. It is off by
default behind an explicit `OPENAI_API_KEY` check and returns `None` without
one — a real gate, not the SDK-version accident that was masking the search
path. P8 did not change it. There are no OpenAI references anywhere in
`backend/` or `frontend/`.

**Legacy SQLite tables.** `AIDatabase` has no migrations at all, so the chat
models were never migration-managed. The checked-in `db.sqlite3` still contains
empty `AIDatabase_chatmessage` and `AIDatabase_chathistory` tables (0 rows
each). P8 deliberately did not fabricate a migration history for an app that
has none, and did not mutate the database file. No application code references
those tables; dropping them is a separate legacy-database maintenance task.

**Note 2.8.** The legacy app is the *only* place gap scoring exists — `RATools/gap_analysis.py`
produces a 0–100 score for ANDA and DMF. `regx-main` has none. If that logic is
wanted in the new platform, it is a port, not a rewrite from nothing.

---

## What this means for planning

1. **The platform work is largely done; the AI work has not started.** Roughly half
   of section 2 by item count, and the half the SOW headline names, is outstanding.
2. **2.2 is closest to finished.** Everything except the calculation engine is in
   place, and the placeholder names its own milestone (4D-3).
3. **The Part 11 question needs a decision, not code.** The mechanism is stronger
   than the legacy app's; the codebase declines the claim on purpose. Someone has to
   decide whether the SOW requires the attestation or the control.
4. **Nothing blocks the AI work in this codebase.** Unlike `main`, there is no
   hardcoded key and no legacy constraint — 2.6/2.7/2.8 are greenfield here.

---

## How this was verified

- Stack built and run: `docker compose build && docker compose up -d`, 7/7 healthy
- API surface read from the live OpenAPI schema at `/api/schema/` — 200 paths
- Frontend routes confirmed by HTTP (200 on `/dashboard`, `/iig-checklists`,
  `/documents`, `/formulations`, `/fda-data/orange-book`)
- Model inventories read from each app's `models.py`
- Absence claims are `grep -rioE` counts across `backend/`, `frontend/src`,
  `frontend/app`, stated above as raw hit counts so they can be re-run

## Caveats

- Assessed at `0da78c8`. Several `regx/*` branches are unmerged and may contain work
  not counted here.
- I did not run the backend test suite (126 files, 2,965 test functions). "Built"
  here means present and wired into the API, not verified by execution.
- The SOW says section 2 scope "may be finalized later (in phase 2)". This measures
  against the 2026-04-22 text.
