# Milestone 4D-3 Threat Model

**Status: DISCOVERY. No implementation authorized.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This threat model covers the security and data-integrity risks introduced by the new
4D-3 attack surface: the draft-answer population pass, the automatic `FDA_DERIVED_DEFAULT`
resolver, the `SYSTEM_CALCULATED` computation layer, and the in-draft cascade
recalculation path. Risks already present in 4D-1 and 4D-2 are not re-analyzed here;
only incremental 4D-3 surface is covered.

---

## 1. Scope

4D-3 introduces one new behavioral surface:
- A server-side population pass that reads governed FDA data and formulation fields, then
  writes draft answers into `ChecklistResponse` and `CalculationOutcome` rows.
- A cascade recalculation triggered by `enter_response()` on `draft` executions.
- A new applicability runtime evaluator (pure function against an in-memory context dict).
- New frontend display of auto-populated answers and calculation results.

4D-3 does not introduce:
- New models or migrations (nothing to attack at the database-schema level).
- New user-facing write endpoints (population is server-side; recalculation is triggered
  by the existing `PATCH responses/<uuid>/` endpoint, which already exists in 4D-2).
- New authentication or authorization logic (no new permission codenames).

---

## 2. Threat Inventory

### T-01: Forged FDA-derived answer (HIGH — mitigated by design)

**Attack:** A malicious Doer sends a crafted PATCH to a `FDA_DERIVED_DEFAULT` question
response, supplying a `raw_value` that differs from the governed FDA data, in an attempt
to inject a false identity match or precedent result into the checklist.

**Mitigation (already in 4D-2):** `enter_response()` rejects any `raw_value` for a
`FDA_DERIVED_DEFAULT` question from a `Doer`-level actor. Only a `REVIEWER_CONFIRMED`
actor may override a `FDA_DERIVED_DEFAULT` answer, and only through the override path
(4D-4 scope). In 4D-3, the population pass runs server-side; no client-supplied value
is accepted for `FDA_DERIVED_DEFAULT` questions during population.

**Residual risk:** None beyond what is already present in 4D-2. The `data_source_type_snapshot`
frozen at answer time makes the provenance visible and auditable.

**Implementation requirement:** `enter_response()` must explicitly check
`data_source_type_snapshot == "fda_derived_default"` and reject any PATCH with a
`raw_value` (not `is_not_applicable`) unless the actor has the override permission (4D-4
path). This check must be enforced in the service layer, not only in the serializer.

---

### T-02: Forged calculation result (HIGH — mitigated by design)

**Attack:** A client attempts to supply a `raw_value` for a `SYSTEM_CALCULATED` question
(e.g. `calculated_value`, `calculated_status` answer types) to inject a false calculation
result.

**Mitigation (already in 4D-2):** `ChecklistResponseUpdateSerializer` already rejects
any non-null `raw_value` for `calculated_value`, `calculated_status`, and
`approval_metadata` answer types with `error_code = "invalid_raw_value_shape"` / 400.
No client-facing endpoint accepts `CalculationOutcome` input. 4D-3 populates
`CalculationOutcome` rows server-side only.

**Residual risk:** None. The constraint is structural: the `CalculationOutcome` update
service is not reachable from any client-facing endpoint.

---

### T-03: Cascade recalculation loop (MEDIUM — new surface in 4D-3)

**Attack:** An adversarially crafted `ChecklistVersion` definition creates a circular
dependency in `calculation_binding` (question A's calculation depends on question B,
whose calculation depends on question A). When `enter_response()` triggers a cascade,
the recalculation enters an infinite loop.

**Mitigation:** The approved design states (4D-3 discovery §4d): "The dependency graph
is acyclic by construction — no `SYSTEM_CALCULATED` question may depend on another
`SYSTEM_CALCULATED` question as a named input." This structural rule must be enforced
at `ChecklistVersion` activation time by the 4D-3 implementation: the activation pre-
condition check (already run at the 4D-1 layer for structural integrity) must be extended
to validate the acyclicity of `calculation_binding` dependencies across all questions in
the version.

