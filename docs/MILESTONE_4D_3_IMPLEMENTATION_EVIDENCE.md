# Milestone 4D-3 — Implementation Evidence

**Status: FOUNDATION LAYER + REGISTRY ACTIVATION VALIDATION. Runtime calculation, response-update, snapshot, outcome, rebinding and frontend layers deferred.**

**Approved specification head:** `97653c09456d04fd194d060d29765f052a721405`
**Implementation branch:** `regx/feat/milestone-4d-3`
**Base:** `regx-main` @ `c0adef4448153368c5bb280219c154f60be052f1`

This document records exactly what was implemented, what was verified, and what
could not be verified in this environment. It does not alter the normative
meaning of any approved specification document.

---

## 1. Environment evidence

Database-backed verification is **impossible** in this environment. Evidence
gathered before any code was written:

| Probe | Result |
|---|---|
| TCP 5432 / 5433 / 54320 | all closed |
| Windows service `*postgres*` | none present |
| `psql` on PATH | not found |
| Docker daemon (`npipe:////./pipe/docker_engine`) | "The system cannot find the file specified" |
| Docker Desktop | not installed (CLI 29.5.3-rd present, no engine) |
| Python / Node | 3.13.14 / v24.14.1 — both available |

`backend/regx/settings/test.py` pins `django.db.backends.postgresql`, and
`common/tests/test_guards.py::TestNoSQLiteInSettings` actively prohibits a
SQLite fallback. `pyproject.toml` sets `--cov-fail-under=55`, which requires the
full suite to execute. No threshold was lowered and no database was mocked to
manufacture coverage.

---

## 2. Database-free boundary

The boundary preserves the approved architecture; no model-dependent behaviour
was relocated into a pure layer to dodge the database requirement.

**A — pure, import with no Django at all** (verified by importing with
`DJANGO_SETTINGS_MODULE` unset):
`iid_assessment.unit_conversion`, `iid_assessment.calculations`.

**B — needs Django settings, but no database connection:**
`iig_checklist.enums`, `applicability`, `execution_constants`, `field_registry`,
`codes`.

**C — deferred, genuinely require ORM / transactions / request handling:**
`services.py`, `views.py`, `serializers.py`, `models.py`, and every 4D-3 service
that reads or writes rows.

All six modules added in this run sit in band A or B.

---

## 3. Modules implemented

| Module | Purpose | Requirement IDs |
|---|---|---|
| `backend/iig_checklist/calculation_translation.py` | Engine→stored status translation, `generated_at` parsing, three closed vocabularies, 29-row deterministic failure mapping | M4D3-TRL-001..006, RSN-001..011, IFV-001..008 |
| `backend/iig_checklist/governed_vocabularies.py` | History and service-detail vocabularies, cross-vocabulary separation guard | M4D3-HST-005, RSN-011/012 |
| `backend/iig_checklist/calculation_registry.py` | Six approved bindings, resolver declaration validation, graph limits, import-time self-check | M4D3-REG-001..020, INP-001..009, MAP-001..010, FCR-002..014, TRG-001..007, UNC-003/006 |
| `backend/iig_checklist/calculation_graph.py` | Pure graph construction, topological ordering, cycle/depth/cascade validation, trigger expansion | M4D3-DEP-001..012, DAG-003..010, RCL-006/007 |
| `backend/iig_checklist/max_daily_units.py` | Conservative worst-case selection over supplied immutable candidates | M4D3-MDU-001..024 |
| `backend/iig_checklist/unit_adapter.py` | Thin adapter over the approved conversion service; reason-code translation | M4D3-UNC-001..011 |

**No second conversion table was created** — `unit_adapter` delegates entirely to
`iid_assessment/unit_conversion.py` and reuses its canonical units
(`gram`, `milligram`, …) and `ConversionReasonCode` values.

**No calculation formula was rewritten** — all six approved functions in
`iid_assessment/calculations.py` are referenced directly by the registry and
verified to match their declared `calculation_name` via `function.__name__`.

### Verified counts

| Vocabulary | Count |
|---|---|
| `ALLOWED_REASON_CODES` | 19 |
| `ALLOWED_RESOLVER_DETAIL_CODES` | 6 |
| `ALLOWED_HISTORY_REASON_CODES` | 2 |
| `ALLOWED_SERVICE_DETAIL_CODES` | 1 |
| `ALLOWED_INPUT_FAILURE_CODES` | 29 |
| `INPUT_FAILURE_MAPPING` rows | 29 |
| Registry entries | 6 |

All match the approved specification exactly. Nothing was silently adjusted.

---

## 4. Gates actually run

