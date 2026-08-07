# Milestone 4D-3 — Implementation Evidence

**Status: FOUNDATION + REGISTRY ACTIVATION + INPUT RESOLUTION + GOVERNED
CALCULATION EXECUTION AND `CalculationOutcome` PERSISTENCE — all implemented.
Still deferred: governed `AssessmentSnapshot` creation, cascade recalculation
orchestration, `update_checklist_response()`, applicability persistence,
component rebinding, response-history redesign, serializers and frontend.**

> **Header correction.** Through §6F this document's header read "Runtime
> calculation, response-update, snapshot, outcome, rebinding and frontend layers
> deferred". That became wrong at §6H, which delivered runtime calculation and
> outcome persistence, and it was not updated at the time. An independent review
> raised it; the header above and the assertions in §7 are now accurate, and the
> stale line is recorded here rather than quietly deleted.

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

1. ~~**`CalculationOutcome.inputs` / `input_provenance` must allow blank.**~~ —
   **cleared in §6G.**
2. **The execution service must write** `_registry_binding_version`, per-input
   source descriptors, `_subject_component_public_id` for component-scoped
   outcomes, `calculation_name` equal to the approved function name, and
   immutable provenance (M4D3-PRV-002, M4D3-PRV-005..008). The model now
   *enforces* all of these on a completed row (§6G); the service that writes
   one remains unimplemented.

Still **not** implemented: calculation execution, completed `CalculationOutcome`
values, `AssessmentSnapshot` creation, response mutation, applicability
persistence, component rebinding, response history, serializers and frontend.

**Next layer:** governed calculation execution and persistence.

## 6G. Placeholder model remediation and completion invariant

The independent confirmation review closed the execution-readiness correction
gate (PASS) and confirmed both the JSONField blocker and the sharp point that
`blank=True` alone would be unsafe. This section records both halves of the
remediation.

### The blocker, and why `blank=True` alone was not enough

`CalculationOutcome.inputs` and `input_provenance` were
`JSONField(default=dict, blank=False, null=False)`. Django's
`Field.empty_values` is `[None, '', [], (), {}]`, so `{}` counts as blank and a
row holding its own defaults could not pass `full_clean()` — no calculated
placeholder could be created at all.

Relaxing to `blank=True` fixes that, but on its own it would also let a
**completed** row carrying a real regulated number be saved with
`input_provenance == {}`, because `clean()` validated only `calculation_name`
and nothing status-dependent. That would violate M4D3-PRV-002 and
M4D3-PRV-005/007. The relaxation therefore ships with an invariant that
restores the guarantee at the status that actually needs it.

### Model change and migration

| Field | Before | After |
|---|---|---|
| `CalculationOutcome.inputs` | `JSONField(default=dict)` | `JSONField(default=dict, blank=True)` |
| `CalculationOutcome.input_provenance` | `JSONField(default=dict)` | `JSONField(default=dict, blank=True)` |

`null` stays `False` — the column is always a JSON object, never SQL NULL.
Nothing else changed: no value nullability, no status choices, no
`calculation_name`, no unit fields, no relationships, no indexes or constraints.

`backend/iig_checklist/migrations/0003_alter_calculationoutcome_input_provenance_and_more.py`
— two `AlterField` operations, dependency `('iig_checklist', '0002_execution')`,
reversible, no `RunPython`, no data rewrite, no rename, no column-type change.
`sqlmigrate` confirms it is a pure Django state change:

```
BEGIN;
-- Alter field input_provenance on calculationoutcome
-- (no-op)
-- Alter field inputs on calculationoutcome
-- (no-op)
COMMIT;
```

### Completion invariant (M4D3-PRV-002/005/007)

`CalculationOutcome.clean()` now applies status-dependent validation. It runs
**only** for `status == complete`; `data_required`, `calculating` and `error`
rows carry no value and are untouched, which a parametrized test asserts.

For a completed outcome:

| Requirement | Error field |
|---|---|
| `value` is non-null | `value` |
| `input_provenance` is a mapping | `input_provenance` |
| `_registry_binding_version` present, three-part numeric | `input_provenance` |
| at least one per-input source descriptor beyond the reserved keys | `input_provenance` |
| `calculation_name` resolves to an approved registry entry | `calculation_name` |
| component-scoped entry records `_subject_component_public_id` | `_subject_component_public_id` |
| recorded component is a canonical lowercase hyphenated UUID | `_subject_component_public_id` |
| entry that neither selects nor inherits a component records none | `_subject_component_public_id` |

Two judgment calls, both stated rather than buried:

- **Binding version is checked for format, not equality with today's registry.**
  Provenance is historical evidence: the version a result was produced under may
  legitimately predate the current entry. Requiring equality would invalidate
  every stored record the moment a `binding_version` is incremented, which is
  the opposite of what a reproducibility chain is for. A test asserts an older
  `0.9.3` still validates.
- **"Component-scoped" means the entry declares a `component_selector`.** An
  entry with no selector but with `calculation_dependencies` *inherits* its
  component (M4D3-MAP-010), so it may record one but is not required to. Only an
  entry that neither selects nor inherits is forbidden from recording one — a
  branch no approved entry reaches, exercised through a synthetic entry.

The registry lookup is a reverse scan by `calculation_name` over the immutable
server registry; `_validate_registry()` guarantees the name is unique per entry,
so it is unambiguous. No calculation function is invoked and no client-supplied
data is consulted.

### Governed placeholder creation now works

`create_execution()` creates a valid placeholder end to end, proven against real
PostgreSQL: one outcome per calculated response, `calculation_name` equal to the
registry entry's function name (never the binding identifier), `status`
`data_required`, `value` null, `inputs == {}`, `input_provenance == {}`, and
`full_clean()` passing on the row the service just wrote. A tripwire replaces the
bound calculation function and proves it is never called. Fail-closed rollback on
unknown identifier, blank identifier, wrong answer type and wrong source
classification is retained, and the existing created-audit behaviour is
unchanged.

The tripwire test that previously asserted the path was still blocked on
`{"inputs", "input_provenance"}` is **replaced** by these success assertions, as
the confirmation review required.

### Post-remediation gates

| Gate | Command | Result |
|---|---|---|
| Execution readiness + outcome states | `pytest iig_checklist/tests/test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 29.2 s |
| Execution models | `pytest iig_checklist/tests/test_execution_models.py --no-cov -q` | **15 passed** |
| Execution API / lifecycle / response / reviewer conclusion | `pytest …test_execution_api.py …test_execution_lifecycle.py …test_response_api.py …test_reviewer_conclusion_api.py --no-cov -q` | **49 passed** |
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **106 passed** |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed** |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **183 passed** |
| Lifecycle / clone / platform auth / tenant / permission | `pytest …test_lifecycle.py …test_clone_api.py …test_platform_mutation_authorization.py …test_platform_authorization.py tenancy authorization --no-cov -q` | **131 passed** |
| Full backend suite | `pytest -q` | **1327 passed**, 0 failed, 0 skipped, 539.0 s, exit 0 |
| Coverage | same run | **93.33%** against a 55% floor |
| System check | `manage.py check` | no issues (0 silenced) |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0, `0003` applied |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts |

Suite grew 1293 → 1327 (+34) and coverage rose 93.25% → 93.33%. Gates were run
serially. No threshold was lowered, no file excluded, no test weakened, and no
pragma, noqa, skip or xfail was added.

### Boundary held

No calculation function is invoked anywhere in this change; the completion
invariant *validates* a hypothetical completed outcome but nothing creates one.
Not implemented: the calculation-execution service, `CalculationOutcome`
completion workflow, `AssessmentSnapshot` creation, response mutation,
`expected_version` handling, applicability persistence, component rebinding,
response history, serializers and frontend. The only model change is the two
`blank=True` flags and the `clean()` invariant; the only migration is `0003`.

## 6H. ORM Phase 3 — governed calculation execution

Every prior gate is closed, so this section delivers the layer they existed to
protect: resolving inputs, invoking one approved calculation, and persisting the
result into the placeholder created at execution creation.

`backend/iig_checklist/calculation_execution.py` —
`execute_calculation_response()`, delivered as one commit rather than the
planned execution-then-persistence pair: the completed-outcome invariant from
§6G makes provenance a precondition of saving any complete outcome, so an
intermediate that persisted a result without provenance could not have passed
its own model validation. One new audit event constant,
`iig_checklist.response.calculated`. No other production file changed; no model,
no migration, no serializer, no frontend.

### Scope, each boundary grounded in a clause rather than convenience

| Decision | Basis |
|---|---|
| **No response mutation** | M4D3-MDL-006 — a `SYSTEM_CALCULATED` response keeps `raw_value = null` at all times and results live exclusively in `CalculationOutcome`; M4D3-SVC-006 forbids writing `system_derived_value`. There is no projection to maintain and no second source of truth. |
| **No history row** | M4D3-HST-003 requires a row when a governed transition *changes an existing `ChecklistResponse`*. This service changes no response, so no transition occurs. `ALLOWED_HISTORY_REASON_CODES` holds no calculation code either. |
| **No snapshot creation** | Stop condition — see below. |
| **Single response only** | Cascade orchestration across the dependency graph is deferred and is **not** claimed here. |

### Stop condition — no governed snapshot creation service exists

M4D3-SNO-001 requires the snapshot to be created "through the approved
`iid_assessment` service". No such callable service exists: `AssessmentSnapshot`
rows are created only inside `iid_assessment/views.py::SnapshotView.post`, bound
to a DRF request, serializer, `request.user` and HTTP response. Extracting a
service out of that view is an `iid_assessment` refactor this run is not
authorised to make, and the authorisation permits snapshot creation *only*
through the governed service.

Rather than duplicate the view's logic or invent a lookup, the execution service
accepts the exact snapshot object through `snapshot_context`, exactly as the
already-reviewed resolver does. All four snapshot-backed calculations are fully
executed and tested this way. **Snapshot creation remains an open blocker.**

### Lock order

> **Superseded by §6I.** As shipped in §6H this service ordered its multi-row
> locks by `public_id`, which contradicts M4D3-TXN-001, M4D3-OUT-004 and
> M4D3-RBD-004 — all three require ascending primary-key order, the first
> "without exception". An independent review caught it. §6I corrects the
> implementation to primary-key order and records the corrected, SQL-verified
> sequence. The original §6H text is left below so the change is auditable.

Original §6H text, **now incorrect**:

1. the `ChecklistExecution`;
2. the target `ChecklistResponse`;
3. every involved upstream/selector `ChecklistResponse`, ordered by `public_id`;
4. every involved `CalculationOutcome`, ordered by `public_id`;
5. the caller's `AssessmentSnapshot`, when supplied.

The claim that all outcomes were locked before the snapshot was also wrong: the
target placeholder was in fact locked *after* the snapshot. Both defects are
fixed in §6I.

### Flow

Phase A validates the caller's objects with no locks and no writes: the response
belongs to the execution, the execution belongs to the tenant, the question is
`SYSTEM_CALCULATED`, and the binding resolves to an approved entry. Phase B opens
one `transaction.atomic()`, takes the locks above, checks `expected_version`
against the locked row, requires exactly one placeholder, resolves inputs through
`resolve_calculation_inputs()`, and then either persists a governed input failure
or invokes the calculation. Phase C emits one audit event through
`transaction.on_commit()`.

The calculation function is `entry.function` from the immutable server registry,
invoked exactly once with exactly the resolver's kwargs. No dynamic import, no
client-supplied name, no `eval`. A test replaces the bound function with a
counter and asserts a single call with the exact kwarg set.

The engine returns a governed `CalculationResult` for every scientific
condition, so an exception from it is an implementation fault: it raises
`CalculationEngineFailure`, aborts the transaction, and its text never reaches a
stored outcome — asserted directly.

### Translation and persistence

`translate_engine_status()` and `translate_input_failure()` are reused
unchanged. Only the existing placeholder row is updated — never a second row,
never delete-and-recreate — and `full_clean()` runs before every save, so the
completed-outcome invariant from §6G applies to everything this service writes.

`complete` carries a value and the engine's unit; every other status stores a
null value and an empty unit. An unknown engine status maps to
`UNKNOWN_ENGINE_STATUS`, and a naive or malformed `generated_at` maps to
`INVALID_GENERATED_AT` — both fail closed with a null value, both tested.

Input failures persist the governed outcome from the deterministic 30-row
mapping, using the first failure in the resolver's already-stable order. Tenant
and configuration faults keep their own categories: a cross-tenant snapshot
stores `TENANT_ISOLATION_VIOLATION`, and a test asserts it is not
`NOT_COMPARABLE`.

### Provenance

Persisted provenance carries `_registry_binding_version`, `calculation_name`,
`formula_version`, the snapshot public UUID where one was used, upstream outcome
public UUIDs, and one descriptor per input holding source kind, source public
UUID, source question code, units, conversion factor and adapter version. Inputs
are stored as exact decimal strings — never floats, which would silently change
a regulated number. A test walks both structures and asserts no key is a
database id and no value is a model repr.

**`_subject_component_public_id` is written whenever
`ResolvedCalculationInputs.subject_component_public_id` is not None** — from a
selector *or* inherited from an upstream outcome, deliberately not limited to
entries declaring a `component_selector`. This closes the observation carried
from the model/migration confirmation: a three-level synthetic chain is tested
end to end, and the third level receives the component only because the
inherited middle outcome recorded it.

### Tests

`backend/iig_checklist/tests/test_4d3_calculation_execution.py` — **37 tests,
real PostgreSQL**, driving the governed path with placeholders created by the
real `create_execution()`.

All six approved calculations execute with hand-checkable fixtures: a 250 mg
excipient in a 1 g tablet taken four times daily, against a 1 g IID potency and
2 g MDE. `percentage_w_w` = 25 %, `daily_exposure` = 1 g/day,
`percentage_of_iid_potency` = 25 %, `difference_from_iid_potency` = 0.75 g,
`percentage_of_iid_mde` = 50 %, `difference_from_iid_mde` = 1 g/day.

> Two expectations were initially written with the sign reversed. The engine's
> convention is **reference minus proposed** — a positive difference means the
> proposal sits below the precedent. The tests were corrected to the engine, not
> the reverse, and the convention is now stated in their docstrings.

Also covered: no second outcome row; JSON-safe inputs; provenance keys and
per-input descriptors; no database ids; snapshot public id recorded; response
never mutated; no history row; selector, inherited and three-level component
provenance; mismatched component; every non-success category; stale
`expected_version`; engine exception; missing and duplicate placeholder;
non-calculated target; foreign execution; unknown binding; exactly one audit
event on success, none on rollback; and recalculation updating the same row with
provenance replaced atomically.

Atomicity is asserted by comparing a full snapshot of outcomes, responses,
snapshot count, history count and audit count before and after each failure.

### Post-implementation gates

| Gate | Command | Result |
|---|---|---|
| Calculation execution | `pytest iig_checklist/tests/test_4d3_calculation_execution.py --no-cov -q` | **37 passed**, 27.4 s |
| Execution readiness | `pytest iig_checklist/tests/test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 20.2 s |
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 54.5 s |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 44.3 s |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.23 s |
| Execution model / API / lifecycle / response / reviewer | `pytest …test_execution_models.py …test_execution_api.py …test_execution_lifecycle.py …test_response_api.py …test_reviewer_conclusion_api.py --no-cov -q` | **64 passed**, 38.8 s |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …test_lifecycle.py …test_clone_api.py …test_platform_mutation_authorization.py …test_platform_authorization.py tenancy authorization --no-cov -q` | **131 passed**, 63.0 s |
| Full backend suite | `pytest -q` | **1364 passed**, 0 failed, 0 skipped, 398.6 s, exit 0 |
| Coverage | same run | **93.50%** against a 55% floor |
| `calculation_execution.py` coverage | same run | **96%** (162 statements, 6 missed) |
| System check | `manage.py check` | no issues (0 silenced) |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check iig_checklist` | All checks passed, exit 0 |
| Import-linter | `importlinter.cli lint` | exit 0, 7 contracts |

