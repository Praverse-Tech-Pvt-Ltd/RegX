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
duplicate codes across sections; wrong answer type; wrong classification;
non-calculated form E target; unknown identifier; the full
`daily_exposure → percentage_of_iid_mde` chain; cross-version and cross-tenant
isolation; permission denial; deterministic ordering; zero mutation on failure;
no success audit on failure; no supersede on failure; and sanitized structured
errors carrying public UUIDs only.

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

## 7. Assertions

- Migrations created: **NO**
- Schema changed: **NO**
- Database access added: **NO**
- Coverage thresholds weakened: **NO**
- Database mocked to claim integration coverage: **NO**
- Existing tests weakened: **NO**
- PR created: **NO**
- Merged: **NO**