| Gate | Command | Result |
|---|---|---|
| Database-free unit tests | `python -m pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **182 passed** |
| Existing DB-free regression | `python -m pytest common/tests/test_guards.py iig_checklist/tests/test_compatibility.py iid_assessment/tests -k "not django_db" --no-cov -q` | **172 passed, 36 deselected** — no regression |
| Ruff | `python -m ruff check <six modules + test file>` | **All checks passed** |
| Import-linter | `.venv\Scripts\lint-imports.exe` | **7 contracts kept, 0 broken** |
| Migration check | `python manage.py makemigrations --check --dry-run` | **`No changes detected`, exit code 0** |

**Migration check — scope of the assertion.** The command completed (exit 0) but
emitted `RuntimeWarning: Got an error checking a consistent migration history
performed for database connection 'default': connection timeout expired`. Django
degraded gracefully: it could **not** verify applied migration *history* against
a live database, but it **did** complete the model-state-versus-migration-files
comparison, which is precisely the question "does this change require a new
migration?". That comparison returned `No changes detected`. The gate is
therefore genuinely PASS for the no-migration constraint, and separately
unverified for migration-history consistency, which needs PostgreSQL.

The test run is itself the proof of database-independence: it passes with **no
PostgreSQL running at all**. The test module contains no `django_db` marker, no
`TestCase`, no `.objects.` call, no factory and no mock.

### Gates blocked

| Gate | Status |
|---|---|
| Targeted 4D-3 DB tests | BLOCKED — PostgreSQL unavailable |
| Complete backend suite | BLOCKED — PostgreSQL unavailable |
| Coverage (`--cov-fail-under=55`) | BLOCKED — PostgreSQL unavailable |
| Migration *history* consistency | BLOCKED — PostgreSQL unavailable (model-state check itself passed, see above) |
| Frontend Vitest / typecheck / lint | NOT RUN — no frontend file changed in this run |
| Playwright E2E | BLOCKED — needs a running backend + database |
| Docker smoke | BLOCKED — Docker daemon unavailable |

Absence of schema change is therefore established two independent ways: the
`makemigrations --check` model-state comparison returned `No changes detected`,
and structurally `git status --porcelain` shows seven new files, none under any
`migrations/` directory and none touching a `models.py`.

---

## 5. Deferred layers (require ORM or transactions)

Deliberately **not** implemented in this run, per the stop condition:

- `resolve_calculation_inputs()` as an ORM service, and every resolver form that
  reads persisted rows: `question_response`, `formulation_field`,
  `maximum_daily_units` collection, `assessment_snapshot`, `calculation_outcome`,
  and component-reference ownership checks.
- `update_checklist_response()` governed service and the
  `ChecklistResponseUpdateView` thin adapter.
- `create_execution()` correction writing `entry.calculation_name`.
- Applicability persistence, the `REVIEW_REQUIRED:` marker, and submission gates.
- Completeness-gate extension in `_check_execution_completeness()`.
- Governed `AssessmentSnapshot` creation and the transaction-scoped context.
- `CalculationOutcome` persistence and provenance writing.
- History helper persistence and component rebinding.
- Serializers, API representation and all frontend work.

~~Activation-time validation of registry question codes~~ — **delivered in §6A.**
This was the mandatory prerequisite; it is no longer deferred.

~~**Next layer:** ORM-backed `resolve_calculation_inputs()`~~ — **delivered in
§6D.** Activation proves the bindings are sound; input resolution now reads them
from persisted rows. Execution and persistence remain deferred.

No fake repository, stub or mock was introduced as a production stand-in.

---

## 6. Implementation notes for the next reviewer

1. **Registry question codes — activation validation is DEFERRED, not
   implemented.** `Q_SUBJECT_COMPONENT` and `Q_DAILY_EXPOSURE` are structural
   governed binding constants in the pure registry. They are **not** mandated by
   the approved specification and have **not** been verified against any
   existing checklist fixture or approved `ChecklistVersion`.

   Accurate current state:

   - No production consumer activates or executes the registry — grep confirms
     nothing outside the six foundation modules imports them, so they are inert.
   - The foundation validates **only internal declaration consistency**: that
     `calculation_dependencies` match the form E resolvers and that
     `recalculation_triggers` match the form A resolvers plus component
     selectors (M4D3-TRG-006).
   - Activation-time validation against an approved `ChecklistVersion`
     (M4D3-REG-018) is **deferred to the ORM/service implementation phase**. It
     does not exist yet and must not be described as passing.
   - When implemented, that activation service **shall fail closed** if any
     referenced question code is absent from the version, duplicated, of the
     wrong `answer_type`, of the wrong `data_source_classification`, or
     otherwise incompatible.
   - This deferred control is **mandatory** before any registry entry can become
     active. Until it exists, no registry entry may be activated.

   If real approved checklist content uses different codes, only these two
   constants change — but the activation check is what makes that safe, and it
   is not yet built.

2. **A real defect the import-time self-check caught.** The first draft declared
   `recalculation_triggers = (Q_SUBJECT_COMPONENT, Q_DAILY_EXPOSURE)` on both MDE
   entries. M4D3-TRG-006 validation rejected it at import: per M4D3-MAP-010 the
   MDE calculations take no direct component input, so their only trigger is the
   upstream daily-exposure code. Corrected to `(Q_DAILY_EXPOSURE,)`. The cascade
   still reaches them — a component change recalculates `daily_exposure`, which
   propagates through `calculation_dependencies`.

3. **Conversion factor formatting.** `Decimal("2000")/Decimal("2")` renders as
   `1E+3`. Provenance in a regulated record must stay readable, so the adapter
   formats the factor with `f"{…:f}"` to force plain notation.

4. **Graph boundary coverage.** The six-entry production registry has a maximum
   chain depth of 2 and cannot express a depth-6 or 11-node graph, so
   `TestGraphDepthBoundary` and `TestGraphCascadeBoundary` build synthetic
   registry entries from an approved entry and drive them through the public
   graph API. A mutation probe confirmed the tests are meaningful: loosening the
   limits to 99 in memory makes five of them fail with `DID NOT RAISE`, while
   the intact guard passes 10/10.

5. **No suppressions remain in 4D-3 code.** The former `# noqa: E731` lambda is
   now the named predicate `is_canonical_code()`, directly covered by
   `TestCanonicalCodePredicate`. The two `# type: ignore` comments in
   `max_daily_units.py` were removed by declaring `_is_valid_decimal()` as a
   `TypeGuard[Decimal]`, which narrows properly at both call sites. The two in
   the test file were removed as inert — no type checker is configured in this
   repository.

6. **`makemigrations` attempts a database connection** even with
   `--check --dry-run`. It is slow rather than blocked: the connection attempt
   times out with a `RuntimeWarning`, then the command completes its model-state
   comparison normally. Allow roughly two minutes for it in an environment with
   no reachable database.

---

## 6A. ORM phase 1 — registry activation validation

### Environment change

PostgreSQL became available part-way through the milestone. **Rancher Desktop**
(already installed, container engine `moby`) exposes the standard
`npipe:////./pipe/docker_engine`, so `docker`, `docker compose`, `compose.yaml`
and CI all work unchanged — **no repository change and no per-device
configuration was required**. The project's own compose stack was already
running: `regx-postgres-1` (`postgres:16-alpine`, healthy, 5432) and
`regx-redis-1` (healthy, 6379).

Every earlier "BLOCKED — PostgreSQL unavailable" entry in this document refers to
the earlier database-free runs and is superseded from this section onward.

### Pre-change baseline (before any production code was touched)