Suite grew 1327 → 1364 (+37) and coverage rose 93.33% → 93.50%. Gates were run
serially. No threshold lowered, no file excluded, no test weakened, and no
pragma, noqa, skip or xfail added.

### Deferred

1. **Governed `AssessmentSnapshot` creation** — no callable service exists;
   snapshots are supplied by the caller. Requires either extracting a service
   from `iid_assessment.views.SnapshotView` or authorising one.
2. **Cascade recalculation orchestration** — only direct single-response
   execution is implemented. Trigger expansion, topological ordering and the
   10-node cascade limit exist in `calculation_graph` but no orchestrator drives
   them.
3. Unchanged: manual override (4D-4), applicability persistence, component
   rebinding, response-history redesign, approval automation, reports, exports,
   dashboards, notifications, asynchronous execution, serializers and frontend.

## 6I. Remediation of the execution review (FAIL → 1 Major, 10 Minor)

An independent adversarial review of §6H returned **FAIL**: 0 Critical, 1 Major,
10 Minor. This section records what was wrong, what changed and how each finding
is now proven. **No specification document was altered**, no model changed and no
migration added.

### Major — lock order was `public_id`, not primary key

**Finding.** `execute_calculation_response()` ordered every multi-row
`select_for_update()` by `public_id`. Three approved clauses require ascending
primary key: M4D3-TXN-001 ("this order shall be observed without exception"),
M4D3-OUT-004 for `CalculationOutcome`, and M4D3-RBD-004 for the future
component-rebinding transaction. `public_id` is a random UUID, so its order is
uncorrelated with primary-key order; a specification-conformant cascade or
rebinding service would have deadlocked against direct execution. §6H compounded
this by presenting `public_id` ordering as the governed order, so the deviation
was undisclosed.

The reviewer also showed the documented sequence was wrong in a second way: the
target `CalculationOutcome` was locked *after* the `AssessmentSnapshot`, while
both the module docstring and §6H claimed all outcomes preceded the snapshot.

**Change.** The service now acquires, in this order:

| # | Rows | Ordering |
|---|---|---|
| 1 | the `ChecklistExecution` | single row |
| 2 | the target `ChecklistResponse` | single row |
| 3 | every other involved `ChecklistResponse` | `ORDER BY id ASC` |
| 4 | every involved `CalculationOutcome` — upstream **and** target placeholder | one statement, `ORDER BY id ASC` |
| 5 | the exact `AssessmentSnapshot`, when supplied | single row |

Step 4 is the substantive change beyond the ordering column. Previously the
upstream outcomes and the target placeholder were locked by two separate
statements with the snapshot lock between them. They are now acquired by a
**single** pk-ordered query and classified in memory, so there is no window in
which the two halves could be taken in conflicting orders, and the target
outcome necessarily precedes the snapshot.

Three helpers own this and normalise whatever order a caller supplies —
`_related_response_ids()`, `_lock_responses()` and `_lock_outcomes()` — so a
future cascade or rebinding pass reuses one acquisition order rather than
inventing a second.

**Why target-before-related is safe.** Step 2 is not itself pk-ordered relative
to step 3. It does not need to be: step 1 already holds the `ChecklistExecution`
row, and every response and outcome this service touches belongs to that one
execution. No two governed operations on the same execution can be inside steps
2–5 simultaneously, and operations on different executions share no rows. That
reasoning is now in the module docstring rather than left implicit.

**Public UUIDs keep their proper job.** They remain the identity used in
provenance, audit payloads, the result object and deterministic failure
ordering. They are simply not a row-lock acquisition order.

**Proof.** `TestLockOrder` captures the SQL PostgreSQL actually receives and
asserts on it — not on Python call order. Observed for a snapshot-backed
dependency calculation (`percentage_of_iid_mde`):

```
1  ..."iig_checklist_checklistexecution"  WHERE "ID" = 1                          FOR UPDATE
2  ..."iig_checklist_checklistresponse"   WHERE "ID" = 6                          FOR UPDATE
3  ..."iig_checklist_checklistresponse"   WHERE "ID" IN (3)     ORDER BY "ID" ASC FOR UPDATE
4  ..."iig_checklist_calculationoutcome"  WHERE "RESPONSE_ID" IN (3, 6)
                                                               ORDER BY "ID" ASC FOR UPDATE
5  ..."iid_assessment_assessmentsnapshot" WHERE "ID" = 1                          FOR UPDATE
```

Ten tests assert this: pk ordering for responses, pk ordering for outcomes, one
statement for the whole outcome set, no `FOR UPDATE` ordering by `public_id`,
execution first, target response before related responses, target outcome before
the snapshot, snapshot last, the full table sequence, and that the helpers
normalise a reversed or shuffled caller-supplied id list. The `ORDER BY` column
is read alias-insensitively but asserted strictly.

**Mutation probe.** Reverting the three `order_by("pk")` calls to
`order_by("public_id")` and re-running fails **6** tests, including the
concurrency test. The tests are not vacuous.

**Concurrency proof.** `test_overlapping_transactions_do_not_deadlock` runs two
real transactions on a `transaction=True` database, released together by a
`threading.Barrier`. One holds the row set a direct execution touches; the other
holds the wider set a cascade or rebinding pass would touch, supplied in reverse
order. Both go through the governed helpers, both emit `ORDER BY id ASC`, both
complete. Each sets `SET LOCAL lock_timeout = '5s'`, so a genuine inversion
surfaces as a failure rather than a hang. A second test keeps the existing proof
that the execution row serializes concurrent calculations (M4D3-TXN-006).

### Minor 1 — documented order did not match the implementation

Fixed with the Major above. The module docstring, the service docstring, the
inline step comments and this document now all state the same five-step
primary-key order, and `test_documented_order_matches_the_issued_statements`
asserts the exact table sequence so the three cannot drift apart again.

### Minor 2 — `expected_version` could silently disable concurrency

**Finding.** The guard read `if expected_version is not None and ...`, so passing
`None` skipped optimistic concurrency entirely. Undocumented and untested.

**Change.** `expected_version` is now mandatory and validated in Phase A, before
any lock, any resolution, any calculation and any audit:

- `None` → `InvalidExpectedVersion`;
- `bool` → `InvalidExpectedVersion`, even though `bool` is an `int` subclass,
  because `True` would otherwise silently mean version 1;
- non-`int` (`str`, `float`, `Decimal`) → `InvalidExpectedVersion`;
- below 1 → `InvalidExpectedVersion`; `ChecklistResponse.version` is a
  `PositiveIntegerField(default=1)` that only increments, so 1 is the lowest
  version any real row can hold.

A stale but well-formed version still raises `StaleResponseVersion` while the
row is locked, with zero mutation. The service type contract and docstring state
that there is no value which disables the check. Eight parametrised cases plus
three behavioural tests cover it, including proof that no calculation function is
invoked and no audit row is written on rejection.

### Minor 3 — tenant-isolation guard had no coverage

`calculation_execution.py:302` — the `execution.tenant_id != tenant.id` guard —
was one of the six uncovered lines. `TestTenantIsolation` now drives the real
service twice: once with a foreign tenant against this execution, once with
another tenant's governed execution and response. Both fail closed with zero
outcome mutation, zero function invocation and zero audit, and the raised message
is asserted to leak no execution, response or tenant identifier.

### Minor 4 — no `full_clean()` rollback test

`TestFullCleanRollback` plants a two-part `binding_version` on the registry
entry, which `CalculationOutcome._validate_completed_outcome()` rejects. The
calculation *is* invoked exactly once — the failure is at persistence, not
before — and `ValidationError` naming `_registry_binding_version` propagates. The
placeholder, the response, the snapshot count, the history count and the audit
count are all unchanged. A companion test proves the monkeypatch is restored and
the approved entry still executes.

### Minor 5 — result immutability was never asserted

`TestImmutableResult` attempts to reassign every dataclass field, add a new
attribute, mutate the nested `failure_codes` tuple by `append` and by index, and
asserts the instance has no `__dict__`. It also asserts no field is a Django
`Model` or `QuerySet` and that identity is the outcome's public UUID string.

### Minor 6 — the NOT_COMPARABLE test did not test NOT_COMPARABLE

**Finding.** The helper was named `_not_comparable` but returned
`status="UNIT_MISMATCH"`. No committed test exercised a genuine engine
`NOT_COMPARABLE`.

**Change.** Three separate tests now exist, and the misleading name is gone:

- `test_engine_emits_not_comparable_for_an_unclear_basis` proves against the
  pure engine that `CalculationStatus.BASIS_UNCLEAR == "NOT_COMPARABLE"` and
  that a zero dosage-unit weight reaches it;
- `test_genuine_not_comparable_is_persisted` drives that real engine status
  through the service and asserts `error` / `NOT_COMPARABLE` / null value /
  empty unit. The zero basis is supplied to the approved function directly
  because `formulation_total_weight_positive` forbids a zero weight in the
  table, so no fixture can reach it through the database;
- `test_engine_unit_mismatch_yields_null_value` and
  `test_resolver_unit_fault_is_not_scientific_non_comparability` keep
  `UNIT_MISMATCH` as its own case and assert it is *not* `NOT_COMPARABLE`,
  which is what M4D3-IFV-004/005 require.

The reviewer's concern that a configuration or unit fault was being persisted as
scientific non-comparability was **not** borne out — the mapping was already
correct. Only the test naming and coverage were wrong.

### Minor 7 — difference calculations persist an empty result unit — SPECIFICATION GAP

`difference_from_iid_potency` and `difference_from_iid_mde` complete carrying a
regulated `Decimal` with `unit = ""`. The engine sets no unit on either result,
and both registry entries declare `output_unit = ""`.

**This is not fixed, deliberately.** The specification is silent:

- M4D3-MAP-007 explicitly instructs the service to store `gram` for
  `daily_exposure`, whose engine result also carries no unit. That clause exists
  precisely because the engine leaves the unit blank.
- M4D3-MAP-004 and M4D3-MAP-006 say only that the difference calculations take
  the same resolved inputs as M4D3-MAP-003/005, "only the kwarg order differs".
  Neither prescribes a result unit.
- The registry field contract (Part 3) states `output_unit` "may be empty".