**Implementation requirement:** At `ChecklistVersion` activation, build the dependency
graph from all `calculation_binding` fields in the version's questions and assert it is
a DAG (directed acyclic graph). If a cycle is detected, the activation must be rejected
with a structured error. This check runs once at activation time, not on every population
call.

**Residual risk after mitigation:** Low. A malicious `platform_master` author could
theoretically attempt to submit a cyclic definition, but this is blocked at activation.
An implementation bug in the DAG check is the residual risk; this should be unit-tested
with a planted cyclic fixture.

---

### T-04: Stale FDA data used in population (MEDIUM — requires explicit disclosure)

**Attack (not an external attack but a data-integrity risk):** The population pass
calls `resolve_substance_identity()` and `find_iid_candidates()` against the current
active FDA release. If the active release is changed (superseded) between when the user
creates the execution and when they submit it for review, the draft answers may reference
data from a release that is no longer active.

**Mitigation:** The approved design addresses this explicitly (4D design §8a):

> A scheduled advisory check may flag an approved execution as referencing now-stale
> data, but only a human explicitly calling `supersede` marks it.

4D-3 draft answers are pre-population only. Once submitted for review, responses are
locked. A reviewer who notices a release change can `return` the execution, triggering
re-entry in `draft` state — but 4D-3 does **not** auto-repopulate on return-to-draft;
the user must re-enter or the reviewer must note the stale data in the conclusion.

**Disclosure:** The population pass does not guarantee that draft answers remain current
after an FDA release supersession. This is a known, accepted limitation of the
draft-population model. It is disclosed here, not silently handled.

**Implementation requirement:** No auto-re-population on `return`. The advisory staleness
check is a 4D-4+ scope item.

---

### T-05: Applicability context injection (LOW — new surface in 4D-3)

**Attack:** The runtime evaluator receives a `context` dict assembled from
`FormulationVersion` fields. If a field is attacker-controlled (e.g. a `product.route`
value that could be set to an unusually long string or contains SQL-like patterns), it
might affect the evaluation.

**Mitigation:** The evaluator is a pure Python dispatch table with no `eval`, no `exec`,
no SQL generation, and no dynamic attribute access. Comparison operations (`eq`, `neq`,
etc.) use Python's native `==`, `in`, etc. against string/bool/number values from the
`FormulationVersion` model fields, which are validated and stored at form entry time.
There is no secondary interpretation of these values; they are never treated as code.

**Residual risk:** None. A long string in `product.route` simply fails an `eq` check;
it cannot alter the evaluator's control flow.

---

### T-06: `CalculationOutcome` partial-update race (MEDIUM — new surface in 4D-3)

**Attack:** Two concurrent `enter_response()` calls on the same `draft` execution
both trigger cascade recalculation of the same `SYSTEM_CALCULATED` question. The result
is a race between two updates to the same `CalculationOutcome` row.

**Mitigation:** Following the recommendation in OQ-3 (§4d of the discovery document),
cascade recalculation runs inside the same `transaction.atomic()` as the triggering
`enter_response()` call, with a `select_for_update()` on the `ChecklistExecution` row
before any calculation update. This serializes concurrent recalculations on the same
execution.

**Implementation requirement:** The cascade recalculation path must acquire
`select_for_update()` on the `ChecklistExecution` before reading any `ChecklistResponse`
values used as calculation inputs. This is the same lock-ordering discipline already
established in `create_execution()` (4D-2 implementation spec §16).

**Residual risk after mitigation:** Low, consistent with the concurrency model already
in use for execution lifecycle transitions.

---

### T-07: FDA source reading outside tenant boundary (MEDIUM — informational)

**Attack:** The population pass reads `fda_data` models (`IIDIngredient`,
`IIDPrecedentRecord`, `SubstanceSynonymMapping`) that are platform-level, not
tenant-scoped. A malicious implementation might inadvertently expose cross-tenant data
through a populated answer's `raw_value`.

**Mitigation:** FDA data (`fda_data` app) is platform-level by design — it is not
tenant-scoped. Tenants are not in competition over which FDA records they can read; all
active FDA data is equally available to all tenants through the governed read-path APIs.
The import-linter contract (`iig_checklist` may import `fda_data` read-only services)
is the established control. No tenant's answers can expose another tenant's formulation
data because the population pass only reads from the current execution's pinned
`FormulationVersion`, which has already passed the `formulation_version.product.tenant == execution.tenant`
check at execution creation time.