| Check | Command | Result |
|---|---|---|
| System check | `manage.py check` | **no issues (0 silenced)** |
| Migration state | `manage.py makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `manage.py migrate --check` (real `regx` DB) | **exit 0**, zero unapplied |
| Full backend suite | `pytest -q` | **1102 passed**, 0 failed |
| Coverage | same run | **90.13%** against a 55% floor |
| Duration | same run | 332.6 s |

The baseline was green, so implementation proceeded.

### Integration point

`backend/iig_checklist/views.py` —
`_ChecklistVersionActionViewBase.post()`, the `VersionAction.ACTIVATE` branch.
This is the existing governed lifecycle transition; **no parallel activation
pathway was created** and no new lifecycle state was invented.

Validation is placed after the tenant-safe `select_for_update()` lookup, the
`_authorize_mutation()` permission check, `validate_version_transition()` and the
`effective_date` check — and **before** the first mutation, which is the
supersede-prior-active block. A failure therefore cannot supersede a prior active
version, cannot write lifecycle fields and cannot emit a success audit.

### Validator

`backend/iig_checklist/activation_validation.py` — read-only, opens no
transaction, emits no audit. Returns immutable, ordered `ValidationFinding`
records; `format_activation_errors()` shapes them into the structured
`REGISTRY_VALIDATION_FAILED` body.

**Verified schema fact driving the duplicate control:** question codes are unique
per **section** (`unique_iig_question_code_per_section`), *not* per version, so
one version may legitimately contain the same code in two sections. Every lookup
therefore collects **all** matches and fails on anything other than exactly one.
There is no `.first()` and no arbitrary selection anywhere in the module.

Controls enforced per referenced registry entry:

| Control | Code |
|---|---|
| Identifier resolves to an approved registry entry | `UNKNOWN_REGISTRY_IDENTIFIER` |
| Referenced question exists in this version | `QUESTION_CODE_MISSING` |
| Referenced code resolves to exactly one question | `QUESTION_CODE_DUPLICATE` |
| Bound question answer type matches the entry | `WRONG_ANSWER_TYPE` |
| Bound question classification matches the entry | `WRONG_SOURCE_CLASSIFICATION` |
| Form E target is `SYSTEM_CALCULATED` | `DEPENDENCY_NOT_CALCULATED` |
| Component selector is `FORMULATION_COMPONENT_REFERENCE` | `SELECTOR_WRONG_ANSWER_TYPE` |
| `registry_component_code` selector rejected | `DISABLED_SELECTOR_FORM` |
| `calculation_dependencies` match form E resolvers | `DEPENDENCY_MISMATCH` |
| `recalculation_triggers` match form A + selector resolvers | `TRIGGER_MISMATCH` |

The last three rows are **defensive**: `_validate_registry()` already rejects
those shapes at import time and the registry is immutable, so no approved entry
can reach them. They are proven in §6c through a synthetic registry rather than
left as untested assertions.

Only identifiers actually referenced by the version's questions are validated;
unreferenced registry entries never block activation.

### Deferred activation control — now IMPLEMENTED

The control recorded in §6 note 1 as deferred and **mandatory before any registry
entry can become active** is delivered by this section. Registry question codes
are no longer unvalidated against real checklist content: an activation
referencing a code that is absent, duplicated, of the wrong answer type or of the
wrong source classification now fails closed with zero mutation.

### Tests

`backend/iig_checklist/tests/test_4d3_activation_validation.py` — **26 tests,
real PostgreSQL**, no mocked QuerySets or managers. Covers valid activation and
success audit; missing selector, form E dependency and trigger questions;
duplicate codes across sections; wrong answer type;
non-calculated form E target; unknown identifier; the full
`daily_exposure → percentage_of_iid_mde` chain; cross-version and cross-tenant
isolation; permission denial; deterministic ordering; zero mutation on failure;
no success audit on failure; no supersede on failure; and sanitized structured
errors carrying public UUIDs only.

> **Corrected after independent review.** This paragraph originally also claimed
> "wrong classification" coverage. No test at this point reached
> `WRONG_SOURCE_CLASSIFICATION`; only `DEPENDENCY_NOT_CALCULATED` was exercised,
> and the two are different controls. The claim is removed here and the gap is
> closed in §6c.

### Post-change gates

| Gate | Command | Result |
|---|---|---|
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **26 passed** |
| Existing lifecycle / clone / platform-auth / execution API | `pytest test_lifecycle.py test_clone_api.py test_platform_mutation_authorization.py test_execution_api.py --no-cov -q` | **101 passed** |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **182 passed** |
| Full backend suite | `pytest -q` | **1128 passed**, 0 failed, 335.9 s |
| Coverage | same run | **92.59%** against a 55% floor |
| Ruff | `ruff check iig_checklist/` | **All checks passed** |
| Import-linter | `lint-imports.exe` | **7 kept, 0 broken** |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | **exit 0** |

Suite grew 1102 → 1128 (+26, the new activation tests) and coverage rose
90.13% → 92.59%. No threshold was lowered and no test was skipped or weakened.

**Two test defects were found and fixed in my own tests, not worked around.**
The endpoint base path is `/api/regx/v1`, not the `/api/v1` I first assumed. And
a cross-tenant isolation test initially used a reviewer, who is denied 403 by the
DRF class-level permission *before* the view body runs; the meaningful test uses
an actor who **does** hold activate permission but sits in another tenant, which
correctly yields 404 and proves tenant scoping rather than permission denial.

## 6c. Remediation of the independent review (FAIL → 2 Major, 4 Minor)

An independent adversarial review of the activation layer returned **FAIL**: 0
Critical, 2 Major, 4 Minor. This section records what was wrong, what changed and
how each finding is now proven. No specification document was altered.

### Major 1 — no calculation-graph validation at activation

**Finding.** M4D3-REG-018 requires activation to validate that the graph is
acyclic and within the Part 13 limits, and M4D3-DEP-005 places that validation at
activation. `calculation_graph.build_graph()` implemented exactly this and was
imported by the foundation test module *and nothing else*. The reviewer
demonstrated that a question with code `Q_DAILY_EXPOSURE` bound to
`percentage_of_iid_mde` — whose form E dependency is `Q_DAILY_EXPOSURE` — is a
self-edge that produced **zero findings** and activated.

**Change.** `_validate_calculation_graph()` in `activation_validation.py` builds
one `CalculationNode` per bound calculated question and calls the existing
`build_graph()`. No graph logic is reimplemented; the module only constructs the
node set and translates `GraphConfigurationError` into sanitized findings. Node
identity is the governed public response UUID, never the calculation function
name, so two questions bound to the same function stay distinct. Edges come only
from `calculation_dependencies`; recalculation triggers never become edges. The
returned graph object is never consumed — it is only proven valid — so no partial
graph result is used.

Questions whose identifier does not resolve are excluded from the node set: they
already fail activation on their own, and excluding them keeps one defect to one
finding. Overall behaviour remains fail-closed.

| Graph error | Structured code |
|---|---|
| `DEPENDENCY_CYCLE` | `CALCULATION_GRAPH_CYCLE` |
| `UNKNOWN_DEPENDENCY_CODE` | `UNKNOWN_DEPENDENCY_CODE` |
| `DEPENDENCY_DEPTH_EXCEEDED` | `DEPENDENCY_DEPTH_EXCEEDED` |
| `CASCADE_NODE_LIMIT_EXCEEDED` | `CASCADE_NODE_LIMIT_EXCEEDED` |
| `DUPLICATE_NODE` | `DUPLICATE_GRAPH_NODE` |
| `UNKNOWN_REGISTRY_IDENTIFIER` | `UNKNOWN_REGISTRY_IDENTIFIER` |

Messages are **authored here**, not taken from the exception: no raw exception
text, no node internals and no traceback reach the API body.

### Major 2 — form E producer was never verified

**Finding.** The validator confirmed the upstream question existed uniquely and
was `SYSTEM_CALCULATED`, but never read its `calculation_binding_identifier`. The
reviewer showed `Q_DAILY_EXPOSURE` bound to `percentage_w_w` (which produces
`percent_w_w`) satisfying `percentage_of_iid_mde`'s dependency, whose resolver
declares `unit_source = "gram"` — a percentage silently consumed as a gram/day
quantity, with no runtime control to catch it because runtime is deferred.

**Change.** `_validate_upstream_producer()` now requires, for every form E
resolver, that the upstream question carries a binding, that the binding resolves
to an approved entry, that the entry emits `system_calculated`, that the upstream
question's answer type matches what its entry produces, and that the entry's
`output_unit` **exactly equals** the consuming resolver's declared `unit_source`.

Unit comparison is exact equality. The specification authorises conversion only
inside the deferred runtime resolver, so no conversion, compatibility relation or
dimensional inference is performed at activation; an incompatible dimension
(millilitre against gram) is simply unequal and rejected.

| Producer defect | Structured code |
|---|---|
| Upstream carries no binding | `UPSTREAM_BINDING_IDENTIFIER_MISSING` |
| Upstream binding is not an approved entry | `UPSTREAM_REGISTRY_IDENTIFIER_UNKNOWN` |
| Upstream entry does not emit `system_calculated` | `UPSTREAM_SOURCE_CLASSIFICATION_MISMATCH` |
| Upstream answer type ≠ producer's declared type | `UPSTREAM_ANSWER_TYPE_MISMATCH` |
| Producer `output_unit` ≠ consumer `unit_source` | `UPSTREAM_OUTPUT_UNIT_MISMATCH` |

These are distinct codes, never collapsed into a generic missing-question error.
They are configuration failures, not `NOT_COMPARABLE` outcomes: nothing is
calculated in this phase.

### Minor 2 — unbound `SYSTEM_CALCULATED` questions

M4D3-REG-018 requires every `SYSTEM_CALCULATED` question to be validated.
Validation previously keyed off a non-blank binding identifier, so a calculated
question with no binding passed. `Model.clean()` couples the two, but it is not a
database constraint and `objects.create()` bypasses it. Activation now
re-establishes the invariant itself and emits
`SYSTEM_CALCULATED_BINDING_MISSING`.

### Minor 1 — one defect, two findings

A single absent referenced code produced two findings with different wording: the
resolver lookup reported it, then a trigger sweep reported it again. Two changes:

1. `ValidationFinding` identity is now the governed semantic key
   `(question_code, registry_identifier, validation_code, question_public_id)`.
   `message` is `compare=False` — presentation only — so wording can never
   create or hide a duplicate. Deduplication and ordering both use that key.
2. The redundant trigger sweep is **removed**, not merely deduplicated.
   `_resolve_unique()` is the single owner of missing/duplicate cardinality
   findings; every trigger code reaches the version through the resolver that
   declared it, and a trigger the resolvers never declare is a registry
   disagreement already reported as `TRIGGER_MISMATCH`.

### Minor 3 / Minor 4 — untested codes and an overstated claim

Four codes had no coverage: `WRONG_SOURCE_CLASSIFICATION`,
`DISABLED_SELECTOR_FORM`, `DEPENDENCY_MISMATCH`, `TRIGGER_MISMATCH`. Three are
unreachable while the immutable approved registry is in force. They are now
exercised through a **synthetic registry** installed with `monkeypatch` for one
test at a time: `get_entry()` resolves the module global on every call, so both
`activation_validation` and `calculation_graph` observe the substitution, and the
real registry is restored automatically. No committed registry definition is
mutated and production immutability is unchanged. The overstated "wrong
classification" claim in §6 is corrected in place.

### Form A (`question_response`) — recorded accurately

No approved production entry declares a `question_response` resolver, so the
generic form A branch is **not exercised by the real registry**. The branch is
retained because the resolver form is approved (M4D3-INP-003), and it is proven
with a synthetic entry. This is defensive generic support, not production
coverage, and is not claimed as such.

### Strengthened tests

- Unreferenced entries: a deliberately broken synthetic entry that *would* fail
  activation is installed and shown to be irrelevant while unreferenced —
  replacing an assertion on registry length, which proved nothing.
- Duplicate selection: asserts the exact code, the exact ambiguous question code,
  a 400, target unchanged, prior active still active and no success audit —
  replacing `findings != ()`.
- Cross-tenant: real second-tenant checklist content now holds a valid
  `Q_SUBJECT_COMPONENT` while tenant A's version does not, proving the ownership
  chain scopes the lookup rather than relying on the endpoint's 404.

### Post-remediation gates

| Gate | Command | Result |
|---|---|---|
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 60.6 s |
| Lifecycle / clone / platform-auth / execution | `pytest iig_checklist/tests/test_lifecycle.py iig_checklist/tests/test_clone_api.py iig_checklist/tests/test_platform_mutation_authorization.py iig_checklist/tests/test_execution_api.py --no-cov -q` | **101 passed**, 61.7 s |
| Tenant / permission regression | `pytest iig_checklist/tests/test_platform_authorization.py tenancy authorization --no-cov -q` | **46 passed**, 24.3 s |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **182 passed**, 0.28 s |
| Full backend suite | `pytest -q` | **1161 passed**, 0 failed, 0 skipped, 437.0 s, exit 0 |
| Coverage | same run | **92.82%** against a 55% floor |
| `activation_validation.py` coverage | same run | **100%** (150 statements, 0 missed) |
| `calculation_graph.py` coverage | same run | **99%** (110 statements, 1 missed) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts configured |

Targeted tests grew 26 → 59 and the suite 1128 → 1161 (+33). Coverage rose
92.59% → 92.82%. No threshold was lowered, no file excluded, no test skipped or
weakened, and no failure suppressed.

### Scope held

Still **not** implemented in this phase, and deliberately so:
`resolve_calculation_inputs()`, any calculation execution, `AssessmentSnapshot`
persistence, `CalculationOutcome` persistence, `update_checklist_response()`,
component rebinding, applicability persistence, response-history persistence,
serializers and frontend. This run remains activation validation only. No
migration was created and no model was changed.

## 6D. ORM Phase 2 — governed calculation input resolution

The activation-layer gate is **CLOSED** (independently confirmed at
`94ee23e4`). This section records the next authorized layer: reading each
approved resolver declaration from persisted rows. Nothing is calculated,
nothing is written.

### Integration files

| File | Role |
|---|---|
| `backend/iig_checklist/calculation_inputs.py` | `resolve_calculation_inputs()`, the immutable result structures and all six ORM resolver forms |
| `backend/iig_checklist/tests/test_4d3_calculation_inputs.py` | 84 PostgreSQL-backed tests |

No other production file changed. No migration, no model, no serializer, no
view, no frontend, and the activation validator is untouched.

### Contract

```
resolve_calculation_inputs(
    *, execution, target_question, registry_identifier, actor=None,
    locked_context=None,
) -> ResolvedCalculationInputs
```

`locked_context` (`ResolutionContext`) carries server-owned objects the caller
has already selected and locked — today the exact `AssessmentSnapshot` and,
optionally, the IID release the caller chose. `actor` is accepted for symmetry
with the governed services and deliberately unused: resolution reads no
actor-dependent state and must return the same result for every caller.

Structural caller-contract violations — a target question from another
checklist version, a non-`SYSTEM_CALCULATED` target, a target whose answer type
disagrees with its registry entry — raise `CalculationInputContractError`. These
are server-side programming faults no client input can reach. Every *data*
condition is returned as a governed `InputFailure`, never raised.

### The six resolver forms

| Form | Source | Reads | Key controls |
|---|---|---|---|
| A | `question_response` | `ChecklistResponse.raw_value` in this execution | exactly one question and one response; N/A and `REVIEW_REQUIRED:` marker both fail closed; shape validated through the existing `validate_raw_value_shape`; a `SYSTEM_CALCULATED` response can never be read as a result (M4D3-INP-003) |
| B | `formulation_field` | `FormulationVersion` / subject `FormulationComponent` | closed accessor table — an unlisted field is `INPUT_RESOLVER_UNKNOWN`, never a dynamic `getattr`; the execution's formulation must belong to the execution's tenant |
| C | `maximum_daily_units` | `FormulationVersion.maximum_dosage_units_per_day` + every `DosingRegimen` row | all rows collected and passed to the already-verified pure helper; conservative worst case; `patient_population` is provenance only, never a filter |
| D | `assessment_snapshot` | the caller's exact snapshot object | **no lookup at all** — tenant, subject component and (when the caller states one) IID release must all agree |
| E | `calculation_outcome` | the upstream response's `CalculationOutcome` | exactly one outcome per upstream response; `complete` status and non-null value; subject component proven from provenance |
| F | `constant` | the immutable registry declaration | callables and mutable containers rejected; no client override, no runtime expression |

### Subject component

Resolved **only** through the enabled `response_reference` selector: the exact
`{"public_id": "<uuid>"}` payload of the selector response, which must resolve
to a component inside this execution's own formulation version, owned by this
tenant, of the required component type. There is no ingredient-name match, no
UNII fallback and no display-order or primary-key inference; a second component
with an identical `ingredient_name` is proven not to interfere.
`registry_component_code` remains disabled and is rejected at runtime as well as
at activation.

Where an entry declares no component of its own, the subject component is
**inherited** from the upstream outcome it consumes (M4D3-MAP-010), and the
snapshot is then checked against that inherited component. A component-scoped
producer whose outcome records no subject component is rejected with
`UPSTREAM_CALCULATION_COMPONENT_MISMATCH` rather than assumed to agree.

### Failure contract

Every emitted code is drawn from the existing `ALLOWED_INPUT_FAILURE_CODES`; no
new vocabulary was introduced, and a test asserts the emitted set is a subset.
The deterministic 29-row `INPUT_FAILURE_MAPPING` continues to own the
status/reason/value translation — this service does not translate, because it
creates no `CalculationOutcome`.

`InputFailure` identity is the governed semantic key
`(kwarg_name, failure_code, source_kind, source_question_code, source_public_uuid)`;
`message` is `compare=False`, so wording can neither create nor hide a failure.
Failures are deduplicated on that key and ordered by it, never by insertion
order or primary key. Messages are authored from governed tokens only — no raw
exception text, no traceback, no SQL, no model repr, no database id.

**There is no partial success.** A single failed input empties the whole kwargs
mapping, so a caller can never reach a calculation with some inputs filled.

### Unit handling

Conversion goes through the existing 4D-3 adapter: Decimal only, canonical
units, plain-notation factor and rule version in provenance. Two observations
carried forward from the activation review are addressed explicitly:

- an absent source unit is `INPUT_UNIT_MISSING` — distinct from an unknown unit
  (`INPUT_UNIT_UNSUPPORTED`) and from a dimension mismatch;
- `SnapshotUnitRef` is resolved against the snapshot field it names rather than
  compared as a string, so a component quantity is converted into the IID
  reference unit and both sides of a comparison are like quantities.

The activation-time **exact-equality** rule is not reused here. Activation
compares two registry *declarations*, where equality is correct; runtime
converts real values, which the specification authorises.

### Locking and transaction boundary

The service opens no transaction and commits nothing, so every read joins the
caller's transaction. A future mutating caller must lock, in this order:

1. the `ChecklistExecution`;
2. the involved `ChecklistResponse` rows, ordered by `public_id`;
3. the involved `CalculationOutcome` rows, ordered by `public_id`;
4. the `AssessmentSnapshot` it selected or created.

### Tests

`test_4d3_calculation_inputs.py` — **84 tests, real PostgreSQL**, no mocked
QuerySets or managers. All six forms; every missing, duplicate, wrong-tenant,
wrong-execution, wrong-version, wrong-type and malformed condition; N/A and
`REVIEW_REQUIRED`; missing, unknown and dimension-mismatched units; stable
failure ordering; public-UUID-only provenance; and explicit proof that
resolution writes nothing.

Synthetic immutable registry entries are installed with `monkeypatch` for one
test at a time to reach form A and form F, which **no approved production entry
declares**. That is recorded here rather than presented as production coverage:
those two branches are approved generic support (M4D3-INP-003/008) exercised
synthetically. Production registry definitions are never mutated and
immutability is not weakened.

### Post-implementation gates

| Gate | Command | Result |
|---|---|---|
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **84 passed**, 45.4 s |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 45.1 s |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **182 passed**, 0.27 s |
| Lifecycle / clone / platform-auth / execution | `pytest iig_checklist/tests/test_lifecycle.py iig_checklist/tests/test_clone_api.py iig_checklist/tests/test_platform_mutation_authorization.py iig_checklist/tests/test_execution_api.py --no-cov -q` | **101 passed**, 56.7 s |
| Tenant / permission regression | `pytest iig_checklist/tests/test_platform_authorization.py tenancy authorization --no-cov -q` | **46 passed**, 21.5 s |
| Full backend suite | `pytest -q` | **1245 passed**, 0 failed, 0 skipped, 459.5 s, exit 0 |
| Coverage | same run | **93.10%** against a 55% floor |
| `calculation_inputs.py` coverage | same run | **94%** (473 statements, 30 missed — defensive branches unreachable while the approved registry is in force) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts |

Suite grew 1161 → 1245 (+84) and coverage rose 92.82% → 93.10%. No threshold was
lowered, no file excluded, no test skipped or weakened, no failure suppressed.

### Boundary held

Verified by grep over the committed module: no `save()`, `create()`,
`update()`, `delete()`, `bulk_*`, `emit()`, `transaction.atomic` or task
dispatch; no `.first()`, `.last()`, `.latest()` or `.earliest()`; and the
registry entry's `function` is **never called**.

Still **not** implemented, deliberately: calculation execution,
`CalculationOutcome` persistence, `AssessmentSnapshot` creation,
`update_checklist_response()`, the `expected_version` mutation path,
applicability persistence, component rebinding, response history, serializers
and frontend. The service is reachable only from tests and future services.

**Next layer:** governed calculation execution and persistence — invoking the
approved function with these resolved kwargs and writing the `CalculationOutcome`
through the deterministic translation table.

## 6E. Remediation of the resolver review (FAIL → 2 Major, 4 Minor)

An independent adversarial review of §6D returned **FAIL**: 0 Critical, 2 Major,
4 Minor. This section records what was wrong, what changed, and how each finding
is now proven.

### Major 1 — snapshot component validation depended on kwarg ordering

**Finding.** The effective subject component was established *inside* the single
resolution loop, which iterates `sorted(entry.input_resolvers.items())`. A form D
snapshot whose kwarg sorted before its form E dependency was therefore validated
against a component that had not been established yet. The reviewer's probe built
a consumer with `a_snapshot` and `z_upstream` and showed a snapshot describing a
completely different component resolving cleanly: `resolved=True`, zero failures.
The approved entries happened to be safe only because
`converted_proposed_daily_exposure` sorts before `selected_iid_mde` — alphabetical
accident, not design. The failure mode was a wrong regulated number, silently.

**Change.** `resolve_calculation_inputs()` now runs four explicit phases:

| Phase | Responsibility |
|---|---|
| A | validate the caller's objects; resolve the registry entry |
| B | establish the subject component **once**, before any input uses it |
| C | resolve every declared input against that finalized component |
| D | build the immutable result |

Phase B locates every form E upstream outcome first, collects each candidate
component identity — the selector's where the entry declares one, plus the
component recorded by every component-scoped upstream — and reconciles them in a
single step. Disagreement fails closed with
`UPSTREAM_CALCULATION_COMPONENT_MISMATCH`; no source silently wins, and there is
no precedence order that could make one of two different components correct. The
result cannot depend on kwarg names, kwarg ordering or mapping insertion order.

Phase C then hands the *same* finalized component to form B and form D, so the
snapshot check can no longer be skipped. This is a true pre-pass, not a post-pass
revalidation: no unvalidated value ever exists.

### Major 2 — the provenance key had no normative backing

**Finding.** Form E rejected any component-scoped upstream outcome whose
`input_provenance` lacked `subject_component_public_id` — a key this phase had
invented. M4D3-PRV-002 mandates only `_registry_binding_version` plus "a
per-input source descriptor", so the future execution layer had no obligation to
write it, and would have had every outcome rejected.

**Change.** The contract is now normative in the approved specification, and the
key is renamed to the server-controlled spelling:

- **M4D3-PRV-005** — reserved key `_subject_component_public_id`, canonical
  lowercase hyphenated UUID string, never a database primary key.
- **M4D3-PRV-006** — server-generated; the underscore prefix already makes
  M4D3-SEC-004 reject any request supplying it.
- **M4D3-PRV-007** — required for component-scoped calculations, omitted (not
  null, not empty) otherwise.
- **M4D3-PRV-008** — the execution/persistence service writes it; Form E fails
  closed on absent, malformed, foreign or mismatched values.
- **M4D3-PRV-009** — one component across selector, snapshot and every
  component-scoped input, reconciled before validation, order-independent.
- **M4D3-DEP-013** — an upstream outcome whose `calculation_name` differs from
  its binding's is rejected.

The key lives in one place, `calculation_translation.SUBJECT_COMPONENT_PROVENANCE_KEY`,
in the database-free vocabulary module so the read side and the future write side
bind to one spelling. `RESERVED_PROVENANCE_KEYS` and
`REGISTRY_BINDING_VERSION_PROVENANCE_KEY` sit beside it. No alias for the old
unprefixed spelling exists, and a test proves the old spelling does **not**
satisfy Form E — no 4D-3 outcome rows are persisted yet, so no compatibility
layer is warranted.

### Minor 1 — nested provenance was mutable

`provenance["considered_regimens"][0]["public_id"] = "TAMPERED"` succeeded: the
top level was a `MappingProxyType` but the nested dicts from the pure
maximum-daily-units helper were plain. A single `freeze()` helper now recurses —
mappings to `MappingProxyType`, sequences to tuples, sets to frozensets — and is
applied to every `ResolvedInput.provenance` and to the kwargs mapping. `Decimal`,
`UUID` and `str` pass through unchanged, so structured provenance is never
stringified.

### Minor 2 — duplicate binding was reported as missing data

A question code resolving to more than one question mapped to
`INPUT_RESPONSE_MISSING` → `data_required`/`DATA_REQUIRED`. An ambiguous binding
is a configuration fault, and M4D3-IFV-004/005 keep configuration and security
faults out of that category. It now maps to `INPUT_VALUE_INVALID` →
`error`/`INPUT_RESOLUTION_FAILED`. Zero matches and more-than-one matches remain
distinct, and a test asserts the resulting categories directly.

### Minor 3 — the upstream calculation name was unchecked

Form E accepted the single outcome for the upstream response regardless of which
calculation produced it. It now requires `outcome.calculation_name` to equal the
`calculation_name` of the registry entry bound to the upstream question, and
rejects a mismatch with the new `UPSTREAM_CALCULATION_NAME_MISMATCH`
(`error`/`INPUT_RESOLUTION_FAILED`/null). The status and value checks run first,
so an uncalculated placeholder still reports `UPSTREAM_CALCULATION_INCOMPLETE`
rather than a confusing name error.

The closed vocabulary therefore grows from 29 to 30 codes, with the mapping table
and the foundation test's count assertions updated together.

### Minor 4 — unused fixture

`test_resolution_performs_no_writes` requested `django_assert_num_queries` and
never used it. It now captures the executed SQL and asserts no `INSERT`,
`UPDATE` or `DELETE` verb appears, keeping the before/after row counts and
deliberately **not** asserting a brittle total query count. The same capture is
applied to a failing resolution and to a component-mismatch failure.

### Execution-phase write obligations

The future governed calculation-execution and persistence service **must** write,
in the same transaction as the outcome:

1. `_registry_binding_version` — the resolved entry's `binding_version` (M4D3-PRV-002);
2. per-input source descriptors (M4D3-PRV-002);
3. `_subject_component_public_id` for every component-scoped outcome (M4D3-PRV-005/008);
4. `calculation_name` equal to the approved calculation **function** name;
5. immutable input provenance.

**Pre-existing execution-phase blocker, unchanged by this run.**
`create_execution()` writes `question.calculation_binding_identifier` into
`CalculationOutcome.calculation_name`, while `CalculationOutcome.clean()` accepts
only the six approved function names — verified directly: `'daily_exposure'` is
rejected, `'calculate_daily_exposure'` is accepted. No placeholder can currently
be created for a `SYSTEM_CALCULATED` question through the governed service, so
Form E has never been exercised against a governed-path placeholder; the resolver
tests construct outcome rows directly. This is a 4D-2 defect, was already listed
as deferred in §5, and is **not** fixed here — it is a mandatory execution-phase
correction before runtime result persistence.

### Post-remediation gates

| Gate | Command | Result |
|---|---|---|
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 76.0 s |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **183 passed** |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed** |
| Lifecycle / clone / platform-auth / execution | as in §6D | **101 passed** |
| Tenant / permission regression | as in §6D | **46 passed** |
| Full backend suite | `pytest -q` | **1268 passed**, 0 failed, 0 skipped, 389.5 s, exit 0 |
| Coverage | same run | **93.20%** against a 55% floor |
| `calculation_inputs.py` coverage | same run | **94%** (569 statements, 34 missed) |
| System check | `manage.py check` | no issues (0 silenced) |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts |

Targeted resolver tests grew 84 → 106 and the foundation suite 182 → 183 (the
vocabulary is parametrized, so the new code adds one case). No threshold was
lowered, no file excluded and no test weakened.

One `# pragma: no cover` was added, on the selector-is-`None` guard in
`_resolve_selector_component`: Phase B now passes only declarations that *have* a
selector, so the branch is unreachable from its single call site. It is disclosed
here rather than left to look like coverage that exists. No `noqa` was added
anywhere.