M4D3-UNC-006 makes the *natural* unit inferable — both operands of the potency
difference are in the snapshot's `iid_potency_unit`, and both operands of the MDE
difference are in its `iid_mde_unit` — but writing that would be a new governed
rule, and `output_unit` is a static registry string while those units are
snapshot-dependent. Implementing it here would mean either inventing a clause or
redesigning `output_unit` into a dynamic value, and this run is authorised to do
neither.

**Deferred requirement, to be added to the approved specification before the
serializer layer exposes these outcomes:** a clause equivalent to M4D3-MAP-007
for M4D3-MAP-004 and M4D3-MAP-006, defining the stored `CalculationOutcome.unit`
of each difference calculation as the snapshot unit its operands were reconciled
into.

**The gap is asserted, not hidden.** `TestDifferenceResultUnit` records that the
registry declares no output unit for either difference, that `daily_exposure` by
contrast has one and honours it, that both differences do complete with an empty
unit, and — bounding the impact — that the unit remains reconstructible because
every input descriptor records its own `source_unit` and `target_unit`.

### Minor 8 — `str(Decimal)` could persist scientific notation

**Finding.** The JSON persistence boundary used bare `str(Decimal)`, which
renders `1E-7` for small magnitudes and `1E+3` for large ones, while the unit
adapter already forced plain notation for the conversion factor for exactly this
reason. Nothing was lost numerically, but a regulated record should not need
decoding.

**Change.** One shared formatter, `calculation_translation.format_decimal_plain()`,
in the database-free module both sides already import. It uses
`format(value, "f")`, preserves the Decimal's own exponent (so `0.250000` keeps
its trailing zeros and repeated executions render identically), handles negatives
and zero, and falls back to `str()` for a non-Decimal or a NaN/infinity rather
than raising — a persistence-boundary renderer must never be the thing that
aborts a governed write. `_json_safe()` and the unit adapter's `original_value`,
`converted_value` and `conversion_factor` all route through it, so there is
genuinely one formatter rather than two that agree today.

Proven end to end: a component of `0.000001` milligram converts to exactly
`Decimal("1E-9")` grams — `str()` of which really is `'1E-9'` — and persists as
`"0.000000001"` in both `inputs` and the per-input descriptor, with a sweep
asserting no persisted *number* anywhere in `inputs` or `input_provenance` uses
scientific form. The sweep requires a value to parse as a `Decimal` before
flagging it, because a public UUID such as `...aca7-474b30d178a7` contains `4e5c`
and a naive regex would report it as an exponent. A negative reference is covered
separately, arithmetic is untouched, and a seven-case parametrised matrix covers
`1E-7`, `-1E-7`, `1E-12`, `1E+3`, `0`, `0.250000` and `-0.500000`.

### Minor 9 — stale evidence

The header and §7 assertions still described runtime calculation and outcome
persistence as deferred, and §7 still asserted "Migrations created: NO" after
§6G added `0003`. Both are corrected above, per scope, with the stale text
recorded rather than silently removed. §6H's lock-order section is marked
superseded rather than rewritten in place.

### Minor 10 — coverage figure

§6H recorded 93.50 %; the reviewer measured 93.51 %. The measured value for this
run — **93.66 %** — is taken from the gates table below rather than carried
forward, and every figure there is from a run made after the last source change.

### Audit-callback failure — established behaviour, recorded not changed

The audit is dispatched through `transaction.on_commit()`, so by the time it runs
the outcome is already durable. There is **no rollback after commit** and none
was invented. Project policy, verified across every governed service
(`services.py` ×3, `views.py` ×1, this service ×1), is a bare
`transaction.on_commit(...)` with no swallow, no retry and **no durable outbox
anywhere in the repository**.

Actual behaviour, now asserted by
`test_a_failing_audit_callback_does_not_undo_the_commit`: the calculation result
stays committed, the callback's exception propagates to the caller, no audit row
is written and nothing is retried. A companion test asserts the success path
registers exactly one callback and writes exactly one row.

**Deferred:** a durable audit outbox. The gap is that a governed calculation can
commit without its audit event if the audit sink fails. That is a
repository-wide property, not specific to this service, and building an outbox is
outside this run's authorisation.

### Snapshot boundary — unchanged, and asserted

The stop condition of §6H is retained and is now tested rather than asserted in
prose. `AssessmentSnapshot` rows are still created only inside
`iid_assessment/views.py::SnapshotView.post`, bound to a DRF request, serializer,
`request.user` and HTTP response; there is no `iid_assessment/services.py`.

`TestDeferredBoundaries` proves: the execution module contains no snapshot
create, no snapshot lookup, no `.first()`, `.last()`, `.latest()` or
`.earliest()`, and exactly one `AssessmentSnapshot.objects` reference — the
pk-scoped lock of the caller's own row; `iid_assessment.services` does not
import; no view, serializer or URL module references `calculation_execution`, so
snapshot-backed execution is reachable only from tests and future services; and a
client-style snapshot *identifier* in place of the object is rejected rather than
resolved (M4D3-SNO-011).

**Snapshot-backed calculation execution remains internal-only** until a governed
`AssessmentSnapshot` creation service exists. Governed snapshot creation is
**not** implemented in this run and is not claimed to be.

### Service error codes — deferred boundary, documented

M4D3-OUT-005 names the external error code `duplicate_calculation_outcome`. This
internal service raises the typed `PlaceholderAmbiguous` and writes nothing; the
governed external code is mapped by the deferred API layer, which must never
serialize the raw exception. `test_duplicate_outcome_stays_an_internal_fail_closed_exception`
records the boundary, asserting the internal exception carries no external code
and that the failure leaves the database untouched.

### Files changed

| File | Change |
|---|---|
| `backend/iig_checklist/calculation_execution.py` | primary-key lock order, single-statement outcome locking, mandatory `expected_version`, plain-notation persistence, corrected documentation |
| `backend/iig_checklist/calculation_translation.py` | `format_decimal_plain()` — the one shared plain-notation formatter |
| `backend/iig_checklist/unit_adapter.py` | routes `original_value`, `converted_value` and `conversion_factor` through the shared formatter |
| `backend/iig_checklist/tests/test_4d3_calculation_execution.py` | 37 → 97 tests |
| `docs/MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md` | this section, plus the header, §6H and §7 corrections |

No model, no migration, no serializer, no view, no frontend, no specification
change.

### Tests

`backend/iig_checklist/tests/test_4d3_calculation_execution.py` — **37 → 97
tests, real PostgreSQL**. The 37 existing tests are retained; one was renamed
(`test_engine_non_ok_status_yields_null_value` →
`test_engine_unit_mismatch_yields_null_value`) and its misleadingly named helper
corrected. New coverage:

| Area | Tests |
|---|---|
| SQL-level lock order (`TestLockOrder`) | 10 |
| Lock-helper edge guards (`TestLockHelperEdges`) | 2 |
| Concurrency and deadlock order (`TestLockOrderConcurrency`) | 2 |
| Mandatory `expected_version` (`TestExpectedVersionIsMandatory`) | 11 |
| Tenant isolation (`TestTenantIsolation`) | 2 |
| `full_clean()` rollback (`TestFullCleanRollback`) | 2 |
| Immutable result (`TestImmutableResult`) | 5 |
| Plain-notation persistence and the JSON boundary (`TestPlainNotationPersistence`) | 12 |
| Difference result unit / specification gap (`TestDifferenceResultUnit`) | 4 |
| Audit-callback failure (`TestAuditCallbackFailure`) | 2 |
| Deferred boundaries (`TestDeferredBoundaries`) | 5 |
| Genuine NOT_COMPARABLE and separate UNIT_MISMATCH | 3 |

`calculation_execution.py` reaches **100 %** statement coverage from this module
alone (179 statements, 0 missed) — it was 96 % with six uncovered lines before,
one of which was the tenant-isolation guard.

Every line the module leaves uncovered is a "this must not happen" path that a
test is actively asserting: the counting stubs in the three tests that prove no
calculation function is invoked, and the `except` inside the concurrency thread
that would fire on a deadlock or lock timeout.

### Post-remediation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| Calculation execution | `pytest iig_checklist/tests/test_4d3_calculation_execution.py --no-cov -q` | **97 passed**, 62.5 s, exit 0 |
| Execution readiness | `pytest iig_checklist/tests/test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 27.0 s, exit 0 |
| Input resolvers | `pytest iig_checklist/tests/test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 76.1 s, exit 0 |
| Activation validation | `pytest iig_checklist/tests/test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 62.6 s, exit 0 |
| Database-free foundation | `pytest iig_checklist/tests/test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.25 s, exit 0 |
| Execution model / API / lifecycle / response / reviewer | `pytest …test_execution_models.py …test_execution_api.py …test_execution_lifecycle.py …test_response_api.py …test_reviewer_conclusion_api.py --no-cov -q` | **64 passed**, 53.2 s, exit 0 |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …test_lifecycle.py …test_clone_api.py …test_platform_mutation_authorization.py …test_platform_authorization.py tenancy authorization --no-cov -q` | **131 passed**, 81.9 s, exit 0 |
| Full backend suite | `pytest -q` | **1424 passed**, 0 failed, 0 skipped, 447.8 s, exit 0 |
| Coverage | same run | **93.66 %** against a 55 % floor |
| `calculation_execution.py` coverage | same run | **100 %** (179 statements, 0 missed) |
| `calculation_translation.py` coverage | same run | **84 %** (108 statements, 17 missed — the vocabulary self-check error branches, unreachable while the approved vocabularies are in force) |
| `unit_adapter.py` coverage | same run | **95 %** (37 statements, 2 missed) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0, nothing unapplied |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1364 → 1424 (+60) and coverage rose 93.51 % → **93.66 %**.
`calculation_execution.py` went from 96 % with six uncovered lines to **100 %**.
`calculation_translation.py` rose 83 % → 84 % and `unit_adapter.py` 94 % → 95 %,
so no module lost coverage.

Import-linter analysed 911 dependencies (was 895) — the new edge is
`unit_adapter → calculation_translation`, intra-app and inside the existing
contracts. Both are database-free modules and no cycle is introduced:
`calculation_translation` imports neither `unit_adapter` nor any ORM module.

No threshold was lowered, no file excluded, no test weakened or skipped, and no
`pragma`, `noqa`, `skip` or `xfail` was added. One unused `# noqa: BLE001` that
Ruff flagged while this section was being written was **removed** and replaced
with a comment explaining why the broad `except` is correct there.

### Still deferred, unchanged

1. **Governed `AssessmentSnapshot` creation** — no callable service exists.
2. **Cascade recalculation orchestration** — only direct single-response
   execution is implemented.
3. **Result unit for the two difference calculations** — specification gap,
   above.
4. **Durable audit outbox** — repository-wide, above.
5. **External service error codes** (M4D3-OUT-005) — deferred API layer.
6. Unchanged: `update_checklist_response()`, manual override (4D-4),
   applicability persistence, component rebinding, response-history redesign,
   approval automation, reports, exports, dashboards, notifications,
   asynchronous execution, serializers and frontend.

## 6J. Governed `AssessmentSnapshot` creation, and its execution integration

The execution-layer gate closed at **PASS** (independently confirmed twice at
`4d484f3`). This section delivers the blocker every prior section deferred: the
callable governed snapshot service, and the calculation-execution integration it
unblocks.

### The stop condition, now lifted

`AssessmentSnapshot` rows could only be created inside
`iid_assessment/views.py::SnapshotView.post`, bound to a DRF request, serializer,
`request.user` and HTTP response. Snapshot-backed calculation execution therefore
had to accept a caller-supplied object and stay internal-only.

`backend/iid_assessment/services.py` — `create_assessment_snapshot()` — is now
the single authoritative creation path. The API is a thin adapter over it. There
is no second implementation.

### The governed source of truth is the formulation, not the caller

Per M4D3-SRC-004 the service derives every `run_preview()` argument from governed
rows rather than from request fields:

| Argument | Source |
|---|---|
| `active_release_public_id` | resolved server-side, M4D3-SRC-001/003 |
| `route_code`, `dosage_form_code` | `FormulationVersion.product`, subject to Part 14.2 |
| `proposed_quantity_per_unit`, `proposed_quantity_unit` | the `FormulationComponent` |
| `total_dosage_unit_weight`, `…_unit` | the `FormulationVersion` (M4D3-SRC-014) |
| substance identity | the component's `resolved_ingredient_public_id` / `resolved_unii` |
| `maximum_dosage_units_per_day` | caller-supplied; the governed Part 14.1 worst case on the execution path (§6K) |

A caller cannot substitute its own potency, MDE or quantity, so a snapshot always
describes the formulation it names.

**`maximum_dosage_units_per_day` is the governed Part 14.1 worst case,
injected by the caller.** See §6K — this paragraph originally described a
fallback to `FormulationVersion.maximum_dosage_units_per_day` as "import-forced"
and "preview-only". Both were wrong and the fallback is gone.

### Exact release policy

