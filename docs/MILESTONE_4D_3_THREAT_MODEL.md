# Milestone 4D-3 Threat Model

**Status: DISCOVERY COMPLETE. Pending second adversarial review before implementation specification.**

**Discovery document:** `docs/MILESTONE_4D_3_DISCOVERY.md`
**Branch:** `regx/feat/milestone-4d-3-discovery`

This threat model covers the security and data-integrity risks introduced by the new
4D-3 attack surface: the draft-answer population pass, the automatic `FDA_DERIVED_DEFAULT`
resolver, the `SYSTEM_CALCULATED` computation layer, the `CALCULATION_BINDING_REGISTRY`,
the `CalculationStatus` translation layer, the applicability runtime evaluator, and the
in-draft cascade recalculation path. Risks already present in 4D-1 and 4D-2 are not
re-analyzed here; only incremental 4D-3 surface is covered.

---

## 1. Scope

4D-3 introduces the following new behavioral surface:

- A server-side population pass that reads governed FDA data and formulation fields, then
  writes draft answers into `ChecklistResponse` and `CalculationOutcome` rows.
- A server-side `CALCULATION_BINDING_REGISTRY` that maps short identifier strings to
  approved calculation functions and input resolvers.
- A `CalculationStatus` translation layer that maps engine result strings to the
  `iig_checklist.enums.CalculationStatus` stored model values.
- A cascade recalculation triggered by `enter_response()` on `draft` executions.
- A new applicability runtime evaluator (pure function against an in-memory context dict)
  returning `ApplicabilityOutcome` (`APPLICABLE`, `NOT_APPLICABLE`, `REVIEW_REQUIRED`).
- New `CalculationOutcome` serialization in the response-list/detail API.
- New frontend display of auto-populated answers and calculation results.

4D-3 does not introduce:

- New database models or migrations (no new table attack surface).
- New user-facing write endpoints for calculation data.
- New authentication or authorization logic (no new permission codenames).
- Asynchronous execution paths.

---

## 2. Threat Inventory

### T-01: Forged FDA-derived answer (HIGH — mitigated by design)

**Attack:** A malicious Doer sends a crafted PATCH to a `FDA_DERIVED_DEFAULT` question
response, supplying a `raw_value` that differs from the governed FDA data, in an attempt
to inject a false identity match or precedent result into the checklist.

**Preventive control (already in 4D-2):** `enter_response()` rejects any `raw_value` for a
`FDA_DERIVED_DEFAULT` question from a `Doer`-level actor. Only a `REVIEWER_CONFIRMED`
actor may override a `FDA_DERIVED_DEFAULT` answer, and only through the override path
(4D-4 scope). In 4D-3, the population pass runs server-side; no client-supplied value
is accepted for `FDA_DERIVED_DEFAULT` questions during population.

**Detective control:** `data_source_type_snapshot` is frozen at answer time and surfaced
in the API. The `iig_checklist.response.fda_populated` audit event (distinct from
`response.entered`) makes system-generated values auditable.

**Implementation requirement:** `enter_response()` must explicitly check
`data_source_type_snapshot == "fda_derived_default"` and reject any PATCH with a
`raw_value` unless the actor has the override permission (4D-4 path). This check must be
enforced in the service layer, not only in the serializer.

**Test mapping:** `test_population_service.py` — attempt to PATCH a `FDA_DERIVED_DEFAULT`
response from a Doer actor; assert 400/rejected.

**Residual risk:** None beyond what is already present in 4D-2. The frozen
`data_source_type_snapshot` makes provenance visible and auditable.

---

### T-02: Forged calculation result (HIGH — mitigated by design)

**Attack:** A client attempts to supply a `raw_value` for a `SYSTEM_CALCULATED` question
to inject a false calculation result, or to PATCH a `CalculationOutcome` row directly.

**Preventive control (already in 4D-2):** `ChecklistResponseUpdateSerializer` rejects
any non-null `raw_value` for `calculated_value`, `calculated_status`, and
`approval_metadata` answer types with `error_code = "invalid_raw_value_shape"` / 400.
No client-facing endpoint accepts `CalculationOutcome` input. 4D-3 populates
`CalculationOutcome` rows server-side only. No generic `PATCH`/`PUT` endpoint for
`CalculationOutcome` is permitted.

**Detective control:** `CalculationOutcome.source_assessment_snapshot_public_id` and
`inputs` / `input_provenance` fields provide an auditable trail of what was computed
and from what source.

**Residual risk:** None. The constraint is structural — the `CalculationOutcome` write
path is not reachable from any client-facing endpoint.

**Test mapping:** API test asserting that PATCH to `CalculationOutcome` resource returns
404 or 405.