### Still out of scope

Unchanged from §6D: no calculation execution, no `CalculationOutcome` creation or
update, no `AssessmentSnapshot` creation, no response mutation, no applicability
persistence, no component rebinding, no history persistence, no serializers, no
frontend, no model and no migration.

## 6F. Execution-readiness corrections

The resolver-layer and specification-amendment gates both closed with
**PASS WITH MINOR CORRECTIONS** (0 Critical, 0 Major, 1 Minor). This section
records the two execution-readiness items that remained, and — importantly — a
third defect discovered while fixing the second.

### Minor — canonical subject-component UUID enforced

**Finding.** M4D3-PRV-005 mandates the canonical lowercase hyphenated form for
`_subject_component_public_id`. The resolver parsed with `uuid.UUID()` and
compared identity, so an uppercase, braced, URN or compact spelling was silently
accepted and normalised.

**Change.** After parsing, the stored string must equal `str(parsed)` exactly;
anything else fails with `INPUT_VALUE_INVALID`. The specification was **not**
weakened to match the implementation — the implementation was tightened to match
the specification. Accepting a second spelling would let two provenance values
denote one component, which is exactly what a canonical form exists to prevent.

Rejected and covered: uppercase, braced, compact 32-character, `urn:uuid:`,
whitespace-padded, trailing-newline and malformed. A companion test proves every
rejected spelling *does* parse cleanly through `uuid.UUID()`, so the canonical
comparison — not UUID parsing — is what rejects them. A canonical UUID naming a
different component remains a distinct component-mismatch failure, and a
component outside this execution's formulation is still rejected without echoing
its UUID.

