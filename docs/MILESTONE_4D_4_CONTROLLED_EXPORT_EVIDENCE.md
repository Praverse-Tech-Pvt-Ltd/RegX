# Milestone 4D-4 — Controlled Export Foundation: Implementation Evidence

**Status of this document:** evidence for **one slice** of Milestone 4D-4.
**Milestone 4D-4 is NOT complete.** This slice delivers the governed controlled-export
foundation only. The remaining 4D-4 scope — overrides/deviations, reviewer conclusion
workflow, and production regulatory checklist content — is untouched, and the content
gate remains at **0 / 20 approved questions**.

Branch: `regx/feat/milestone-4d-4-controlled-export`
Base: `origin/regx-main` @ `63f4473d824c3cc8a76fa1fa12445c1fbd7c9707` (PR #14, `4D4-DEC-005` approved)

---

## 0. Review history

This slice went through independent review, **failed**, and was remediated. The findings
are recorded here rather than erased:

| Finding | Severity | Status |
|---|---|---|
| **MAJOR-1** — `generated_at` excluded from the hashed payload, contradicting `4D4-DEC-005` "Checksum coverage" and §17's tamper-evidence purpose | Major | **FIXED** — §3.1 |
| **MAJOR-2** — governed reviewer-amendment provenance (`ChecklistResponseHistory`) omitted entirely, contradicting `4D4-DEC-005` conditional reviewer provenance | Major | **FIXED** — §3.2 |
| **MINOR-1** — `reviewer_conclusion_note` emitted unconditionally as `null` | Minor | **FIXED** — now omitted when absent |
| **MINOR-2** — `DEC-006`'s UTC-timestamp canonical rule governed nothing hashed | Minor | **FIXED** — resolved by MAJOR-1 |
| **MINOR-3** — reconciliation tests bound only the private compatibility alias | Minor | **FIXED** — tests now exercise `common.csv_safety.csv_safe_cell` directly, plus an identity test proving the alias delegates rather than duplicates |

Critical findings: **0**. The permission boundary, tenant isolation, lifecycle gate,
allow-listed input provenance, ordinary-API separation and CSV safety all passed review
unchanged.

## 1. Scope delivered

| # | Item | Where |
|---|---|---|
| 1 | Shared CSV formula-injection helper promoted out of `templates_registry` | `backend/common/csv_safety.py` |
| 2 | Governed export service (projection, canonicalisation, checksum, renderings) | `backend/iig_checklist/controlled_export.py` |
| 3 | Dedicated export permission, granted to VP only | `backend/iig_checklist/permissions.py` |
| 4 | Export audit event | `backend/iig_checklist/audit.py` |
| 5 | Thin HTTP adapter + route | `backend/iig_checklist/views.py`, `urls.py` |
| 6 | Test matrix (64 tests) | `backend/iig_checklist/tests/test_4d4_controlled_export.py` |
| 7 | Conditional reviewer-amendment provenance projection | `controlled_export.py` — `ALLOWED_AMENDMENT_FIELDS`, `_amendment_projection()` |

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
  "checksum": {"algorithm": "sha256", "value": "<hex>"},   <-- envelope: cannot hash itself
  "payload": {                                             <-- everything below is hashed
    "export_schema_version": "1",
    "generated_at":          "<ISO-8601 UTC, Z-suffixed>",
    "execution":             {execution_public_id, status,
                              formulation_version_public_id,
                              reviewer_conclusion_note?},   <-- ? = conditional
    "checklist_definition":  {definition_public_id, definition_code,
                              version_public_id, version_number},
    "responses": [
      {question_public_id, question_code, answer_type,
       response_public_id, response_version, raw_value,
       is_not_applicable, not_applicable_reason,
       data_source_type_snapshot, system_derived_value,
       calculation: null | {outcome_public_id, status, value, unit,
                            reason_code, provenance},
       reviewer_amendments?: [                              <-- ? = conditional
         {amendment_public_id, prior_version, new_version,
          prior_raw_value, new_raw_value,
          prior_is_not_applicable, new_is_not_applicable,
          prior_not_applicable_reason, new_not_applicable_reason,
          correction_reason, amended_by_public_id, amended_at,
          prior_entered_by_public_id, prior_entered_at,
          source_classification_snapshot}
       ]}
    ]
  }
}
```

### 3.1 Checksum scope — corrected after independent review

**An earlier revision of this branch got this wrong, and the error is recorded here
rather than quietly rewritten.**

The **canonical object** was correct and is unchanged: §17 requires "a SHA-256 checksum
computed over the canonical serialized export **payload**" — singular and
format-independent — and `4D4-DEC-006` defines canonical form in *data* terms (key
ordering, decimal rendering, timestamp form, UTF-8), not CSV-row terms. So there is
**one** governed `payload`, hashed **once**; JSON and CSV are two renderings of it and
both carry the same checksum value.

**What was wrong:** `generated_at` was placed in an unhashed envelope, justified by the
claim that two exports of identical regulatory state ought to produce the same checksum.
Independent review found that property **appears nowhere in the specification** — it was
invented — and that excluding the timestamp actively defeats the purpose §17 states for
the checksum:

> This lets a later dispute verify a previously-issued export was not altered after the
> fact (`MILESTONE_4D_DISCOVERY.md:890`)

An issued artifact whose `generated_at` can be rewritten without breaking its checksum is
not tamper-evident in the field a back-dating dispute would turn on.

`4D4-DEC-005` settles it directly:

> **Checksum coverage.** All provenance included in the controlled export participates in
> the canonical serialized payload covered by the SHA-256 checksum
> (`MILESTONE_4D_4_DISCOVERY.md:301`)

and `generated_at` is listed as included artifact provenance in both the inclusion table
(L223) and the approved contract's `Artifact` group (L253).

Two further signals corroborated the correction: `DEC-006` fixes a canonical form for
"UTC ISO-8601 timestamps", yet under the old shape the hashed payload contained **no
timestamp at all**, leaving that rule governing nothing; and the exclusion made the
checksum silent on the one artifact field an adversary can most cheaply alter.

**Corrected contract, now implemented:**

- `generated_at` is **inside** the hashed payload, canonicalised to UTC `Z`.
- `export_schema_version` is inside, so a shape change is tamper-evident.
- **Only the checksum itself** is outside — a hash cannot cover itself.
- The envelope is now `{checksum, payload}`. `generated_at` is **not** duplicated into
  the envelope: a second copy could drift from the one the checksum attests to.
- Two export runs at different times **legitimately produce different checksums.**
  Reproducibility means *the same complete canonical payload yields the same hash*, not
  that two separate export runs agree.

Covered by `TestChecksum::test_generated_at_lives_in_the_hashed_payload_not_the_envelope`,
`test_a_different_generated_at_changes_the_checksum`,
`test_the_checksum_field_is_not_recursively_hashed`,
`test_generated_at_is_canonical_utc_z`.

### 3.2 Conditional reviewer-amendment provenance — added after independent review

The first revision omitted reviewer-amendment provenance entirely, carrying only
`reviewer_conclusion_note`. `4D4-DEC-005` requires reviewer provenance "included
conditionally, only where governed reviewer conclusion **or amendment records** exist",
and names what must be carried as "current state plus conditional reviewer-amendment
provenance".

`ChecklistResponseHistory` is the repository's only such record — append-only, one row
per reviewer-conclusion amendment, never written on first entry — so it is exactly the
governed record the decision describes. **No general response history is invented**, as
the decision forbids.

- **Allow-listed**, field-by-field, against the real model (`ALLOWED_AMENDMENT_FIELDS`),
  with a runtime guard that raises if the projection ever produces an unlisted key.
- **Public identity only.** Actors are `public_id`; email is deliberately excluded —
  audit events may carry it because the audit trail is access-controlled, but an export
  artifact is a document that leaves the system. DB primary keys, `response_id` and the
  `TimeStampedModel` columns are excluded.
- **Conditional.** The `reviewer_amendments` key is *omitted* where no amendment exists,
  not emitted as an empty list. `reviewer_conclusion_note` is likewise omitted rather
  than emitted as `null` (**MINOR-1**).
- **Sequence preserved.** Ordered by `new_version`, then `amended_at`, then `public_id`.
  Canonicalisation sorts object *keys* only and never reorders a list, so the governed
  chronology survives hashing.
- **Checksum-covered**, per the same `Checksum coverage` clause.

This was the first reader of `ChecklistResponseHistory` anywhere in the codebase — it has
no serializer and no API — so the projection was written against the model directly
rather than inherited from an existing read contract.

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

**Post-review remediation mutations** (re-run after MAJOR-1/MAJOR-2 were fixed):

| # | Mutation | Result | Failing tests |
|---|---|---|---|
| A | `generated_at` removed from the governed payload | **14 failed** overall; **3** in `TestChecksum` | `test_generated_at_lives_in_the_hashed_payload_not_the_envelope`, `test_a_different_generated_at_changes_the_checksum`, `test_generated_at_is_canonical_utc_z` |
| B | Reviewer-amendment projection removed | **6 failed** | `test_included_when_a_governed_amendment_exists`, `test_projection_is_allow_listed_and_carries_no_db_ids`, `test_amendment_order_is_governed_sequence_not_alphabetical`, `test_adding_an_amendment_changes_the_checksum`, +2 |
| C | Amendments present in the artifact but excluded from the hashed bytes | **5 failed** | `test_adding_an_amendment_changes_the_checksum`, `test_changing_an_exported_amendment_field_changes_the_checksum`, +3 governed-state checksum tests |
| D | Public `csv_safe_cell()` bypassed | **15 failed** | reconciliation + controlled-export CSV safety |

Mutation C is the one that matters for MAJOR-2: B proves the data is *projected*, C proves
it is *hashed*. Without C, an implementation could export amendments while leaving them
outside the tamper-evidence boundary.

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
| `templates_registry` suite | 100 passed (CSV helper repointing + MINOR-3 delegation test) |
| New controlled-export suite | 64 passed |

Full-backend result and coverage are recorded in §7.

---

## 7. Full backend suite

| | Baseline (`regx-main` @ `63f4473`) | Pre-review | **Post-remediation** | Delta vs base |
|---|---|---|---|---|
| Passed | 1814 | 1863 | **1879** | **+65** |
| Failed | 0 | 0 | **0** | 0 |
| Skipped / xfailed | 0 | 0 | **0** | 0 |
| Coverage | 94.56% | 94.66% | **94.68%** | **+0.12 pp** |

`1879 passed, 4 warnings in 624.69s` — `Required test coverage of 55% reached. Total
coverage: 94.68%`.

The +65 is 64 controlled-export tests plus the reconciliation alias-delegation test
(MINOR-3). No pre-existing test was skipped, xfailed, removed, or weakened. In
particular the APP-009 tests, the response payload-contract tests, and the
frozen-dataclass immutability tests are byte-identical to `regx-main`.

**Three pre-existing tests in this branch's own suite were rewritten, not weakened.**
`test_generated_at_is_outside_the_hashed_bytes` asserted the contract MAJOR-1 found to be
wrong; it is replaced by four tests asserting the corrected contract. The other two
(`test_same_state_yields_the_same_checksum`,
`test_an_excluded_internal_field_does_not_move_the_checksum`) now pin `generated_at`
through a narrowly frozen clock constant so they compare like with like — the service's
own UTC normalisation is untouched and still exercised by
`test_generated_at_is_canonical_utc_z`. Coverage moved **up**, not down.

---

## 8. What still blocks Milestone 4D-4 closure

1. Overrides / deviations — not started.
2. Reviewer conclusion workflow — not started.
3. **Production regulatory checklist content — 0 / 20 approved questions.** This
   requires human regulatory authorship and approval; it is not an engineering task and
   was deliberately not attempted.
4. `4D4-DEC-004`, `4D4-DEC-008`, `4D4-DEC-010` remain open.