**Residual risk:** None beyond the pre-existing platform design.

---

### T-08: `source_assessment_snapshot_public_id` pointing at another tenant's snapshot (LOW)

**Attack:** If the population pass uses OQ-4 Option A (snapshot-first) and resolves an
`AssessmentSnapshot` by UUID, a crafted UUID could point at another tenant's snapshot.

**Mitigation:** `AssessmentSnapshot` has a `tenant` FK. Any snapshot lookup in the
population pass must filter by `tenant = execution.tenant`. If Option B (live-first)
is chosen, this threat does not exist — a new snapshot is always created for the current
execution's tenant.

**Residual risk (if OQ-4 = Option A):** Must add explicit tenant filter to snapshot
lookup. If OQ-4 = Option B, this risk is eliminated by construction.

---

### T-09: Frontend — fabricated calculation value display (HIGH — mitigated by design)

**Attack:** A frontend implementation that evaluates calculation formulas locally
(in JavaScript) and displays a result without waiting for the server could display a
wrong value (e.g. due to floating-point vs. Decimal precision divergence) that is then
treated by the user as the authoritative result.

**Mitigation:** Per 4D-3 discovery §8: "No formula logic in the frontend — the frontend
is a display layer only; all calculation logic lives in the backend." The frontend must
reload `CalculationOutcome.value` from the server after every PATCH that triggers
recalculation. It must never compute a formula result client-side.

**Implementation requirement (mandatory acceptance criterion):** No frontend code may
implement any of the six calculation formulas. The response after a PATCH to a
`USER_REQUIRED` field must include the server-updated `CalculationOutcome` values (or
the frontend must re-fetch the response list). Any PR reviewer must explicitly check for
the absence of calculation logic in frontend code.

---

## 3. Risks Inherited from Prior Milestones (not re-analyzed)

| Inherited risk | Source | Status |
|---|---|---|
| Malware scanning of evidence attachments is stub-only | 4D design §15 / 4D-2 discovery §3d | Pre-existing gap, unchanged by 4D-3 |
| `AssessmentSnapshot.clean()` guard unreachable in current codebase | 4D design §7 / 4D-2 impl spec §3 | 4D-3 must not repeat this; `full_clean()` required at every CalculationOutcome save |
| TenantMiddleware cross-tenant 403 vs. view 404 distinction | 4D-2 implementation | Pattern established, must be maintained in any new 4D-3 endpoints |
| No 21 CFR Part 11 e-signature | 4D design §20 | Pre-existing, unchanged |

---

## 4. Mitigations Summary

| Threat | Severity | Mitigation | Status |
|---|---|---|---|
| T-01: Forged FDA-derived answer | HIGH | Service-layer data_source_type_snapshot check | Design-complete in 4D-2; 4D-3 must not weaken |
| T-02: Forged calculation result | HIGH | No client endpoint for CalculationOutcome; structural exclusion | Design-complete in 4D-2 |
| T-03: Cascade loop from cyclic binding | MEDIUM | DAG acyclicity check at activation; unit test with planted cycle | New in 4D-3; implementation requirement |
| T-04: Stale FDA data in draft | MEDIUM | Disclosed limitation; no auto-repopulate on return | Accepted design |
| T-05: Applicability context injection | LOW | Pure Python dispatch, no eval/exec | No action required |
| T-06: CalculationOutcome race | MEDIUM | select_for_update() on execution before cascade; in-transaction | Implementation requirement (OQ-3 = Option A) |
| T-07: FDA data cross-tenant read | MEDIUM | FDA data is platform-level by design; no tenant isolation applies | No action required |
| T-08: Snapshot cross-tenant read | LOW | Tenant filter on snapshot lookup; eliminated if OQ-4 = Option B | Resolution via OQ-4 |
| T-09: Client-side formula evaluation | HIGH | Mandatory acceptance criterion: no formula logic in frontend | Implementation requirement |