### Blocker — `create_execution()` placeholder calculation name

**Finding.** `create_execution()` wrote `question.calculation_binding_identifier`
into `CalculationOutcome.calculation_name`, while `CalculationOutcome.clean()`
accepts only the six approved calculation **function** names.

**Change.** The identifier is now resolved through the immutable registry and
`entry.calculation_name` is written. No second registry implementation was
introduced, and the raw binding string is not trusted: the entry must exist, its
`allowed_answer_type` must match the question's answer type, and its
`allowed_data_source` must match the question's classification. Any failure
raises `InvalidCalculationBinding`, which aborts the whole transaction — no
execution, no responses, no outcomes, no success audit — and surfaces through the
existing view as a structured `execution_invalid_calculation_binding` 400 rather
than a 500.

### Newly discovered — placeholder creation is still blocked by the model

Correcting the name exposed a **second, independent defect in the same path**.
`CalculationOutcome.inputs` and `CalculationOutcome.input_provenance` are
declared `JSONField(default=dict)` with `blank=False`. Django counts `{}` among
`Field.empty_values`, so a row holding its own field defaults cannot pass
`full_clean()`:

```
full_clean errors: {'inputs': ['This field cannot be blank.'],
                    'input_provenance': ['This field cannot be blank.']}
```

`create_execution()` creates every governed row through `_create_validated()`,
which always calls `full_clean()`. A calculated placeholder therefore still
cannot be created — now for this reason rather than the name.

