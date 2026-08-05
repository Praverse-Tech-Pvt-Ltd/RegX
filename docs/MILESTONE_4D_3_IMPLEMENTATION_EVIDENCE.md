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

**Next layer:** ORM-backed `resolve_calculation_inputs()`. Until it exists, a
successfully activated checklist still has no runtime 4D-3 consumer — activation
proves the bindings are sound, but nothing yet resolves or executes them. That is
the expected state at the end of this run.

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