`resolve_active_iid_release()` implements M4D3-SRC-001: the single `fda_iid`
release with `status = "active"`. `unique_active_release_per_dataset_type` makes
at most one row possible, but every match is still collected and anything other
than exactly one fails closed. No `.first()`, no ordering, no "latest" selection.

`ELIGIBLE_RELEASE_STATUSES` is `{active, approved}` — **exactly** what
`find_iid_candidates()` matches against (`release__status__in=[APPROVED, ACTIVE]`).

> **A design correction the tests forced.** The first implementation used
> `{active, superseded}`, reasoning that a superseded release is still
> reproducible. A test showed that is false: the governed matcher excludes
> superseded releases, so pinning one produced a snapshot with null potency — an
> empty regulated record that looks like an assessment. M4D3-SRC-009 forbids 4D-3
> implementing its own selection, so the matcher's own filter is the authority
> rather than a second rule invented here. Superseded releases are now refused.

**Where reproducibility actually lives.** Not in replaying an old release — in
the snapshot already frozen. Tested end to end: release A is snapshotted; A is
superseded and B activated with different values; the first snapshot keeps A's
potency and A's release UUID forever; a later event uses B and its different
values; the first snapshot is never rewritten to point at B; and re-deriving
against A is refused rather than silently producing nothing.

### Always-new (M4D3-SNO-006/008)

Every call constructs a new row. No reuse, no deduplication by value, no update
path, no delete-and-recreate. Two identical calls create two distinct snapshots
with different public UUIDs and the earlier row is untouched.

Proven at the SQL level: creation issues no snapshot `SELECT` other than Django's
own `public_id` uniqueness probe from `full_clean()`, and specifically none keyed
on tenant, component, formulation version, release, or any `ORDER BY` — the shape
a reuse or dedupe lookup would have.

### Ownership, transaction and audit

Ownership is checked before anything else: the formulation version must belong to
the tenant, and the component must belong to that exact formulation version.
Both raise typed exceptions with **empty args** — no database id, SQL, foreign
tenant identifier or raw driver exception.

The caller owns the transaction (M4D3-SNO-012). The service opens none of its
own, commits nothing independently, and schedules its audit through the caller's
`transaction.on_commit()`, so a rollback discards the snapshot and emits no
success audit. `full_clean()` runs before save.

The audit event type and `resource_id` are unchanged; the payload gains the
formulation version, component, release identity and match status. No test
asserted the old payload. Callback-failure behaviour is unchanged from §6I: the
commit stands, the exception propagates, nothing is retried, and the absent
durable outbox remains deferred.

### `SnapshotView` extraction

The view resolves the request's formulation version and component into real
tenant-owned objects, then calls the service. Status codes, permissions, tenant
isolation and the response body are unchanged.

**This tightens the endpoint, deliberately.** Previously the view wrote the raw
request UUIDs into the snapshot with no validation at all, so a caller could
freeze a regulated record naming a formulation that did not exist or one owned
by another tenant. A version that does not exist and one owned by another tenant
are both 404 and indistinguishable from outside, so the endpoint cannot be used
to probe for another tenant's identifiers.

> **One existing test corrected, not weakened.** `test_snapshot_is_immutable`
> named an `IIDIngredient` as the formulation component and an
> `FDADataSourceRelease` as the formulation version — neither is a formulation
> object, and only the absent validation made that possible. It now posts a real
> tenant-owned formulation. The immutability assertion itself is untouched. The
> other three snapshot tests construct rows directly to exercise model
> immutability rather than the endpoint, and are unaffected.

### Execution integration (M4D3-SNO-009)

When a bound entry reads an `AssessmentSnapshot`, `execute_calculation_response()`
resolves the subject component, resolves the active release server-side, calls
`create_assessment_snapshot()` **inside its own transaction**, and hands that
exact object straight to `resolve_calculation_inputs()`. No lookup follows.

`calculation_inputs` gains `resolve_subject_component()`, exposing exactly Phase A
and Phase B. Both entry points call the same `_resolve_subject_component()`
through shared `_validate_target_contract()` and `_locate_upstreams()` helpers, so
the selector, inheritance and disagreement rules cannot diverge. No resolver logic
is duplicated; resolution stays read-only.

A snapshot this transaction creates takes **no lock** — it does not exist yet, so
no other transaction can hold or observe it. The five-step primary-key lock order
of §6I is otherwise unchanged, and a snapshot supplied through the private hook is
still locked in position five.

`snapshot_context` is renamed `_internal_snapshot_context`. It remains for tests
and for server-side callers pinning an exact pre-resolved snapshot, but the
underscore marks it as no part of the callable contract (M4D3-SNO-011). No view,
serializer or task calls the execution service at all, and a test asserts it.

**M4D3-SRC-002 implemented**: with no single active `fda_iid` release the
calculation fails closed with a persisted `status = "error"` /
`reason_code = "FDA_VALUE_UNAVAILABLE"` outcome — not an exception — so the
governed record shows why nothing was calculated. No snapshot is created.

When the subject component cannot be resolved, no snapshot is created either.
That is already a governed resolver failure and the resolver reports it, with
every other failure alongside it, a moment later.

Rollback is proven for a calculation exception, an outcome-validation failure, a
stale `expected_version` and an invalid binding: in every case the snapshot count,
responses, outcomes, history and audit are all unchanged.

### Discovered stop condition — model change and migration

`AssessmentSnapshot.calculation_results` was `JSONField(default=dict)` with
`blank=False`. Django counts `{}` among `Field.empty_values`, so a row holding
this field's own default could not pass `full_clean()`. With no matching IID
precedent `run_preview()` computes nothing and `calculations` is `{}` — so the
governed service could not create a snapshot for exactly the case where one
matters most: the reproducible record that **no precedent existed**. M4D3-SNO-006
requires a snapshot for every governed event, so this blocked a normative
requirement.

Same defect and same remedy as `CalculationOutcome.inputs`/`input_provenance` in
§6G: `blank=True`, `null` unchanged. Migration
`0003_alter_assessmentsnapshot_calculation_results` — one `AlterField`,
reversible, no `RunPython`; `sqlmigrate` emits a pure no-op state change. Nothing
else on the model changed and snapshot immutability is untouched.

No workaround was applied: `full_clean()` was not bypassed, the field was not
excluded from validation, and no filler was written into `calculation_results`.

### Tests

| Module | Tests |
|---|---|
| `iid_assessment/tests/test_snapshot_service.py` (new) | **38** |
| `iig_checklist/tests/test_4d3_calculation_execution.py` | 97 → **112** |
| `iid_assessment` total | 105 → **143** |

The 14 new execution tests cover all four snapshot-backed calculations creating
exactly one fresh snapshot each with the exact release, component and formulation
version; the outcome provenance and audit naming that exact snapshot; a
calculation needing no snapshot creating none; recalculation creating another;
and every rollback and fail-closed path above.