**Not fixed here, deliberately.** The correct fix is `blank=True` on both fields,
which is a model change and a migration; both are outside this run's
authorisation. No workaround was applied: `full_clean()` was not bypassed, no
field was excluded from validation, and no provenance was fabricated to dodge the
blank check. Fabricating `inputs` or `input_provenance` content at placeholder
time would also contradict §6D's placeholder contract.

`test_calculation_name_is_no_longer_the_blocker` is the tripwire. It asserts that
`calculation_name` is **absent** from the rejected fields and that the rejection
set is exactly `{"inputs", "input_provenance"}` — so it proves the name fix
landed, documents precisely what remains, and fails usefully the moment the model
is corrected.

Because the placeholder cannot yet be created, the corrected name is proven at
its source instead: the registry mapping is asserted for every approved entry
(identifier → `calculate_*`, never equal to the identifier), and
`CalculationOutcome.clean()` is shown to accept every approved function name and
reject every binding identifier.

### Tests

`backend/iig_checklist/tests/test_4d3_execution_readiness.py` — **25 tests, real
PostgreSQL**. Placeholder name correction and its remaining blocker; fail-closed
rollback for unknown identifier, blank identifier, wrong answer type and (via a
synthetic entry) wrong source classification; no partial execution; unchanged
behaviour of the uncalculated path including the on-commit created audit, tenant
scoping and draft status; a tripwire proving no calculation function is invoked
during placeholder creation; and the full canonical-UUID matrix with a zero-write,
zero-audit assertion backed by SQL-verb capture.