---

### T-03: Cascade recalculation loop (MEDIUM — mitigated by activation-time DAG validation)

**Attack:** A crafted `ChecklistVersion` definition creates a circular dependency in the
`CALCULATION_BINDING_REGISTRY` dependency declarations (question A's calculation depends
on question B, whose calculation depends on question A). When `enter_response()` triggers
a cascade, the recalculation loop does not terminate.

**Preventive control:** Acyclicity is enforced at `ChecklistVersion` activation time by
validating the dependency graph formed by all `calculation_binding_identifier` registry
entries across all questions in the version. A cycle is rejected with a structured error.
The registry itself must never allow `SYSTEM_CALCULATED`-to-`SYSTEM_CALCULATED`
dependencies if that constraint is adopted; either way, the activation-time DAG check is
the primary gate.

**Detective control:** Activation-time validation produces a structured error code that
is auditable. A defensive visited-set check in the recalculation loop provides a runtime
backstop against registry/activation-check bugs.

**Implementation requirement:** The activation-time DAG check must be unit-tested with
a planted cyclic fixture (A depends on B, B depends on A). The defensive runtime cycle
check must also be tested independently.

**Test mapping:** `test_execution_lifecycle.py` — activate a `ChecklistVersion` with a
planted cycle; assert activation is rejected with a structured error. `test_recalculation.py`
— defensive runtime check.

**Residual risk after mitigation:** Low. A malicious `platform_master` author could
theoretically submit a cyclic definition, but this is blocked at activation.

---

### T-04: Stale FDA data used in population (MEDIUM — accepted design limitation)

**Attack (data-integrity risk, not external attack):** The population pass calls
`resolve_substance_identity()` and `find_iid_candidates()` against the current active
FDA release. If the active release changes between execution creation and submission
for review, the draft answers may reference data from a release that is no longer active.

**Preventive control:** OQ-4 live-first design ensures that the snapshot used at
population time reflects the active release at that moment. Once submitted for review,
responses are locked. A reviewer who notices a release change can `return` the execution.

**Detective control:** `CalculationOutcome.source_assessment_snapshot_public_id` records
which snapshot was used. If the active release changes, a future lookup can identify
executions whose snapshot references a superseded release.

**Implementation requirement:** No auto-re-population on `return`. The advisory staleness
check is 4D-4+ scope. Historical approved and terminal executions must never be
automatically recalculated when source data changes.

**Residual risk:** Known, accepted limitation of the draft-population model. Disclosed.

---

### T-05: Applicability context injection (LOW — mitigated by pure-function design)

**Attack:** The runtime evaluator receives a context dict assembled from
`FormulationVersion` fields. If a field value contains an unusually long string or
SQL-like patterns, it might affect evaluation.

**Preventive control:** The evaluator is a pure Python dispatch table with no `eval`,
no `exec`, no SQL generation, and no dynamic attribute access. Comparison operations
use Python's native `==`, `in`, etc. against values from the `FormulationVersion` model
fields, which are validated and stored at form-entry time. There is no secondary
interpretation of these values as code.

**Applicability grammar — forged context field attack:** If a client-controlled value
(e.g. a `product.route` set to an unusually long or SQL-like string) is used as a
context field, it simply fails an `eq` comparison; it cannot alter the evaluator's
control flow or generate a query.

**Detective control:** The evaluator returns an `ApplicabilityOutcome` value; any
unexpected outcome is auditable through the `not_applicable_reason` stored on the
`ChecklistResponse` row.

**Residual risk:** None. A long string in `product.route` fails the comparison; it
cannot alter control flow.

**Test mapping:** `test_applicability_evaluator.py` — long-string and special-character
context values produce expected comparison failures.

---

### T-06: `CalculationOutcome` partial-update race (MEDIUM — mitigated by lock order)

**Attack:** Two concurrent `enter_response()` calls on the same `draft` execution both
trigger cascade recalculation of the same `SYSTEM_CALCULATED` question. The result is a
race between two updates to the same `CalculationOutcome` row.

**Preventive control (OQ-3 resolved):** Cascade recalculation runs inside the same
`transaction.atomic()` as the triggering `enter_response()` call, with
`select_for_update()` on the `ChecklistExecution` row before any calculation update.
This serializes concurrent recalculations on the same execution.

**Lock order:** `ChecklistExecution` → affected `ChecklistResponse` rows → `CalculationOutcome`
rows (in stable pk order). This order must be maintained consistently to prevent deadlocks.

**Detective control:** Database-level locking prevents silent partial writes. Any failed
transaction is rolled back atomically.

