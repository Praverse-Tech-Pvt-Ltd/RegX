# Milestone 4D — Integrated Status Assessment

**Assessed at:** `regx-main` @ `7acf1670f565dc269836a873ebe54d483b5dc298` (PR #17 merged)

> ## Verdict
>
> **Engineering Milestone 4D: NOT COMPLETE.**
> **Production regulatory content gate: 0 of 20 approved — tracked separately.**
>
> 4D-1, 4D-2 and 4D-3 are complete. 4D-4 is **substantially complete but not
> closed**: four engineering items remain, listed in §5. This document does not
> close the milestone, and the two gates above are deliberately not conflated.

---

## 1. What is merged and verified working together

Every item below was exercised by the integrated regression run in §4, not merely
inspected.

| Capability | Slice | Status |
|---|---|---|
| Checklist definition governance | 4D-1 | merged |
| Execution / response / outcome foundation | 4D-2 | merged |
| Governed response update + `expected_version` concurrency | 4D-3 | merged |
| Deterministic calculations, cascade, topological order, rollback | 4D-3 | merged |
| `CalculationOutcome` read projection | 4D-3 | merged |
| APP-009 applicability ownership | 4D-4 · PR #12 | merged |
| Controlled export, canonical form, SHA-256 checksum | 4D-4 · PR #15 | merged |
| Normalized export provenance (`4D4-DEC-005`) | 4D-4 · PR #15 | merged |
| Reviewer-amendment provenance | 4D-4 · PR #15 | merged |
| Governed overrides + `PERM_OVERRIDE_EXECUTION` | 4D-4 · PR #16 | merged |
| `FDA_DERIVED_DEFAULT`-only overridability (`4D4-DEC-010`) | 4D-4 · PR #16 | merged |
| Original system-derived value preservation | 4D-4 · PR #16 | merged |
| `ANSWER_OVERRIDDEN` history (`4D4-DEC-004`) | 4D-4 · PR #16 | merged |
| Override audit + export override provenance | 4D-4 · PR #16 | merged |
| `approval_metadata` (`4D4-DEC-008`) | 4D-4 · PR #17 | merged |
| Tenant-scoped capabilities (`4D4-DEC-012`) | 4D-4 · PR #17 | merged |
| Override UI capability gating | 4D-4 · PR #17 | merged |

**Governance:** all twelve registered decisions `4D4-DEC-001` … `4D4-DEC-012`
are **APPROVED**. None remains open.

## 2. Integrity properties confirmed

- **Tenant isolation** — every governed service performs the tenant-scoped
  `visible_to()` lookup *before* any permission check, so a cross-tenant
  identifier returns 404 rather than a 403 that would confirm existence. The
  capability endpoint is tenant-scoped and does not infer authority from another
  membership.
- **Export integrity** — one governed payload, one canonical serialization, one
  SHA-256. JSON and CSV are renderings of the same artifact and carry the same
  checksum. `generated_at` and `export_schema_version` are inside the hashed
  payload; only the checksum itself is outside, because a hash cannot cover
  itself.
- **Server-control boundaries** — `system_derived_value`, `override_reason` and
  `approval_metadata` are all unreachable from the ordinary response PATCH; each
  has a dedicated governed writer.
- **Provenance discipline** — every export group is positive allow-listed with a
  runtime guard. Public identifiers only: no database primary keys, no actor
  email or display name, no model representations, no exception text.

## 3. `ControlledExportError` — accepted technical debt

**Disposition: DEFERRED.** Not Critical, not Major.

**Exact trigger conditions.** `ControlledExportError` is raised by exactly three
guards in `controlled_export.py`: a `float` reaching `_canonical_scalar`, an
unsupported Python type reaching the same function, and a projection producing a
key outside `ALLOWED_INPUT_DESCRIPTOR_FIELDS` / `ALLOWED_AMENDMENT_FIELDS` /
`ALLOWED_OVERRIDE_FIELDS`. `ChecklistExecutionExportView` catches only
`ExportPermissionDenied` and `ExecutionNotExportable`, so this would surface as
an unstructured 500.

**Why it does not produce an incorrect artifact or a false success audit.** The
exception is raised during artifact assembly, before any response is rendered and
before `transaction.on_commit()` registers the audit callback. No artifact is
issued, no checksum is published and no `execution.exported` success event is
emitted. It is fail-closed in the direction that matters for a regulatory record.

**Why it is not fixed here.** The three conditions have genuinely different
correct HTTP answers — corrupt persisted data is not the same fault as an
unreviewed field entering a projection — so a single blanket status would encode
a governance choice rather than a mechanical fix. Reachability also requires data
written outside every governed path: numeric answers are validated as decimal
*strings*, reviewer conclusions are strictly `{"value": <str>}`, and no migration
or fixture writes response JSON.

## 4. Integrated regression results

Run against merged `regx-main` @ `7acf167`.

| Gate | Result |
|---|---|
| `manage.py check` | no issues (0 silenced) |
| `makemigrations --check --dry-run` | **No changes detected** |
| `migrate --check` | exit 0 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 278 files already formatted |
| `lint-imports` | exit 0 |

Backend, frontend and E2E results are recorded in the final report accompanying
this assessment.

### A note on one voided run

An initial full-suite run reported 4 errors in the lock-ordering and
concurrent-version-allocation tests, with PostgreSQL reporting *"database
test_regx_test is being accessed by other users"*. That run was invalidated by a
second pytest session executing against the same test database concurrently — an
operator error, not a defect. It is recorded here rather than discarded silently,
because a reader comparing run logs would otherwise see an unexplained failure.
The suite was re-run serially.

### E2E disposition

**BASELINE FAILURE — no new 4D regression.** `fda-iid.spec.ts:733`
("Terminology mapping review › … affected-record drill-down") fails under
parallel execution and passes in isolation, indicating a race on a URL assertion.
The same failure reproduces on the clean merged base with 4D-4 changes stashed —
at one point with an *additional* failure (`fda-iid.spec.ts:68`) that the feature
branches did not exhibit. No 4D slice touches FDA-IID or terminology-mapping
code.

**This is unresolved test debt, not a pass.** The E2E suite cannot currently be
used as a clean release signal for any milestone, and stabilising
`fda-iid.spec.ts` deserves its own task. Modifying FDA-IID code to make 4D look
green was explicitly rejected.

## 5. Why Milestone 4D is not closed

Four engineering items remain, all recorded in `MILESTONE_4D_4_DISCOVERY.md`:

1. **Reviewer-conclusion frontend surface.** §H records the remaining scope as
   "frontend surface for entering and displaying conclusions". The governed
   service, its dedicated endpoint and its export projection all exist; the UI
   does not. Only the execution-level `approve` call passes a
   `reviewer_conclusion_note`, and no client calls the per-response
   reviewer-conclusion endpoint.
2. **Reviewer-conclusion minimum-length enforcement.** §H asks to "confirm
   min-length enforcement matches §13". Only `MAX_REVIEWER_CONCLUSION_CHARS` is
   enforced today; no minimum is applied.
3. **`ReviewerConclusionSerializer.expected_version` coercion — disposition
   OPEN.** It retains `IntegerField(min_value=1)`, so `1.0`, `"1"` and `"1.0"`
   are coerced to `1`, whereas the response-update and override paths pass the
   raw value to the shared `validate_expected_version()` and reject all three.
   Three governed write paths, two contracts. The discovery document records this
   as "not *required* by 4D-4's authoritative scope … Recommend closing; requires
   approval" — so it is a **governance decision, not a free fix**, and was
   deliberately not resolved unilaterally.
4. **Override clearing.** Deferred by §AC.4 pending its own decision. No clear
   path, no `ANSWER_OVERRIDE_CLEARED` code and no route exist.

Item 3 is the one worth a deliberate look: it is a real inconsistency in a
governed contract, but closing it changes an API's accepted input, which is why
the register requires approval rather than treating it as cleanup.

## 6. Production regulatory content — separate gate

**0 of 20 approved.** Governed entirely by
`MILESTONE_4D_4_CONTENT_APPROVAL.md`. This requires human regulatory authorship
and sign-off; it is not an engineering task and no engineering work can advance
it. It is tracked independently of engineering completion and **must not** be
read as satisfied by any result in this document.

## 7. Successor milestone

**None is defined in this repository.** There is no Milestone 5 document, no
discovery file and no scoped identifier beyond 4D. The `ROADMAP.md` "Next"
section names production gates (FDA ingestion, client formulation use,
regulatory-template migration) that depend on client or regulatory input, and
capability areas (ANDA/DMF scoring, regulatory AI, report generation, Word
integration) that have never been scoped. Each would need its own discovery pass
before an implementation prompt would be meaningful.