### Post-correction gates

| Gate | Command | Result |
|---|---|---|
| Execution readiness | `pytest iig_checklist/tests/test_4d3_execution_readiness.py --no-cov -q` | **25 passed**, 52.0 s |
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 173.1 s |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 135.1 s |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.24 s |
| Lifecycle / clone / platform-auth / execution / response | `pytest …test_lifecycle.py …test_clone_api.py …test_platform_mutation_authorization.py …test_execution_api.py …test_execution_lifecycle.py …test_response_api.py --no-cov -q` | **127 passed**, 120.6 s |
| Tenant / permission regression | `pytest …test_platform_authorization.py tenancy authorization --no-cov -q` | **46 passed**, 23.3 s |
| Full backend suite | `pytest -q` | **1293 passed**, 0 failed, 0 skipped, 453.0 s, exit 0 |
| Coverage | same run | **93.25%** against a 55% floor |
| System check | `manage.py check` | no issues (0 silenced) |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts |

Suite grew 1268 → 1293 (+25) and coverage rose 93.20% → 93.25%. Gates were run
**serially**: they share one test database, and running them concurrently tears
it down mid-run and produces spurious failures. No threshold was lowered, no file
excluded, no test weakened, and no pragma, noqa, skip or xfail was added.

### Open execution-phase blockers

1. **`CalculationOutcome.inputs` / `input_provenance` must allow blank.**
   `blank=True` on both fields, with the accompanying migration. Until then no
   calculated placeholder can be created and governed calculation execution
   cannot start. Requires model/migration authorisation.
2. **The execution service must write** `_registry_binding_version`, per-input
   source descriptors, `_subject_component_public_id` for component-scoped
   outcomes, `calculation_name` equal to the approved function name, and
   immutable provenance (M4D3-PRV-002, M4D3-PRV-005..008).

Still **not** implemented: calculation execution, completed `CalculationOutcome`
values, `AssessmentSnapshot` creation, response mutation, applicability
persistence, component rebinding, response history, serializers and frontend. No
model or migration changed.

**Next layer:** governed calculation execution and persistence, once blocker 1 is
authorised and cleared.

## 7. Assertions

- Migrations created: **NO**
- Schema changed: **NO**
- Database access added: **NO**
- Coverage thresholds weakened: **NO**
- Database mocked to claim integration coverage: **NO**
- Existing tests weakened: **NO**
- Production registry made mutable: **NO**
- Runtime calculation code added: **NO**
- PR created: **NO**
- Merged: **NO**