**Test mapping:** `test_recalculation.py` — concurrent `enter_response()` calls with
`transaction=True`; assert only one recalculation wins and results are consistent.

**Residual risk after mitigation:** Low. Consistent with the concurrency model already
established in 4D-2.

---

### T-07: FDA source reading outside tenant boundary (MEDIUM — informational)

**Attack:** The population pass reads `fda_data` models that are platform-level (not
tenant-scoped). A malicious implementation might inadvertently expose cross-tenant data
through a populated answer's `raw_value`.

**Preventive control:** FDA data (`fda_data` app) is platform-level by design — all
active FDA data is equally available to all tenants through the governed read-path APIs.
The import-linter contract (`iig_checklist` may import `fda_data` read-only services)
is the established control. No tenant's answers can expose another tenant's formulation
data because the population pass only reads from the current execution's pinned
`FormulationVersion`, which has already passed the `formulation_version.product.tenant == execution.tenant`
check at execution creation.

**Residual risk:** None beyond the pre-existing platform design.

---

### T-08: `source_assessment_snapshot_public_id` pointing at another tenant's snapshot (LOW)

**Attack:** The live-first population pass resolves an `AssessmentSnapshot` by
`(FormulationComponent, active_release)` key. A crafted lookup could match a snapshot
belonging to another tenant.

**Preventive control (OQ-4 resolved — live-first):** Any `AssessmentSnapshot` lookup
in the population pass must include `tenant = execution.tenant` as an explicit filter.
A snapshot from another tenant must never be used as the source for a calculation. The
live-first approach means new snapshots are always created for the current tenant; the
risk is limited to the exact-match reuse path.

**Detective control:** `source_assessment_snapshot_public_id` on the `CalculationOutcome`
row records the snapshot used; a cross-tenant mismatch would be detectable in an audit.

**Implementation requirement:** Any `AssessmentSnapshot.objects.get_or_create()` or
equivalent in the population pass must include `tenant=execution.tenant` in the lookup.

**Test mapping:** `test_population_service.py` — assert that a snapshot belonging to
another tenant is not reused; a new snapshot is created for the current tenant.

**Residual risk:** Low. Explicit tenant filter enforced at the query level.

---

### T-09: Frontend — fabricated calculation value display (HIGH — mitigated by design)

**Attack:** A frontend implementation that evaluates calculation formulas locally
(in JavaScript) and displays a result without waiting for the server could display a
wrong value (due to floating-point vs. Decimal precision divergence, or using stale
data) that is then treated by the user as the authoritative result.

**Preventive control:** Per 4D-3 discovery §8: "No formula logic in the frontend — the
frontend is a display layer only; all calculation logic lives in the backend." The
frontend must reload `CalculationOutcome.value` from the server after every PATCH that
triggers recalculation. It must never compute a formula result client-side.

**Implementation requirement (mandatory acceptance criterion):** No frontend code may
implement any of the six calculation formulas. The response after a PATCH to a
`USER_REQUIRED` field must include the server-updated `CalculationOutcome` values (or
the frontend must re-fetch). Any PR reviewer must explicitly check for the absence of
calculation logic in frontend code.

**Test mapping:** Vitest/RTL — assert no formula name appears in any frontend source
file. Playwright E2E — after PATCH, assert `SYSTEM_CALCULATED` field value matches server
response, not a locally computed result.

**Residual risk:** None through design enforcement.

---

### T-10: Incorrect status translation (MEDIUM — new in 4D-3)

**Attack / failure mode:** A defect in the `CalculationStatus` translation layer causes
a blocked or unresolved calculation to be mapped to `"complete"` instead of `"error"`.
This would persist a `CalculationOutcome` with `status = "complete"` and a non-null
`value` for a calculation that actually failed, potentially causing a reviewer to accept
a fabricated result.

**Preventive controls:**
- The translation function is an explicit allow-listed dict (not a default-to-success
  fallback). Unknown engine status strings fail closed to `"error"` — never to
  `"complete"`.
- `full_clean()` is called before every `CalculationOutcome.save()`. If the translated
  status value is not one of the four valid `iig_checklist.enums.CalculationStatus`
  choices, `full_clean()` raises `ValidationError` and aborts the write.
- `value` must remain `None` when `status = "error"` or `status = "data_required"`;
  the implementation must enforce this explicitly in the translation function.

**Detective controls:**
- Unit tests for every engine status string (including all aliases) verify that the
  correct stored `(status, reason_code)` pair is produced.
- A planted-failure test verifies that an unknown engine status string maps to `"error"`,
  not `"complete"`.
- Existing tests that assert `CalculationOutcome.value` is `None` for blocked outcomes
  provide a second layer of detection.