### Post-implementation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| Snapshot service | `pytest iid_assessment/tests/test_snapshot_service.py --no-cov -q` | **38 passed**, 33.1 s |
| IID assessment (all) | `pytest iid_assessment --no-cov -q` | **143 passed**, 41.2 s |
| Calculation execution | `pytest …test_4d3_calculation_execution.py --no-cov -q` | **112 passed**, 77.9 s |
| Execution readiness | `pytest …test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 27.8 s |
| Input resolvers | `pytest …test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 76.2 s |
| Activation validation | `pytest …test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 62.7 s |
| Database-free foundation | `pytest …test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.25 s |
| Execution model / API / lifecycle / response / reviewer | `pytest …` | **64 passed**, 42.1 s |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …` | **131 passed**, 66.2 s |

| Full backend suite | `pytest -q` | **1477 passed**, 0 failed, 0 skipped, 474.4 s, exit 0 |
| Coverage | same run | **93.86 %** against a 55 % floor |
| `calculation_execution.py` coverage | same run | **100 %** (218 statements, 0 missed) |
| `iid_assessment/services.py` coverage | same run | **99 %** (78 statements, 1 missed — the defensive non-`fda_iid` guard reached only through the API path) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0, `0003` applied |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1424 → **1477** (+53) and coverage rose 93.66 % → **93.86 %**.
`calculation_execution.py` stayed at 100 %: the M4D3-SRC-002 and
unresolved-component paths added here were uncovered on first measurement and
tests were added rather than the gap accepted. No threshold was lowered, no file
excluded, no test weakened or skipped, and no `pragma`, `noqa`, `skip` or
`xfail` was added.

### Still deferred

1. **Cascade recalculation orchestration** — only direct single-response
   execution is implemented. Not claimed.
2. ~~**Part 14.1 worst-case maximum-dosage-units threading**~~ — **delivered in
   §6K.** It was never blocked by the import contract, and the fallback it was
   deferred behind affected regulated snapshot fields.
3. **Difference result unit** — the §6I specification gap, untouched here.
4. **Durable audit outbox** — repository-wide, unchanged.
5. **External service error codes** (M4D3-OUT-005) — deferred API layer.
6. Unchanged: `update_checklist_response()`, manual override, applicability
   persistence, component rebinding, response-history redesign, approval
   automation, reports, exports, dashboards, notifications, asynchronous
   execution, broader serializer work and frontend.

## 6K. Remediation of the snapshot review (FAIL → 1 Major, 1 Minor)

An independent adversarial review of §6J returned **FAIL**: 0 Critical, 1 Major,
1 Minor. Both concern M4D3-SRC-004. No specification was amended, no model
changed and no migration added.

### Major — the worst-case daily-units selection was not used

**Finding.** `_create_governed_snapshot()` passed
`maximum_dosage_units_per_day=None`, and the snapshot service then fell back to
`FormulationVersion.maximum_dosage_units_per_day` alone. M4D3-SRC-004 requires
the Part 14.1 selection, which reconciles **two** governed sources and takes the
**higher** (M4D3-MDU-010): the version field, and every `DosingRegimen.maximum_units_per_day`
of that version.

The reviewer measured the consequence on the same formulation:

| | daily exposure | `decision_status` |
|---|---|---|
| Fallback, as shipped in §6J | 30 | `PASS_WITH_IID_PRECEDENT` |
| Part 14.1 worst case | 300 | **`EXCEEDS_IID_PRECEDENT`** |

with `FormulationVersion.maximum_dosage_units_per_day = 1` and a `DosingRegimen`
at 10. A second case was worse in a different way: with the version field null
and only a regimen present — a normal design, the field is nullable — the
fallback passed nothing, so daily exposure became `DATA_REQUIRED` and **every
maximum-daily-exposure calculation disappeared** from `calculation_results`.

Those values reach `decide()` and are frozen as `decision_status`,
`decision_note` and `calculation_results` on an immutable regulated record
exposed by `AssessmentSnapshotSerializer`. The error direction is unsafe: it
makes the stored decision **more favourable** than the governed worst case.

**Two things §6J said about this were wrong.**

*It was never import-forced.* `select_maximum_daily_units()` is a **pure
function** taking plain data — no ORM, no Django model access. The caller,
`_create_governed_snapshot()`, lives in `iig_checklist` and may import it
directly. The contract `iig-checklist-content-is-not-imported-by-governed-domains`
constrains `iid_assessment`, which never needed it, because the service already
accepted `maximum_dosage_units_per_day` precisely so the value could be injected.

*It was not preview-only.* `decision_status` and `decision_note` are decision
fields, not provenance. §6J's narrow claim — that no regulated **4D-3
`CalculationOutcome`** value depends on it — was true and is independently
re-verified below, but it was stated in a way that implied the whole effect was
confined to provenance.

**Change.** `_worst_case_daily_units()` builds `DosingRegimenCandidate` values
from the execution's formulation version and calls the pure selector. Its result
is injected through the existing parameter. The comparison, tie-break and
fail-closed rules stay entirely inside Part 14.1; nothing is reimplemented and
nothing is copied into `iid_assessment`.

**The service's fallback is removed entirely.** It now uses
`maximum_dosage_units_per_day` exactly as supplied and applies no source rule of
its own — using one source where the governed rule uses two is precisely what
caused this. `None` now unambiguously means the caller's governed selection
failed closed (M4D3-MDU-013), leaving the argument unresolved so
`calculate_daily_exposure` canonicalises to `DATA_REQUIRED` (M4D3-MDU-014).

> **Superseded by §6L.** This section left the API path still passing the
> *request's* dosing value into the same governed service, which §6L identifies
> as an M4D3-MDU-006 violation and fixes. The claim below that "the API
> behaviour" was preserved unchanged was accurate but incomplete: it did not
> disclose that the API path applied no Part 14.1 selection at all.

That removal closed a real edge case the fallback had opened: a version field of
`0` is storable (no positivity constraint on that field, unlike `DosingRegimen`),
and the selector correctly rejects it as invalid — but the fallback would have
passed `0` through, yielding a **zero** daily exposure and a falsely favourable
decision. A test pins this.

**The formulation version is now read fresh inside the transaction** rather than
from whatever the caller's `execution` had cached on its FK descriptor. The
worst-case selection and every frozen value derive from it, so a snapshot must
never be built from a stale in-memory copy. This was found by a test that mutated
the formulation and saw the cached value used.

### Minor — evidence corrected

The §6J paragraph is replaced and the deferred-item entry that hid behind it is
struck through. The value is no longer described as preview-only or as blocked by
the import contract.

### Tests

`TestWorstCaseDailyUnits` — **11 tests**, real PostgreSQL, driving the real
execution → governed snapshot path:

| Case | Assertion |
|---|---|
| Regimen 10 > version 1 (the reviewed scenario) | selector picks 10; snapshot exposure 2.5 g; `EXCEEDS_IID_PRECEDENT`, not `PASS_…`; MDE calculations present; decision note names the exceedance |
| Contrast pin | supplying the version field alone still yields `PASS_WITH_IID_PRECEDENT` — the regression this fix exists for |
| Version field null, regimen 8 | selector picks 8; exposure `OK`; MDE calculations retained; no `REVIEW_REQUIRED` from a null field |
| Version 12 > regimens 3, 5 | version field selected; no regimen overrides it |
| Four regimens incl. a tie at 9 | highest selected; stable across repeated evaluation; insertion order irrelevant |
| No regimens | version field used |
| No source at all | fails closed, `DATA_REQUIRED`, no MDE calculations, no invented default |
| Version field `0` | rejected as invalid; no zero-exposure snapshot |
| Selector imported, not reimplemented | no local `max(`; no dosing-regimen logic and no `iig_checklist` reference inside `iid_assessment.services` |
| 4D-3 precedent fields | `iid_potency_amount` / `_unit` / `iid_mde` / `_unit` unchanged; the outcome still completes at 25 |
| Rollback | a calculation exception discards the snapshot and every other write |

### Post-remediation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| M4D3-SRC-004 worst case | `pytest …::TestWorstCaseDailyUnits --no-cov -q` | **11 passed**, 12.6 s |
| Snapshot service | `pytest iid_assessment/tests/test_snapshot_service.py --no-cov -q` | **38 passed**, 24.3 s |
| IID assessment (all) | `pytest iid_assessment --no-cov -q` | **143 passed**, 30.7 s |
| Calculation execution | `pytest …test_4d3_calculation_execution.py --no-cov -q` | **123 passed**, 77.0 s |
| Execution readiness | `pytest …test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 21.0 s |
| Input resolvers | `pytest …test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 56.6 s |
| Activation validation | `pytest …test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 46.0 s |
| Database-free foundation | `pytest …test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.25 s |
| Execution model / API / lifecycle / response / reviewer | `pytest …` | **64 passed**, 40.4 s |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …` | **131 passed**, 62.8 s |
| Full backend suite | `pytest -q` | **1488 passed**, 0 failed, 0 skipped, 500.7 s, exit 0 |
| Coverage | same run | **93.90 %** against a 55 % floor |
| `calculation_execution.py` coverage | same run | **100 %** (225 statements, 0 missed) |
| `max_daily_units.py` coverage | same run | **100 %** (67 statements, 0 missed) |
| `iid_assessment/services.py` coverage | same run | **99 %** (78 statements, 1 missed — the `has_iid_reference` convenience property) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1477 → **1488** (+11) and coverage rose 93.86 % → **93.90 %**.
The new import edge is `calculation_execution → max_daily_units`, intra-app and
inside the existing contracts; `iid_assessment` still imports no `iig_checklist`
module and no cycle exists. No threshold was lowered, no file excluded, no test
weakened or skipped, and no `pragma`, `noqa`, `skip` or `xfail` was added.

### Contract preserved

Unchanged by this remediation: the single governed creation path; always-new;
exact active/approved release selection; exact component and formulation
validation; tenant isolation; the immutable result; the `on_commit` audit; a
fresh snapshot per event; rollback; and the internal-bypass restriction. No
cascade orchestration, no model, no migration. **The API path is corrected in
§6L** — this section's "API behaviour unchanged" was true only of valid
requests.

## 6L. Remediation of the SnapshotView review (FAIL → 1 Major, 1 Minor)

A focused confirmation review of §6K returned **FAIL**: 0 Critical, 1 Major,
1 Minor. The execution path was confirmed fixed; the defect survived on the other
snapshot-creation path.

### Major — the persisted API accepted a client dosing value

**Finding.** `SnapshotView` passed `data.get("maximum_dosage_units_per_day")`
straight into `create_assessment_snapshot()`. **M4D3-MDU-006**: *"no dosing value
shall ever be accepted from a client request payload"*, and the acceptance matrix
names the request serializer as the enforcement point
(`M4D3-MDU-006 | Request serializers | TST-328 | No client-supplied dosing value | Security`).

Reproduced through the authenticated API on a formulation carrying a governed
`DosingRegimen` of 10:

| Path | daily exposure | `decision_status` |
|---|---|---|
| `SnapshotView`, client posts `1` | 30 | `PASS_WITH_IID_PRECEDENT` |
| Governed Part 14.1 worst case | 300 | **`EXCEEDS_IID_PRECEDENT`** |

This was §6K's Major, unfixed on the API path. §6J had made the view a caller of
the governed service and §6K established Part 14.1 as the rule for that service's
callers — leaving one caller applying the rule and one accepting client input.

**Change.** `SnapshotRequestSerializer` no longer accepts the field: it is popped
from `fields`, so it is absent from the endpoint's contract and its schema, and a
request that supplies it is **rejected** with a structured 400
(`error_code = "prohibited_request_field"`) rather than silently ignored. A caller
who believes they set the dosing basis for a regulated assessment must not be
told it succeeded.

`MatchPreviewRequestSerializer` keeps the field. That endpoint persists nothing,
so a caller exploring a hypothetical dosing figure freezes no regulated record;
M4D3-MDU-006 governs the snapshot, which is immutable and whose `decision_status`
depends on the value.

`SnapshotView` now derives the value server-side, from a formulation version read
fresh inside its transaction.

### One helper, both callers

The selection is no longer written twice. `formulations.dosing` provides
`resolve_governed_maximum_daily_units()` and
`governed_maximum_daily_units_value()`, collecting both governed sources and
calling the selector. The checklist execution service and the API view both use
it, and a test asserts they bind the *same function object*.

**The pure selector moved to `common.max_daily_units`.** M4D3-MDU-006 requires
the `iid_assessment` endpoint to apply Part 14.1, and
`iig-checklist-content-is-not-imported-by-governed-domains` forbids
`iid_assessment` importing anything from `iig_checklist` — so a selector living
only there was unreachable from the endpoint that needed it. The algorithm is
pure (`dataclasses`, `Decimal`, no ORM, no Django), so `common` is where a
shared domain-free rule belongs.

`iig_checklist.max_daily_units` remains as a re-export, so the governed module
identity that M4D3-MDU-001..024 and the acceptance matrix refer to keeps its name
and import path, and every existing importer and its 183 foundation tests are
untouched. **Nothing about the selection changed**: not the two sources, not the
M4D3-MDU-010 reconciliation, not the M4D3-MDU-008 tie-break, not the
M4D3-MDU-013/014 fail-closed contract. `select_maximum_daily_units` remains the
sole scientific selector. All seven import contracts stay green and no cycle is
introduced.

### API compatibility — an intentional correction

* A valid request that does **not** contain the prohibited field keeps the same
  endpoint, permissions, tenant isolation, 201 status and response body.
* A request that **does** contain it now fails with a structured 400.
* This is a deliberate security and specification correction, not accidental
  breakage. M4D3-MDU-006 takes precedence over backward compatibility for
  prohibited regulated input, and no compatibility path silently accepts the
  field.
* An unknown alternate spelling or a nested attempt is inert — nothing reads it —
  and the governed worst case still applies. Tests assert both.

### Unresolved selection

When the selector fails closed the view passes `None`, exactly as the execution
path does: the argument is left unresolved, `calculate_daily_exposure`
canonicalises to `DATA_REQUIRED`, no MDE comparison is produced, and no
favourable decision is fabricated. A zero or negative version scalar with no
valid regimen reaches the same state; a zero scalar *with* a valid regimen uses
the regimen.

### Minor — evidence corrected

§6K's statement that "the API behaviour" was preserved is marked superseded, and
the paragraph that described the fallback removal as restoring the API's original
semantics now records that it left the M4D3-MDU-006 violation in place.

### Tests

`TestClientDosingValueProhibited` — **24 tests**, real PostgreSQL, through the
authenticated API:

| Area | Coverage |
|---|---|
| Field refused | structured 400 naming the field; no snapshot; no audit |
| Every client shape | `0`, `1`, `999`, `null`, negative, non-numeric string, int, float — all 400 |
| Cannot be reintroduced | three alternate spellings and a nested attempt are inert; the governed worst case still applies |
| Not advertised | absent from `SnapshotRequestSerializer().fields`, still present on `MatchPreviewRequestSerializer` |
| The reviewed scenario | version 1 + regimen 10 → exposure 300, `EXCEEDS_IID_PRECEDENT`, MDE calculations present, one audit event |
| Selection matrix via API | null scalar → regimen 8; scalar 12 > regimens 3/5; no regimens → scalar; no source → `DATA_REQUIRED`; zero/negative alone → `DATA_REQUIRED`; zero + regimen 6 → 6 |
| One helper | the view binds the shared helper; the checklist side asserts both bind the same object, because `iid_assessment` may not import `iig_checklist` even in tests |

Two existing API tests were corrected to stop sending the now-prohibited field.
Their assertions are otherwise untouched.

### Post-remediation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| SnapshotView M4D3-MDU-006 | `pytest …::TestClientDosingValueProhibited --no-cov -q` | **24 passed**, 18.4 s |
| Snapshot service | `pytest iid_assessment/tests/test_snapshot_service.py --no-cov -q` | **62 passed**, 37.6 s |
| IID assessment (all) | `pytest iid_assessment --no-cov -q` | **167 passed**, 44.2 s |
| Calculation execution | `pytest …test_4d3_calculation_execution.py --no-cov -q` | **124 passed**, 85.1 s |
| Execution readiness | `pytest …test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 22.8 s |
| Input resolvers | `pytest …test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 61.7 s |
| Activation validation | `pytest …test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 49.7 s |
| Database-free foundation | `pytest …test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.29 s |
| Formulations | `pytest formulations --no-cov -q` | **21 passed**, 14.3 s |
| Common | `pytest common --no-cov -q` | **10 passed**, 7.9 s |
| Execution model / API / lifecycle / response / reviewer | `pytest …` | **64 passed**, 43.3 s |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …` | **131 passed**, 69.3 s |
| Full backend suite | `pytest -q` | **1513 passed**, 0 failed, 0 skipped, 529.3 s, exit 0 |
| Coverage | same run | **93.95 %** against a 55 % floor |
| `common/max_daily_units.py` coverage | same run | **100 %** (67 statements, 0 missed) |
| `formulations/dosing.py` coverage | same run | **100 %** (10 statements, 0 missed) |
| `calculation_execution.py` coverage | same run | **100 %** (223 statements, 0 missed) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, 956 dependencies analysed |

The suite grew 1488 → **1513** (+25) and coverage rose 93.90 % → **93.95 %**. No
model and no migration: the selector relocation is a file move plus a re-export,
and `makemigrations --check` confirms no model-state drift. No threshold was
lowered, no file excluded, no test weakened or skipped, and no `pragma`, `noqa`,
`skip` or `xfail` was added.

### Still deferred

Unchanged: cascade recalculation orchestration; the difference result-unit
specification gap (§6I); the durable audit outbox; external execution API
error-code mapping (M4D3-OUT-005); and the wider deferred list of §6J.

## 6M. Form C daily-units consolidation (snapshot gate CLOSED, 1 Minor)

The focused confirmation review of §6L returned **PASS WITH MINOR CORRECTIONS**
and closed the snapshot-service gate: 0 Critical, 0 Major, 1 Minor. This section
clears that Minor before cascade orchestration.

### Minor — Form C duplicated the ORM collection and the freshness policy

**Finding.** §6L consolidated the two *snapshot* callers onto
`formulations.dosing`, but a third consumer of the same governed rule was left
untouched. `calculation_inputs._resolve_maximum_daily_units()` (Form C) still
read `execution.formulation_version`, built its own `DosingRegimenCandidate`
tuple, queried `DosingRegimen` itself and called `select_maximum_daily_units()`
directly.

The *scientific selector* was never duplicated — every site called the one pure
function — but the **ORM candidate collection and the freshness policy existed
in two places**, and they differed in one respect that matters:
`execution.formulation_version` is a lazily-loaded FK that keeps whatever the row
looked like when the caller first touched it, while snapshot creation reads the
row fresh. A caller passing a stale execution could therefore have Form C resolve
daily units from cached formulation data while the snapshot frozen in the *same
transaction* resolved from current state — the exact class of divergence §6K and
§6L exist to close.

No value was wrong at the time of the finding: both collections were written
identically. The risk was latent drift.

**Change.** `formulations.dosing` gains the identity-based entry point:

```
current_formulation_version(formulation_version_id)
resolve_current_maximum_daily_units(*, formulation_version_id) -> MaxDailyUnitsSelection
```

Form C now calls `resolve_current_maximum_daily_units(formulation_version_id=execution.formulation_version_id)`.
It resolves from the raw FK column rather than the cached relation, so the stale
copy can never be consulted. `DosingRegimenCandidate`, `select_maximum_daily_units`
and the `DosingRegimen` import are **removed** from `calculation_inputs` — the
duplicated path is deleted, not merely bypassed, and a test asserts none of those
names remains in the module.

The governed public identity comes from the selector's own provenance
(`formulation_version_public_id`), so naming the source costs no second read.

**Behaviour is preserved exactly.** Both query forms were already equivalent:
`FormulationVersionRelatedManager` only adds a `for_tenant()` convenience method
and does **not** override `get_queryset()`, so `DosingRegimen.objects.filter(...)`
and `formulation_version.dosing_regimens.all()` return the same base queryset,
and both sites ordered by `public_id`. The 106 resolver tests passed unchanged
with no edits.

### One governed selection path, three consumers

| Consumer | Entry point |
|---|---|
| Persisted snapshot API (`SnapshotView`) | `governed_maximum_daily_units_value()` |
| Checklist execution snapshot creation | `governed_maximum_daily_units_value()` |
| Form C input resolution | `resolve_current_maximum_daily_units()` |

All three funnel into `resolve_governed_maximum_daily_units()` and thence into
the single `select_maximum_daily_units()`. A test asserts the two snapshot
callers bind the *same function object* and that Form C imports the identity
entry point of the same module.

### Tests

`TestFormCDailyUnitsConsistency` — **16 tests**, real PostgreSQL:

| Area | Coverage |
|---|---|
| Freshness, case A | the version scalar changes after the FK is cached; the cached relation still reports the old value, Form C resolves the new one |
| Freshness, case B | a regimen added after caching is seen |
| End-to-end agreement | under a stale execution, Form C and the snapshot worst case return the same value |
| Equivalence matrix | regimen greater, version greater, version null, no regimens, multiple with a tie, zero scalar with a valid regimen — Form C equals the shared helper on value *and* `detail_code` |
| Unresolved cases | null/zero/negative with no regimen: both unresolved, `FORMULATION_FIELD_MISSING` preserved with the formulation public UUID |
| Contract preservation | all ten provenance keys, `source_public_uuid`, `expected_type`, recursive immutability, no database id, no exponent notation |
| Read-only | no INSERT/UPDATE/DELETE, no `FOR UPDATE`, no audit |
| Duplication removed | `DosingRegimenCandidate`, `select_maximum_daily_units` and `DosingRegimen` absent from `calculation_inputs` |
| Three callers | one governed selection path, asserted |

### Intermediate-commit disclosure, corrected

§6L's remediation was reported as "commits 1 and 2 are not independently green".
Verified in isolated worktrees, that overstated it:

| Commit | Import check |
|---|---|
| `1829aca` | **fails** — `ModuleNotFoundError: No module named 'formulations.dosing'` |
| `a75e214` | imports cleanly |
| `0a76735` | imports cleanly, tests green |
| `4a2f6aa` | fully green |

Only **one** commit is not buildable, caused by `git mv` pre-staging the selector
rename into the first commit. No repository policy is violated:
`.github/workflows/backend.yml` triggers only on push to `regx-main` and pull
requests to `regx-main`, and no document requires every commit to build. The
impact is on bisectability alone — `git bisect` across that range needs one
`skip`. The final head is correct and internally consistent. **Observation, not a
technical defect**; history was not rewritten.

### Serializer declared-fields observation

Still true and still safe: `SnapshotRequestSerializer._declared_fields` retains
`maximum_dosage_units_per_day` by inheritance from
`MatchPreviewRequestSerializer`, while the instantiated serializer's `.fields`
excludes it and the generated OpenAPI schema contains it **nowhere** —
drf-spectacular instantiates the serializer, so the dynamic removal is effective
for the generator actually in use. Runtime and schema are both safe. Future
tooling that introspects `_declared_fields` directly rather than an instance
would need hardening. Not changed here: the serializer contract is out of scope
for this correction and the current behaviour is correct.

### Post-remediation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| Form C consistency | `pytest …::TestFormCDailyUnitsConsistency --no-cov -q` | **16 passed**, 18.3 s |
| Input resolvers | `pytest …test_4d3_calculation_inputs.py --no-cov -q` | **106 passed**, 74.2 s — unchanged, no edits |
| SnapshotView M4D3-MDU-006 | `pytest …::TestClientDosingValueProhibited --no-cov -q` | **24 passed**, 21.3 s |
| Snapshot service | `pytest iid_assessment/tests/test_snapshot_service.py --no-cov -q` | **62 passed**, 40.8 s |
| IID assessment (all) | `pytest iid_assessment --no-cov -q` | **167 passed**, 40.7 s |
| Calculation execution | `pytest …test_4d3_calculation_execution.py --no-cov -q` | **140 passed**, 102.2 s |
| Execution readiness | `pytest …test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 26.5 s |
| Activation validation | `pytest …test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 60.5 s |
| Database-free foundation | `pytest …test_4d3_foundation.py --no-cov -q` | **183 passed**, 0.28 s |
| Formulations | `pytest formulations --no-cov -q` | **21 passed**, 12.8 s |
| Execution model / API / lifecycle / response / reviewer | `pytest …` | **64 passed**, 39.4 s |
| Lifecycle / clone / platform auth / tenancy / authorization | `pytest …` | **131 passed**, 62.2 s |
| Full backend suite | `pytest -q` | **1529 passed**, 0 failed, 0 skipped, 488.2 s, exit 0 |
| Coverage | same run | **93.99 %** against a 55 % floor |
| `formulations/dosing.py` coverage | same run | **100 %** (15 statements, 0 missed) |
| `common/max_daily_units.py` coverage | same run | **100 %** |
| `calculation_execution.py` coverage | same run | **100 %** (223 statements, 0 missed) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1513 → **1529** (+16) and coverage rose 93.95 % → **93.99 %**.
`calculation_inputs.py` shrank by the deleted duplication and holds its 94 %. No
model, no migration, no serializer or view change: the correction is confined to
`formulations/dosing.py`, `calculation_inputs.py` and tests. No threshold was
lowered, no file excluded, no test weakened or skipped, and no `pragma`, `noqa`,
`skip` or `xfail` was added.

### Still deferred

Unchanged: cascade recalculation orchestration; the difference result-unit
specification gap (§6I); the durable audit outbox; external execution API
error-code mapping (M4D3-OUT-005); and the wider deferred list of §6J.

## 6N. Cascade recalculation orchestration

Closes the largest remaining gap of Milestone 4D-3. Every earlier section
recalculated **one** response at a time; this one implements M4D3-RCL — when a
governed response changes, every outcome that consumes it is recalculated, in a
deterministic order, inside one transaction.

Six commits, `cd1b86c` → `5bf820b`, on `regx/feat/milestone-4d-3`.

### Form B freshness, hardened first (`cd1b86c`)

§6M closed the Form C duplication. Auditing the remaining `execution.<relation>`
uses in the resolver found the same defect class in Form B.
`_resolve_formulation_field()` read `execution.formulation_version`, a
lazily-loaded FK that keeps whatever the row held when the caller first touched
it. The values it reads — `total_dosage_unit_weight` and its unit — are regulated
inputs to `percentage_w_w`, and a governed `AssessmentSnapshot` freezes that same
weight from the **current** row in the same transaction. A cached copy could put
two different formulation states into one calculation.

It now reads through `formulations.dosing.current_formulation_version()`, the one
shared helper Form C already uses.

**The §14 audit of the other forms found no further instances.**

| Resolver form | Read path | Staleness risk |
|---|---|---|
| A — `question_response` | `_responses_for_question()` queries fresh | none |
| B — `formulation_field` | **was** `execution.formulation_version` | **fixed here** |
| C — `maximum_daily_units` | `resolve_current_maximum_daily_units()` | none (§6M) |
| D — `assessment_snapshot` | the caller's exact locked snapshot, `tenant_id` compared | none by design |
| E — `calculation_outcome` | `_locate_upstream()` queries `CalculationOutcome` fresh | none — and this is what makes a cascade dependant see its upstream's new value |
| F — `constant` | registry only, no ORM | none |
| subject component | `_component_in_execution()` queries fresh, scoped by `formulation_version_id` | none |

The one remaining use of `execution.tenant` is passed to
`validate_raw_value_shape()` for tenant scoping, not read as a regulated value.

Four tests, each of which **fails** against the previous implementation
(verified by reverting the fix): a stale cached scalar bypassed; a stale cached
unit bypassed, visible as a 1000× conversion rather than a silent equality; Form
B and a fresh read agreeing on one weight; and Form B and Form C sharing one read
path. Behaviour preservation was established first — the existing 246 resolver
and execution tests passed with **no edits** before those four were added.

### The normative matrix, read before coding

Per §3 of the brief, the cascade rules were taken from the specification rather
than inferred. Nothing below is a design choice.

| Clause | What it requires | Where it lands |
|---|---|---|
| M4D3-RCL-001 | cascade keyed on `recalculation_triggers`, explicitly **not** `calculation_dependencies` | `affected_nodes_for_trigger()` |
| M4D3-RCL-006 | resolve changed identity → directly affected set → expand through `calculation_dependencies` → union in stable topological order → lock in Part 17 order → recalculate in the same transaction | `recalculate_dependents()`, steps 1–5 |
| M4D3-RCL-007 | a non-trigger response recalculates nothing, changes no version, emits no audit | early return, `triggered=False` |
| M4D3-RCL-002 / DAG-006 | stable topological order, tie-break ascending `ChecklistQuestion.code` | `_topological_order()` — **corrected**, below |
| M4D3-RCL-003 | outcome rows updated in place, `full_clean()` before each save | already owned by the execution service |
| M4D3-RCL-004 | no audit and no version change when `status`, `value`, `reason_code` and `generated_at` are all unchanged | `_suppress_unchanged_audit`, below |
| M4D3-RCL-005 | terminal and submitted executions never auto-recalculated | `RECALCULABLE_EXECUTION_STATUSES` allow-list |
| M4D3-DAG-005 | Kahn's or equivalent iterative; unbounded recursion prohibited | pre-existing, unchanged |
| M4D3-DAG-010 | a visited set; each node runs at most once | `dict.fromkeys()` over the graph order |
| M4D3-RBD-008 | "dependency-graph failure, and stale `expected_version`" are among the structural failures that "roll back the entire" operation | whole-cascade rollback |

**§11 of the brief said "do not invent this choice" about rollback vs partial
completion. It was not invented.** M4D3-RBD-008 names both failure modes
explicitly, so the cascade is all-or-nothing: one blocking failure discards every
outcome, snapshot and audit of the event.

**There is no cascade summary audit event, and this too is read, not chosen.**
M4D3-RCL-006 requires the per-calculation success audit after commit. No approved
clause and no constant in `iig_checklist/audit.py` defines a cascade-level event —
`RECALC` and `CASCADE` appear nowhere in it. Adding one would be inventing
governed vocabulary.

### The dependency graph, ORM side (`1a056bf`)

`calculation_graph` was already pure and complete — edge derivation, Kahn
ordering, cycle detection, the depth limit and the cascade node limit. Nothing
built its nodes from the database. `build_execution_graph()` is that half.

| Decision | Clause | Why |
|---|---|---|
| node identity is the **response** public UUID | M4D3-DEP-007 | two questions bound to one function stay distinct |
| the query is scoped to the execution | M4D3-DAG-009 | one `ChecklistVersion`, one tenant; a graph can never span versions |
| nodes are **not** filtered | M4D3-RBD-008 | an unapproved binding raises `UNKNOWN_REGISTRY_IDENTIFIER`; skipping it would recalculate part of the graph and leave the rest silently stale |
| `CascadeGraphInvalid` carries `error_code` + question codes | — | never a database id, never a raw exception |

Read-only: no transaction, no lock, no write — asserted by capturing SQL and
requiring the verb set to be exactly `{SELECT}` with no `FOR UPDATE`.

### A defect the cascade exposed — the DAG-006 tie-break (`b9aa82c`)

**Found while writing the ordering tests, not by inspection.**

M4D3-DAG-006 names the tie-break for equal-precedence nodes exactly: ascending
`ChecklistQuestion.code`. `_topological_order()` sorted by `node_id`.

The two were indistinguishable until now. Every existing pure-graph test passes
node ids (`"n-exposure"`, `"n-pct"`) that happen to sort the same way as their
question codes, and nothing built nodes from the database.
`build_execution_graph()` does, and its node identity is the governed response
public UUID — effectively random. Keyed on it:

- two executions carrying exactly the same six questions would recalculate them
  in **different** orders;
- repeated runs of one execution would agree only by accident.

The sort key is now `(question_code, node_id)`, applied both to the initial ready
set and to nodes released mid-sort. Question codes are already unique within a
graph (`_index_by_question_code` enforces it), so the code alone is a total
order; `node_id` keeps the key total by construction.

Two regression tests, both failing against the previous implementation, use node
ids and codes that are deliberately **opposed** (`"zzz"`/`Q_AAA` vs
`"aaa"`/`Q_ZZZ`), so only the correct key produces the asserted order. The full
1601-test suite passing with the corrected key is itself the evidence that no
existing behaviour depended on the node-id ordering.

### The orchestration service (`31d7686`)

```
recalculate_dependents(*, tenant, execution, changed_response, actor,
                       expected_version) -> CascadeRecalculationResult
```

M4D3-RCL-006 implemented in order:

| Step | Action |
|---|---|
| A | caller contract — response in execution, execution in tenant. No lock, no write |
| 1 | `ChecklistExecution` locked; M4D3-RCL-005 status checked **under the lock**, so the state examined is the committed state |
| 2 | the changed response locked; `expected_version` checked against the locked row |
| 3 | graph built and the affected set resolved — read-only, and a graph fault raises **here**, before any further lock or write |
| 4 | every affected response, then every affected outcome, each `ORDER BY id ASC ... FOR UPDATE`, taken as one set before any recalculation |
| 5 | each target executed in stable topological order, once |

**It is not a second calculation writer.** Every target goes through
`execute_calculation_response()`, which stays the sole owner of function
invocation, engine translation, outcome persistence, provenance, snapshot
creation and audit. The module never names the engine, never touches an outcome
field and never dispatches audit — asserted against its **parsed AST**, not its
text, because the module documents at length what it does not do and a substring
sweep would flag its own prose.

**Two ORM details worth recording.**

Neither batched lock uses `select_related`: on PostgreSQL a joined
`SELECT … FOR UPDATE` would also lock `checklistquestion`, adding a table the
Part 17 order does not contain. The locked rows are then re-read with a plain
`SELECT` inside the transaction, so the `version` handed to the writer is the
value under our own lock rather than whatever the pre-lock scan saw.

### M4D3-RCL-004 — why the flag lives in the writer

The clause suppresses the audit event when `status`, `value`, `reason_code` and
`generated_at` are all unchanged. Only the writer can evaluate that: it alone
sees the outcome row before and after the write, under the lock, and it alone
owns the `on_commit` dispatch. So `execute_calculation_response()` gained a
private `_suppress_unchanged_audit` parameter rather than the cascade emitting or
withholding audit itself.

| Property | Value |
|---|---|
| fields compared | exactly the four the clause names — `updated_at` and `input_provenance` move on every write and are deliberately excluded |
| default | `False`, so direct single-response execution is untouched |
| set by | the cascade service only |
| surfaced as | `CalculationExecutionResult.audit_suppressed`, `CascadeTarget.audit_suppressed`, `CascadeRecalculationResult.audited_count` |

The clause's companion requirement, "no version change", needs **no code**:
recalculation never writes `ChecklistResponse.version` on a calculated response
(M4D3-MDL-006), and a test asserts every version is unchanged after a cascade.

Widening the comparison would suppress audit for a recalculation that *did*
change a governed value; narrowing it would emit an event the clause forbids.

### Tests (`a630f6a`, `5bf820b`)

**65 tests**, real PostgreSQL, no mocked QuerySets or managers.

The approved six-entry registry already contains a genuine two-level cascade, so
the primary fixture needs no synthetic registry:

```
Q_SUBJECT_COMPONENT   (user-required selector — no graph edge at all)
  --recalculation_triggers--> percentage_w_w
                              daily_exposure            (= Q_DAILY_EXPOSURE)
                              percentage_of_iid_potency
                              difference_from_iid_potency

Q_DAILY_EXPOSURE      (both a trigger and a calculation_dependency)
  --------------------------> percentage_of_iid_mde
                              difference_from_iid_mde
```

That is M4D3-RCL-001 in one fixture: the selector creates no edge, yet changing
it recalculates all six, ordered so `daily_exposure` precedes the two
calculations that read its outcome.

| Group | Coverage |
|---|---|
| Graph discovery | all six become nodes; identity is the response UUID; user-input questions are not nodes; edges come only from `calculation_dependencies`; discovery is read-only; another execution's responses never enter; an execution with no calculations yields a valid empty graph |
| Governed graph faults | cycle; self-dependency; dependency outside the version; depth beyond the limit; unapproved binding **rejected, not skipped**; a fault aborts before any write; the error carries no database id |
| Trigger identification | the selector cascades to all six; a non-trigger response recalculates nothing and issues no `UPDATE`/`INSERT` at all; a trigger reaches only its declared consumers |
| Ordering | upstream before dependants; independent nodes by ascending code; stable across runs; **independent of response public ids**, proven with a sibling execution carrying the same codes on different UUIDs; a dependant consumes the upstream value written in the same cascade, checked through `upstream_outcome_public_ids` |
| Writer boundary | every target passes through `execute_calculation_response()`; the AST assertion; no ORM object leaks; the result is frozen |
| Outcome persistence | rows updated in place, same pk and public id, no row count change; a second cascade reuses them; response versions unchanged; **end-to-end value assertion** — doubling the component quantity moves `percentage_w_w` 25 → 50, `daily_exposure` 1 g → 2 g, `percentage_of_iid_mde` 50 → 100 |
| Audit | one event per target; no cascade summary event invented; M4D3-RCL-004 suppression; a changed recalculation still audits; direct execution always audits; a rolled-back cascade emits nothing |
| Atomicity | an engine fault part-way through discards **every** outcome; no snapshot survives a rollback; a stale `expected_version` writes nothing; the version is checked against the committed row |
| Snapshots | one new snapshot per snapshot-backed target (M4D3-SNO-006); a second cascade creates a second generation; outcomes reference the snapshot from their own cascade |
| Execution state | all five non-recalculable statuses refused (parametrised); DRAFT and RETURNED proceed; the allow-list is disjoint from `TERMINAL_EXECUTION_STATUSES`; the status is read under the lock, proven with a genuinely stale in-memory copy |
| Isolation | a foreign tenant refused; a response from another execution refused; a cascade never touches another execution's outcomes |
| Lock order | the execution first; every multi-row lock `ORDER BY … id ASC`; responses before outcomes; **the whole affected set held before the first target runs** |
| Result contract | origin identity; governed codes and 36-character UUIDs only; counts agree; target order equals the graph order |

Two test-construction notes worth recording, because both could have produced a
test that passes for the wrong reason:

- The lock-order test examines only the queries issued **before** the first
  target call, because `execute_calculation_response()` takes its own batched
  locks per target. It then requires the cascade's own response lock to contain
  all six affected ids and the outcome lock to follow it.
- The M4D3-RCL-004 test deletes the FDA precedent first. The engine stamps
  `generated_at` fresh on every successful result, so a repeated *successful*
  recalculation always differs in that field; a stable `DATA_REQUIRED` outcome
  (`generated_at` = `None`) is the only state in which a second run genuinely
  changes none of the four governed fields. Companion tests assert a changed
  recalculation still audits and that direct execution always audits, so the
  suppression cannot degenerate into blanket cascade silence.

Synthetic registries are installed with `monkeypatch` only where the approved
entries cannot express the case — a cycle, a self-dependency, an over-deep chain.
No committed registry definition is mutated.

`create_execution` refuses a second active execution per formulation version, so
the isolation and ordering-independence tests build a sibling execution on its
own product and formulation.

### Post-implementation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| Cascade | `pytest …test_4d3_cascade.py --no-cov -q` | **65 passed**, 70.9 s |
| Database-free foundation | `pytest …test_4d3_foundation.py --no-cov -q` | **186 passed**, 0.24 s |
| Input resolvers | `pytest …test_4d3_calculation_inputs.py --no-cov -q` | **110 passed**, 76.5 s |
| Calculation execution | `pytest …test_4d3_calculation_execution.py --no-cov -q` | **140 passed**, 112.0 s |
| Execution readiness | `pytest …test_4d3_execution_readiness.py --no-cov -q` | **59 passed**, 26.2 s |
| Activation validation | `pytest …test_4d3_activation_validation.py --no-cov -q` | **59 passed**, 44.5 s |
| IID assessment (all) | `pytest iid_assessment --no-cov -q` | **167 passed**, 53.7 s |
| Formulations | `pytest formulations --no-cov -q` | **21 passed**, 15.7 s |
| Full backend suite | `pytest -q` | **1601 passed**, 0 failed, 0 skipped, 659.7 s, exit 0 |
| Coverage | same run | **94.22 %** against a 55 % floor |
| `cascade.py` coverage | targeted run | **100 %** (86 statements, 0 missed) |
| `calculation_graph.py` coverage | targeted run | **100 %** (112 statements, 0 missed) |
| `calculation_execution.py` coverage | targeted run | **100 %** |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1529 → **1601** (+72: 4 Form B, 65 cascade, 3 graph boundary) and
coverage rose 93.99 % → **94.22 %**. No model, no migration, no serializer, no
view and no frontend change. No threshold lowered, no file excluded, no test
weakened or skipped, and no `pragma`, `noqa`, `skip` or `xfail` added.

### Per-commit buildability

Verified in isolated worktrees — the §6M disclosure exists because this was not
checked at the time.

| Commit | Imports in isolation | Own tests |
|---|---|---|
| `cd1b86c` Form B freshness | OK (3 modules) | 110 passed |
| `1a056bf` dependency graph | OK (4 modules) | 183 passed |
| `b9aa82c` DAG-006 tie-break | OK (4 modules) | 185 passed |
| `31d7686` orchestration | OK (4 modules) | — |
| `a630f6a` cascade tests | OK (4 modules) | 64 passed |
| `5bf820b` empty-graph boundary tests | OK (4 modules) | 65 passed |

All six commits build independently. `git bisect` across this range needs no
`skip`.

> **Correction (§6O).** The `5bf820b` row above was added during the §6O
> remediation. As first written this table listed five rows while the sentence
> beneath it claimed six commits build independently — the sixth was verified
> but not recorded. The independent cascade review raised this as Minor 3, and
> it was a genuine omission in the evidence, not in the verification.

### Commit-plan deviation, disclosed

The brief's §28 named five commits. Six were made. The two additions are both
deliberate separations rather than scope creep:

- `b9aa82c` — the DAG-006 tie-break is a **defect fix in a different module**,
  found while writing the ordering tests. Folding it into the cascade feature
  commit would have hidden a correctness change inside a feature.
- `5bf820b` — the empty-graph boundary tests extend two already-committed test
  files and close the last uncovered branch in the graph layer.

### Still deferred

Unchanged: the difference result-unit specification gap (§6I); the durable audit
outbox; external execution API error-code mapping (M4D3-OUT-005); and the wider
deferred list of §6J.

**Not authorised and not done:** frontend; reports and exports; approval
automation; manual override and deviation; component rebinding; async/Celery
orchestration; any general-purpose rules engine; `eval` or dynamic expressions;
arbitrary SQL dependencies; PR creation; merge.

**No trigger surface was added.** `recalculate_dependents()` is a callable domain
service. No view, serializer, signal or task calls it, and no client-reachable
path can steer a dependency list into it — dependencies come only from the
immutable approved registry.

## 6O. Remediation of the independent cascade review (FAIL → 1 Major, 3 Minor)

The independent review of the cascade at `88f6f24` returned **FAIL**: 0 Critical,
**1 Major**, 3 Minor.

### Major — the cascade did not use the governed expected-version contract

`recalculate_dependents()` validated the caller's `expected_version` by comparing
it to the locked row directly:

```python
if locked_origin.version != expected_version:
    raise StaleResponseVersion()
```

The single-response writer had, since §6H, routed the same parameter through a
governed structural gate (`_validate_expected_version()`, M4D3-TXN-003) that
rejects `None`, `bool`, non-`int` and anything below 1 with
`InvalidExpectedVersion`, in Phase A, before a lock is taken. The cascade
restated the check instead of reusing it, and the two therefore disagreed.

The review measured the consequences, and they reproduce exactly:

| Supplied value | Origin at version 1 — before | After |
|---|---|---|
| `True` | **accepted** — `True == 1` | `InvalidExpectedVersion` |
| `1.0` | **accepted** — `1.0 == 1` | `InvalidExpectedVersion` |
| `None`, `"1"`, `0`, `-1`, `1.5`, `[1]`, `{}` | `StaleResponseVersion` — misclassified | `InvalidExpectedVersion` |
| `2` | `StaleResponseVersion` | `StaleResponseVersion` — unchanged |
| `1` | accepted | accepted — unchanged |

Two distinct defects, one root cause. `True` and `1.0` **bypassed the origin
concurrency gate entirely** whenever the changed response stood at version 1 —
which is where every freshly created response stands — so a malformed value
silently disabled the optimistic-concurrency check the milestone requires to be
mandatory. Every other malformed value was reported as a *stale version*, which
tells a caller to re-read and retry when the real fault is a malformed request
that no retry can fix.

**Fix.** The validator is now the single governed gate, shared rather than
duplicated:

- `_validate_expected_version()` in `calculation_execution.py` was renamed to
  **`validate_expected_version()`** and added to that module's `__all__`. Its
  rules are unchanged — this is a visibility change, not a behaviour change.
- `cascade.py` imports it and calls it in **Phase A**, before
  `transaction.atomic()` opens, so a malformed value never reaches a
  `SELECT … FOR UPDATE`.
- The cascade's locked comparison now runs on the *validated integer* only, so
  `StaleResponseVersion` means one thing: a valid version that differs from the
  locked row.
- No second implementation exists. A committed test asserts the identity
  `cascade.validate_expected_version is calculation_execution.validate_expected_version`,
  and a second parses the AST of `recalculate_dependents()` to prove it contains
  no `isinstance` call of its own.

**Placement.** The validator stayed in `calculation_execution.py` rather than
moving to a new shared module. `cascade.py` already imported that module for
`execute_calculation_response()` and `StaleResponseVersion`, so reusing the gate
adds **no new dependency edge** and cannot introduce a cycle; a new module would
have been ceremony around an import that already existed. `InvalidExpectedVersion`
and `StaleResponseVersion` did not move, so no existing public or internal
contract changed, and nothing is exposed through the API. Import-linter remains
**7 kept, 0 broken**.

### Minor 1 and 2 — missing committed topology and stale-target tests

Both were real gaps: the ordering guarantees and the whole-cascade rollback were
asserted, but no committed test drove a named chain or diamond topology, and no
committed test forced a *downstream target* to present a stale version.

### Minor 3 — the per-commit buildability table omitted `5bf820b`

Corrected in place in §6N above, with a note recording that the omission was in
the evidence rather than in the verification.

### Tests added — all PostgreSQL-backed, none mocking the writer

`test_4d3_cascade.py` grew 65 → **140** tests (+75, sections N, O, P, Q) — the
same +75 the full backend suite records below.

| Section | Covers |
|---|---|
| N — structural gate | 12 invalid values (`None`, `True`, `False`, `1.0`, `"1"`, `0`, `-1`, `1.5`, `[]`, `{}`, `[1]`, `Decimal("1")`) × 4 assertions each: `InvalidExpectedVersion`; a whole-database fingerprint unchanged; zero calculation invocations; zero `FOR UPDATE`, `UPDATE` and `INSERT` queries. Plus: the shared-validator identity; the AST no-duplicate check; no audit |
| N — the measured regression | with the origin genuinely at version 1, `True` and `1.0` each raise `InvalidExpectedVersion` and mutate nothing, while integer `1` still cascades all six targets |
| N — genuine stale | a valid integer mismatch raises `StaleResponseVersion`; the origin *is* locked before the mismatch is reported; nothing is mutated; no target runs |
| O — stale downstream target | the third of six targets is handed a stale `expected_version` through a seam that changes only that argument — the real `execute_calculation_response()` runs, takes its own locks and raises. Asserts: three writer calls happened; every outcome is back at its pre-cascade `DATA_REQUIRED`/`None`/`generated_at=None` state; zero surviving snapshots; **zero captured `on_commit` callbacks**; zero audit |
| P — real chain | manual `Q_SUBJECT_COMPONENT` → `daily_exposure` → `percentage_of_iid_mde`, entirely on the approved registry with real ORM rows, the real resolver and the real writer. Asserts the graph really is a two-level chain; each link runs exactly once; B precedes C; C reads B's fresh outcome (1 g → 50 % of a 2 g precedent); C's provenance names B's current outcome UUID; and changing the component flows all the way down (0.5 g → 25 %) |
| Q — real diamond | A → B, A → C, (B, C) → D. Asserts the topology; B, C and D each execute exactly once; D executes last; D is **not** run twice for its two parents (M4D3-DAG-010 on the topology that would expose a missing visited set); D's value equals C − B from the outcomes written in that same cascade; D's provenance lists **both** parents' current outcome UUIDs |

**The regression tests fail against the reviewed implementation.** Verified by
stashing `cascade.py` and `calculation_execution.py` back to `88f6f24` and
re-running: `test_true_does_not_pass_as_version_one` and
`test_float_one_does_not_pass_as_version_one` both **FAILED**; both pass with the
fix.

**Test-construction notes**, since each could have produced a test that passes
for the wrong reason:

- The zero-mutation assertions compare a fingerprint covering all six outcomes
  (`status`, `value`, `reason_code`, `generated_at`, `updated_at`), every
  response `version` in the execution, the `AssessmentSnapshot` count and the
  `AuditEvent` count — not a single field that could stay equal by luck.
- `_cascade()` treats `expected_version=None` as "use the row's own version", so
  the invalid cases call `recalculate_dependents()` directly. Routing `None`
  through the helper would have silently tested the valid path.
- The stale-target seam mutates only the `expected_version` argument. The real
  writer is never replaced, so the `StaleResponseVersion` raised is the governed
  one, raised under the writer's own lock.
- The diamond's sink declares a literal `"gram"` target unit rather than a
  `SnapshotUnitRef`: with both its inputs sourced from calculation outcomes the
  entry needs no snapshot, so a reference unit would have had nothing to read
  and the test would have proved only `ASSESSMENT_SNAPSHOT_MISSING`.
- One recorder body in `test_a_genuine_stale_version_runs_no_target` is
  deliberately never executed — that is the assertion, restated as an empty
  call list, and it is the only uncovered pair in the module.

The approved six entries contain no diamond, so section Q installs a synthetic
registry with `monkeypatch`. Only the *shape* is synthetic: B and C are the
approved `daily_exposure` entry itself, D is the approved
`difference_from_iid_mde` entry with its two inputs re-pointed at B and C, and
the real resolver, the real engine functions and the real calculation writer all
run untouched. No committed registry definition is mutated.

### Post-remediation gates

Run **serially** — the suites share one PostgreSQL test database.

| Gate | Command | Result |
|---|---|---|
| Cascade | `pytest …test_4d3_cascade.py --no-cov -q` | **140 passed**, 0 failed, 112.2 s |
| Calculation execution + resolvers | `pytest …test_4d3_calculation_execution.py …test_4d3_calculation_inputs.py --no-cov -q` | **250 passed**, 131.6 s |
| Foundation, activation, readiness, execution API/model, lifecycle, authorization | `pytest …test_4d3_foundation.py …test_4d3_activation_validation.py …test_4d3_execution_readiness.py …test_execution_api.py …test_execution_models.py …test_execution_lifecycle.py …test_platform_authorization.py --no-cov -q` | **369 passed**, 89.2 s |
| Snapshot service (all of `iid_assessment`) | `pytest iid_assessment --no-cov -q` | **167 passed**, 40.9 s |
| Full backend suite | `pytest -q` | **1676 passed**, 0 failed, 0 skipped, 673.3 s, exit 0 |
| Coverage | same run | **94.30 %** against a 55 % floor |
| `cascade.py` coverage | targeted run | **100 %** (86 statements, 0 missed) |
| `calculation_execution.py` coverage | targeted run | **100 %** (231 statements, 0 missed) |
| `calculation_graph.py` coverage | targeted run | **100 %** (112 statements, 0 missed) |
| System check | `manage.py check` | no issues (0 silenced), exit 0 |
| Migration model-state | `makemigrations --check --dry-run` | **No changes detected**, exit 0 |
| Migration history | `migrate --check` | exit 0 |
| Ruff | `ruff check .` | All checks passed, exit 0 |
| Import-linter | `lint-imports` | **7 kept, 0 broken**, exit 0 |

The suite grew 1601 → **1676** (+75) and coverage rose 94.22 % → **94.30 %**. No
threshold lowered, no file excluded, no test weakened or skipped, and no
`pragma`, `noqa`, `skip` or `xfail` added.

### Behaviour explicitly re-confirmed, not merely assumed

The whole `test_4d3_cascade.py` module was re-run: Form B freshness, graph
discovery, transitive affected-node expansion, the M4D3-DAG-006 question-code
tie-break, cycle and self-cycle detection, the no-op cascade, snapshot-backed
recalculation, the fresh-snapshot policy, downstream freshness, `DATA_REQUIRED`,
`NOT_COMPARABLE` and `ERROR` propagation, tenant isolation, checklist-version
isolation, M4D3-RCL-004 suppression, repeated cascade behaviour, the immutable
cascade result, and the lock-order and concurrency probes all pass unchanged.

### Held out of scope, by instruction

**M4D3-RCL-004 was not redesigned.** Its literal behaviour is retained and no new
audit semantics were added. The review's observation that `generated_at` moves on
every successful result — and so prevents suppression for a `COMPLETE` outcome —
remains a disclosed, non-blocking observation (§6N).

**The repeating-decimal `DecimalField` observation is not solved here.** It stays
a deferred issue. No model precision and no rounding rule was changed; doing so
without an approved scientific specification would be inventing governed
numerics.

### Scope held

No client-facing recalculation trigger, no cascade API endpoint, no serializer or
view wiring, no frontend, no component rebinding, no applicability persistence, no
manual override, no async or Celery task, no report or export, and no new model or
migration. `recalculate_dependents()` remains a callable domain service that no
view, serializer, signal or task invokes.

`frontend/next.config.ts` carries an unrelated local modification. It was not
modified, staged, reverted or committed at any point in this run.

### Assertions for the §6O remediation run

| Assertion | Answer |
|---|---|
| Prior cascade Major resolved | **YES** |
| Second expected-version implementation introduced | **NO** — one shared validator, asserted by identity |
| Migrations created | **NO** |
| Models changed | **NO** |
| Approved specification amended | **NO** |
| Validator exposed through the API | **NO** — internal to `iig_checklist` |
| Import contracts broken | **NO** — 7 kept, 0 broken |
| Client-facing recalculation trigger added | **NO** |
| Serializers, views, API endpoints or frontend added | **NO** |
| Async / Celery orchestration added | **NO** |
| Coverage threshold lowered | **NO** — 94.22 % → 94.30 % |
| Existing tests weakened or skipped | **NO** |
| `pragma` / `noqa` / `skip` / `xfail` added | **NO** |
| `frontend/next.config.ts` modified, staged or committed | **NO** |
| PR created | **NO** |
| Merged | **NO** |

## 7. Assertions

These were written for the database-free foundation run and had not been
rescoped as later sections landed. They are now stated per scope, because
"migrations created: NO" was true of §1–§5 and false of the milestone once §6G
added `0003`.

**For the milestone to date (§1 through §6I):**

| Assertion | Answer |
|---|---|
| Migrations created | **YES — exactly one**, `0003_alter_calculationoutcome_input_provenance_and_more`, two `AlterField` flags (§6G) |
| Schema changed | **NO** — `0003` is a Django state change only; `sqlmigrate` emits two no-ops |
| Database access added | **YES** — activation validation (§6A), input resolution (§6D) and calculation execution (§6H) all read persisted rows; §1–§5 were database-free |
| Runtime calculation code added | **YES** — `execute_calculation_response()` (§6H) invokes the approved functions |
| `CalculationOutcome` results persisted | **YES** (§6H) |
| Governed `AssessmentSnapshot` creation | **NO** — open blocker, §6H and §6I |
| Cascade recalculation orchestration | **NO** — deferred, §6H and §6I |
| Serializers / API endpoint / frontend | **NO** |
| Coverage thresholds weakened | **NO** |
| Database mocked to claim integration coverage | **NO** |
| Existing tests weakened | **NO** |
| Production registry made mutable | **NO** |
| PR created | **NO** |
| Merged | **NO** |

**For the §6I remediation run specifically:**

| Assertion | Answer |
|---|---|
| Migrations created | **NO** |
| Models changed | **NO** |
| Approved specification amended | **NO** |
| Snapshot service added | **NO** |
| Cascade orchestration added | **NO** |
| Serializers or frontend added | **NO** |
| Coverage threshold lowered | **NO** |
| `pragma` / `noqa` / `skip` / `xfail` added | **NO** |
| PR created | **NO** |
| Merged | **NO** |

**Superseded rows.** Two rows of the milestone-to-date table above were written
when §6I was the head and are no longer true. They are left in place rather than
rewritten, so the record of what was true when is preserved:

| Row | Was | Now |
|---|---|---|
| Governed `AssessmentSnapshot` creation | **NO** — open blocker | **YES** — §6J, `iid_assessment.services.create_assessment_snapshot()` |
| Cascade recalculation orchestration | **NO** — deferred | **YES** — §6N, `iig_checklist.cascade.recalculate_dependents()` |

**For the §6N cascade run specifically:**

| Assertion | Answer |
|---|---|
| Migrations created | **NO** |
| Models changed | **NO** |
| Approved specification amended | **NO** |
| Rules engine, `eval` or dynamic expressions added | **NO** — dependencies come only from the immutable approved registry |
| Caller-supplied dependency lists accepted | **NO** |
| Second calculation writer introduced | **NO** — every target goes through `execute_calculation_response()` |
| Cascade-level audit event invented | **NO** — no approved clause or event constant defines one |
| Async / Celery orchestration added | **NO** |
| Component rebinding added | **NO** |
| Serializers, views, API endpoints or frontend added | **NO** |
| Trigger surface exposed to clients | **NO** — callable domain service only |
| Coverage threshold lowered | **NO** — 93.99 % → 94.22 % |
| Existing tests weakened or skipped | **NO** |
| `pragma` / `noqa` / `skip` / `xfail` added | **NO** |
| `frontend/next.config.ts` modified, staged or committed | **NO** — untouched throughout |
| PR created | **NO** |
| Merged | **NO** |
