# Milestone 4D-4 — Controlled Export Foundation: Implementation Evidence

**Status of this document:** evidence for **one slice** of Milestone 4D-4.
**Milestone 4D-4 is NOT complete.** This slice delivers the governed controlled-export
foundation only. The remaining 4D-4 scope — overrides/deviations, reviewer conclusion
workflow, and production regulatory checklist content — is untouched, and the content
gate remains at **0 / 20 approved questions**.

Branch: `regx/feat/milestone-4d-4-controlled-export`
Base: `origin/regx-main` @ `63f4473d824c3cc8a76fa1fa12445c1fbd7c9707` (PR #14, `4D4-DEC-005` approved)

---

## 1. Scope delivered

| # | Item | Where |
|---|---|---|
| 1 | Shared CSV formula-injection helper promoted out of `templates_registry` | `backend/common/csv_safety.py` |
| 2 | Governed export service (projection, canonicalisation, checksum, renderings) | `backend/iig_checklist/controlled_export.py` |
| 3 | Dedicated export permission, granted to VP only | `backend/iig_checklist/permissions.py` |
| 4 | Export audit event | `backend/iig_checklist/audit.py` |
| 5 | Thin HTTP adapter + route | `backend/iig_checklist/views.py`, `urls.py` |
| 6 | Test matrix (49 tests) | `backend/iig_checklist/tests/test_4d4_controlled_export.py` |

### Explicitly NOT delivered in this slice

- No override / deviation model, API, or workflow.
- No reviewer-conclusion workflow changes.
- **No production regulatory checklist content.** No regulatory question was authored,
  invented, or seeded. All test fixtures are synthetic.
- No new model, no new field, no migration (`makemigrations --check --dry-run` → *No changes detected*).
- No widening of any ordinary API serializer.
- Open decisions `4D4-DEC-004`, `-008`, `-010` remain **open** and were not resolved.

---

## 2. Specification mapping

| Requirement | Source | Implementation |
|---|---|---|
| Export is permission-gated, *not implicit from view* | `MILESTONE_4D_DISCOVERY.md` §17 | `PERM_EXPORT_CHECKLIST`, granted to VP only. Doer and Reviewer both hold `PERM_VIEW_EXECUTION` and are both refused. |
| Only a completed execution may be exported | §17 | `EXPORTABLE_EXECUTION_STATUSES = {"approved"}`; every other status raises `ExecutionNotExportable`. |
| Deterministic, versioned payload | §17, `4D4-DEC-006` | `EXPORT_SCHEMA_VERSION = "1"`, carried **inside** the hashed payload. |
| SHA-256 over the canonical serialized export payload | §17 | `checksum_for()` over `canonical_bytes()`. |
| Export-safe provenance, allow-listed | `4D4-DEC-005`, §I.1 | `ALLOWED_INPUT_DESCRIPTOR_FIELDS` + `_PROVENANCE_SCALAR_KEYS` / `_PROVENANCE_LIST_KEYS`; positive-listed, so an unreviewed key added to the stored column cannot reach an artifact. |
| Reproducible from pinned state | §18 | Reads only the execution's own responses and the pinned `checklist_version`. No live FDA / formulation source is re-queried. |
| CSV must not be a formula-injection vector | CWE-1236, §17 | Every cell routed through the shared `csv_safe_cell()`. |
| Single shared CSV helper, not a duplicate | §17 (former Open Question 3) | Helper promoted to `common/csv_safety.py`; `templates_registry.reconciliation` now imports it. Exactly one implementation platform-wide. |

---

## 3. Artifact shape

```
{
  "generated_at":  "<ISO-8601 UTC, Z-suffixed>",
  "checksum":      {"algorithm": "sha256", "value": "<hex>"},
  "payload": {
    "export_schema_version": "1",
    "execution":             {execution_public_id, status,
                              formulation_version_public_id,
                              reviewer_conclusion_note},
    "checklist_definition":  {definition_public_id, definition_code,
                              version_public_id, version_number},
    "responses": [
      {question_public_id, question_code, answer_type,
       response_public_id, response_version, raw_value,
       is_not_applicable, not_applicable_reason,
       data_source_type_snapshot, system_derived_value,
       calculation: null | {outcome_public_id, status, value, unit,
                            reason_code, provenance}}
    ]
  }
}
```

### 3.1 Checksum scope — a deliberate decision, recorded

§17 requires "a SHA-256 checksum computed over the canonical serialized export
payload" — **singular** and format-independent — and `4D4-DEC-006` defines canonical
form in *data* terms (key ordering, decimal rendering, timestamp form, UTF-8), not in
CSV-row terms. Accordingly:

- There is **one** governed `payload`, hashed **once**. JSON and CSV are two
  renderings of that same payload and both carry the same checksum value.
- `generated_at` and the checksum itself sit in the **envelope, outside the hashed
  bytes**. Hashing the issue timestamp would make two exports of *identical regulatory
  state* disagree, destroying the property that makes the checksum useful: that a
  verifier can re-derive it from the state it attests to.
- `export_schema_version` **is** inside the payload, so a change to the artifact shape
  is itself tamper-evident.

This resolves the checksum-scope ambiguity noted during implementation; it is recorded
here rather than left implicit, and is covered by tests
(`TestChecksum::test_json_and_csv_carry_the_same_checksum`,
`test_regenerating_at_a_different_time_does_not_move_the_checksum`).

### 3.2 Canonicalisation (`4D4-DEC-006`)

- Dict keys sorted **twice** — recursively in `_canonicalise()` *and* via
  `json.dumps(sort_keys=True)` — so a sub-tree serialised independently is stable too.
  These two layers are redundant by design (see §5, mutation 3).
- `Decimal` rendered through the project's `format_decimal_plain()`, never `float()` or
  `str()`: a regulated figure must not round-trip through binary floating point, and
  `str(Decimal("1E-7"))` would emit exponent notation.
- `float` is **rejected**, not coerced. No governed value is a float; reaching that
  branch means an unreviewed field entered the payload, and silently accepting it would
  make the checksum depend on binary rounding.
- Timestamps normalised to UTC with a `Z` suffix; naive values treated as UTC rather
  than guessed at, so rendering never depends on server locale.
- `ensure_ascii=False` + explicit UTF-8 encode; compact separators, so formatting can
  never alter the hash.

---

## 4. Authorization, tenancy, and ordering

`export_execution()` evaluates, in this order:

1. **Tenant-scoped lookup** via `visible_to(tenant)` — a cross-tenant `public_id` is a
   **404**, never a 403 that would confirm the record exists.
2. **Dedicated export permission** — `PERM_EXPORT_CHECKLIST`.
3. **Lifecycle** — status must be `approved`.

The audit event (`iig_checklist.execution.exported`) is emitted via
`transaction.on_commit`, only after the artifact exists, and carries the checksum,
algorithm, schema version, format, and execution status, so the trail can later attest
to a specific issued artifact.

**HTTP note:** the format selector is the query parameter **`export_format`**, not
`format`. `format` is DRF's reserved `URL_FORMAT_OVERRIDE` and using it produced a 404
during implementation.

---

## 5. Mutation proofs

Each mutation was applied, the failure observed, and the mutation **completely
reverted**. No mutation code is committed; a residual scan for the marker string across
all touched files returned **NONE**.

| # | Mutation | Result | Failing tests |
|---|---|---|---|
| 1 | Provenance allow-list disabled (`return dict(stored)`) | **5 failed** | `test_an_unexpected_internal_provenance_key_is_dropped`, `test_an_excluded_internal_field_does_not_move_the_checksum`, +3 |
| 2 | `csv_safe_cell()` neutralisation removed (returns `text` unescaped) | **15 failed** | `test_render_reconciliation_csv_neutralizes_every_column`, `test_malicious_identifier_is_neutralized_in_csv_but_not_in_database`, `test_csv_safe_cell_neutralizes_only_formula_triggers[…]`, +11 |
| 3a | `json.dumps(sort_keys=False)` only | **0 failed** — *see note* | — |
| 3b | Both ordering layers removed (recursive sort **and** `sort_keys`) | **2 failed** | `test_key_order_does_not_affect_canonical_bytes`, `test_nested_key_order_does_not_affect_canonical_bytes` |
| 4 | Permission check removed from `export_execution()` | **3 failed** | `test_doer_cannot_export_despite_holding_view`, `test_reviewer_cannot_export`, `test_direct_service_call_enforces_permission` |

**Note on 3a — reported rather than hidden.** Disabling `sort_keys` alone did *not*
fail any test, because `_canonicalise()` already sorts recursively. That is not a test
gap: the two layers are deliberate defense-in-depth, and either alone is sufficient for
determinism. Mutation 3b removes both and the checksum-stability tests fail as required.
Mutation 2's blast radius reaches `templates_registry` because the helper is now genuinely
shared — which is the point of the promotion.

---

## 6. Gates

| Gate | Result |
|---|---|
| `python manage.py check` | System check identified no issues (0 silenced) |
| `makemigrations --check --dry-run` | No changes detected |
| `migrate --check` | clean |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 274 files already formatted |
| `lint-imports` | exit 0 — `common` still has no domain imports |
| `templates_registry` suite | 99 passed (CSV helper repointing) |
| New controlled-export suite | 49 passed |

Full-backend result and coverage are recorded in §7.

---

## 7. Full backend suite

| | Baseline (`regx-main` @ `63f4473`) | This branch | Delta |
|---|---|---|---|
| Passed | 1814 | **1863** | **+49** |
| Failed | 0 | **0** | 0 |
| Skipped / xfailed | 0 | **0** | 0 |
| Coverage | 94.56% | **94.66%** | **+0.10 pp** |

`1863 passed, 4 warnings in 745.46s` — `Required test coverage of 55% reached. Total
coverage: 94.66%`.

The delta is exactly the 49 new controlled-export tests: no pre-existing test was
skipped, xfailed, removed, or weakened. In particular the APP-009 tests, the response
payload-contract tests, and the frozen-dataclass immutability tests are byte-identical
to `regx-main`. Coverage moved **up**, not down.

---

## 8. What still blocks Milestone 4D-4 closure

1. Overrides / deviations — not started.
2. Reviewer conclusion workflow — not started.
3. **Production regulatory checklist content — 0 / 20 approved questions.** This
   requires human regulatory authorship and approval; it is not an engineering task and
   was deliberately not attempted.
4. `4D4-DEC-004`, `4D4-DEC-008`, `4D4-DEC-010` remain open.