**Severity:** MEDIUM. The translation layer is a small, exhaustively testable function.
The main risk is an incomplete mapping (a new engine status string added without updating
the translation table). Mitigation: fail-closed default.

**Test mapping:** `test_planted_failures_4d3.py` — one test per engine status string.
`test_population_service.py` — unknown engine status fails closed to `"error"`.

**Residual risk after mitigation:** Low. Fail-closed design and exhaustive tests.

---

### T-11: Unknown or mismatched registry identifier (MEDIUM — new in 4D-3)

**Attack / failure mode:** A `ChecklistQuestion.calculation_binding_identifier` value in
a stored `ChecklistVersion` does not match any entry in the `CALCULATION_BINDING_REGISTRY`
(e.g. a registry entry was renamed in a code deployment, or a record was migrated with
an incorrect identifier). The population pass would fail to find the calculation function.

**Preventive controls:**
- Activation-time validation rejects any `SYSTEM_CALCULATED` question whose
  `calculation_binding_identifier` is not present in the `CALCULATION_BINDING_REGISTRY`.
  A `ChecklistVersion` with unknown identifiers cannot be activated.
- At runtime, an unknown identifier encountered during population or recalculation must
  fail closed: `CalculationOutcome.status = "error"`, `reason_code = "UNKNOWN_REGISTRY_IDENTIFIER"`.
  It must not raise an unhandled exception that aborts the entire execution creation.

**Detective controls:**
- Activation-time validation produces a structured, auditable error when an unknown
  identifier is detected.
- Runtime error in `CalculationOutcome.reason_code` is visible in the API response.

**Test mapping:** `test_execution_lifecycle.py` — activate a `ChecklistVersion` with an
unknown `calculation_binding_identifier`; assert activation is rejected. `test_population_service.py`
— population with an unknown identifier at runtime sets `status = "error"`.

**Residual risk:** Low. Activation-time gate prevents unknown identifiers from reaching
production `ChecklistVersion` records in normal operation.

---

### T-12: Repeated recalculation denial of service (LOW — bounded by design)

**Attack:** A malicious or buggy client rapidly submits PATCH requests to `USER_REQUIRED`
responses on a `draft` execution, triggering repeated cascade recalculations and
overloading the database with write operations.

**Preventive controls:**
- Cascade recalculation is bounded at activation time by the maximum dependency depth
  and maximum affected-node count (§4d of discovery document). No unbounded cascade is
  possible for an activated `ChecklistVersion`.
- The `select_for_update()` on `ChecklistExecution` serializes concurrent writes — a
  second PATCH on the same execution must wait for the first to commit before proceeding.
- Standard API rate-limiting applies (pre-existing platform control, not 4D-3 scope).

**Detective controls:**
- Slow query monitoring on the `enter_response()` path.
- Rate-limiting logs at the API gateway level.

**Test mapping:** `test_recalculation.py` — concurrent PATCH calls; assert serialized
execution via lock ordering.

**Residual risk:** Low. Bounded cascade + serialized writes prevent runaway behavior.

---

### T-13: Generated_at timestamp injection or parse failure (LOW — new in 4D-3)

**Attack / failure mode:** `CalculationResult.generated_at` is an ISO 8601 string
produced by the calculation engine. A defect in parsing (or an unexpected format)
could store a `None` in `CalculationOutcome.generated_at` or silently corrupt the
timestamp field.

**Preventive controls:**
- The implementation must explicitly parse the ISO 8601 string to a timezone-aware
  `datetime` before assignment (§4f of discovery document).
- Naive timestamps are rejected (the calculation functions always produce UTC; a naive
  timestamp indicates a code defect).
- Malformed strings fall back to `None` (not an exception that aborts the population pass).
- `generated_at` is not client-supplied; it originates from the server-side calculation
  function.

**Detective controls:**
- Unit tests for timezone-aware parsing and malformed-value handling.
- Monitoring for `generated_at = None` on `status = "complete"` rows (should not occur
  in normal operation).

**Residual risk:** Low. Server-generated values only; malformed input falls back safely.

---

### T-14: Duplicate `CalculationOutcome` creation (LOW — mitigated by existing constraint)

**Attack / failure mode:** A concurrent population pass for the same execution creates
two `CalculationOutcome` rows for the same `(response, calculation_name)` pair.

**Preventive control (already in 4D-2):** `CalculationOutcome` has an implicit FK to
`ChecklistResponse`, and 4D-2's `create_execution()` creates `CalculationOutcome` rows
at execution creation time. 4D-3 updates existing rows (not creates new ones). The
`select_for_update()` on `ChecklistExecution` (T-06 mitigation) serializes concurrent
updates.

**Residual risk:** Low. Row creation is in 4D-2; 4D-3 only updates existing rows.

---

### T-15: Stale source approval — source data deleted or replaced post-snapshot (LOW)

**Attack / failure mode:** The `IIDPrecedentRecord` or `IIDIngredient` used as the
basis for a `CalculationOutcome` is withdrawn or replaced in the FDA source after the
snapshot was taken and the execution was submitted for review.

**Preventive controls:**
- `CalculationOutcome.source_assessment_snapshot_public_id` records the snapshot used.
  The snapshot is immutable once created.
- Once an execution is submitted for review or approved, its responses are locked.
- The staleness advisory check (flagging executions that reference now-superseded data)
  is a 4D-4+ scope item; 4D-3 discloses and accepts this limitation.

**Residual risk:** Medium for long-running executions in draft state during an FDA
release transition. Accepted design limitation (T-04); no additional mitigation in 4D-3.

---

## 3. Risks Inherited from Prior Milestones (not re-analyzed)

| Inherited risk | Source | Status |
|---|---|---|
| Malware scanning of evidence attachments is stub-only | 4D design §15 / 4D-2 discovery §3d | Pre-existing gap, unchanged by 4D-3 |
| `AssessmentSnapshot.clean()` guard unreachable in current codebase | 4D design §7 / 4D-2 impl spec §3 | 4D-3 must not repeat this; `full_clean()` required at every `CalculationOutcome` save |
| TenantMiddleware cross-tenant 403 vs. view 404 distinction | 4D-2 implementation | Pattern established; must be maintained in any new 4D-3 endpoints |
| No 21 CFR Part 11 e-signature | 4D design §20 | Pre-existing, unchanged |

---

## 4. Mitigations Summary

| Threat | Severity | Primary control | Detective control | Test mapping | Residual risk |
|---|---|---|---|---|---|
| T-01: Forged FDA-derived answer | HIGH | Service-layer `data_source_type_snapshot` check; population is server-side | `fda_populated` audit event | `test_population_service.py` | None |
| T-02: Forged calculation result | HIGH | No client endpoint for `CalculationOutcome`; no PATCH route | `source_assessment_snapshot_public_id` trail | API test 405/404 | None |
| T-03: Cascade loop from cyclic binding | MEDIUM | DAG acyclicity check at activation | Structured activation error | `test_execution_lifecycle.py` (cyclic fixture) | Low |
| T-04: Stale FDA data in draft | MEDIUM | Live-first snapshot (OQ-4); lock on submission | Snapshot public ID auditable | N/A (accepted) | Medium — accepted |
| T-05: Applicability context injection | LOW | Pure Python dispatch, no eval/exec | `not_applicable_reason` auditable | `test_applicability_evaluator.py` | None |
| T-06: `CalculationOutcome` race | MEDIUM | `select_for_update()` on execution; in-transaction (OQ-3) | Serialized writes | `test_recalculation.py` (concurrent) | Low |
| T-07: FDA data cross-tenant read | MEDIUM | FDA data is platform-level by design; import-linter contract | Audit trail on `fda_populated` event | N/A (design) | None |
| T-08: Snapshot cross-tenant read | LOW | Explicit `tenant=execution.tenant` filter on snapshot lookup | Snapshot public ID auditable | `test_population_service.py` | Low |
| T-09: Client-side formula evaluation | HIGH | No formula logic in frontend; server reload after PATCH | Code-level lint rule | Vitest no-formula test; Playwright E2E | None |
| T-10: Incorrect status translation | MEDIUM | Exhaustive allow-list; fail-closed default; `full_clean()` | Planted-failure tests | `test_planted_failures_4d3.py` | Low |
| T-11: Unknown registry identifier | MEDIUM | Activation-time validation; runtime fail-closed to `"error"` | `reason_code` in API response | `test_execution_lifecycle.py`; `test_population_service.py` | Low |
| T-12: Repeated recalculation DoS | LOW | Bounded cascade; `select_for_update()` serialization | Slow-query monitoring | `test_recalculation.py` (concurrent) | Low |
| T-13: `generated_at` parse failure | LOW | Server-generated timestamp only; malformed fallback to `None` | Unit tests; monitoring | `test_population_service.py` | Low |
| T-14: Duplicate `CalculationOutcome` | LOW | Row created at execution creation (4D-2); 4D-3 updates only | Existing FK constraint | `test_population_service.py` | Low |
| T-15: Source deleted/replaced post-snapshot | LOW | Immutable snapshot reference; submission lock | Snapshot public ID auditable | N/A (accepted limitation) | Medium — accepted |
