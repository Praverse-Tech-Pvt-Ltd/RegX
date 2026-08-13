# Milestone 4D-4 — Governed Response Overrides: Implementation Evidence

**Status of this document:** evidence for **one slice** of Milestone 4D-4.
**Milestone 4D-4 is NOT complete.** This slice delivers governed overrides only.
`4D4-DEC-008` (`approval_metadata`) remains **PENDING APPROVAL**, and production
regulatory content remains at **0 of 20** approved.

Branch: `regx/feat/milestone-4d-4-overrides`
Base: `3b7a0e9` — the approved override-governance commit (§AC of
`MILESTONE_4D_4_DISCOVERY.md`)

> **Base note.** This branch was cut from the docs commit `3b7a0e9` rather than
> `regx-main`, because at implementation time the override-governance PR had not
> yet merged and `regx-main` still recorded `4D4-DEC-004` / `4D4-DEC-010` as
> `OPEN` with `4D4-DEC-011` unregistered. Implementing against a register that
> marks the governing decisions unresolved would violate the rule at
> `MILESTONE_4D_4_DISCOVERY.md` L534. Every commit here is therefore consistent
> with its governing register. The branch merges into `regx-main` cleanly whether
> or not the docs PR lands first — the content is identical either way.

---

## 1. Decisions implemented

| Decision | Implementation |
|---|---|
| `4D4-DEC-004` | `HISTORY_REASON_ANSWER_OVERRIDDEN = "ANSWER_OVERRIDDEN"` added to `ALLOWED_HISTORY_REASON_CODES` |
| `4D4-DEC-010` | Classification matrix enforced in the governed service |
| `4D4-DEC-011` | `PERM_OVERRIDE_EXECUTION` / `iig_checklist.override_execution` |
| `4D4-DEC-002` | Shared `validate_expected_version()`, unchanged |
| `4D4-DEC-003` | `EDITABLE_EXECUTION_STATUSES` (`draft`, `returned`), unchanged |
| `4D4-DEC-007` | Dedicated action endpoint, not the ordinary PATCH |
| §AC.4 | Clearing **not** implemented, and actively refused |
| §AC.5 | No new field; no migration |

### Not implemented, deliberately

- **Override clearing** — §AC.4 defers it; no clear path, no clear code, no route.
- **`approval_metadata`** (`4D4-DEC-008`) — untouched.
- **Production regulatory content** — none authored; all fixtures synthetic.
- **Override UI** — blocked on a missing permission surface (§9).

---

## 2. Permission — `4D4-DEC-011`

`PERM_OVERRIDE_EXECUTION = "iig_checklist.override_execution"`

| Role | Override | Holds edit? | Holds view? |
|---|---|---|---|
| Doer | **NO** | yes | yes |
| Reviewer | **YES** | no | yes |
| VP | **YES** | no | yes |
| Tenant Admin | NO | no | yes |
| Platform Support | NO | no | no |

Doer holds `PERM_EDIT_EXECUTION` **and** `PERM_VIEW_EXECUTION` and is still
refused — that is `4D4-DEC-011`'s "ordinary edit/view/review authority must never
implicitly confer override authority", asserted directly rather than assumed. The
permission is a distinct codename, not an alias of `PERM_REVIEW_EXECUTION`.

Enforced in `override_checklist_response()`, so a direct domain call is bound
exactly as an HTTP request is.

## 3. Classification matrix — `4D4-DEC-010`

| Classification | Disposition | Enforced |
|---|---|---|
| `FDA_DERIVED_DEFAULT` | **OVERRIDABLE** | ✓ |
| `USER_REQUIRED` | not an override case | refused |
| `SYSTEM_CALCULATED` | **NOT OVERRIDABLE** | refused |
| `EVIDENCE_DERIVED` | **NOT OVERRIDABLE** | refused |
| `REVIEWER_CONFIRMED` | **NOT OVERRIDABLE** | refused |

The check reads `response.data_source_type_snapshot`, **not** the live question,
so re-classifying a question later cannot retroactively make an already-answered
response overridable. Covered by
`test_classification_read_from_snapshot_not_live_question`.

The service boundary is authoritative; frontend controls are not protection.

## 4. Lifecycle and concurrency

Lifecycle reuses `EDITABLE_EXECUTION_STATUSES` with the established
pre-lock/post-lock pattern: checked in Phase A, then **re-read under
`select_for_update()`** so the status that governs the write is committed state
rather than what the Phase A scan saw. `submitted_for_review`, `under_review` and
`approved` are all refused.

`expected_version` reuses the shared `validate_expected_version()`. The serializer
is a **passthrough** (`JSONField`), so `1.0`, `"1"`, `"1.0"`, `0`, `-1` and `null`
reach the governed validator intact instead of being coerced to `1` by the
transport layer — one structural rule, in the domain.

## 5. Storage semantics — §AC.5

No new field. No migration (`makemigrations --check --dry-run` → *No changes detected*).

| | First override | Update of an active override |
|---|---|---|
| `system_derived_value` | set to the displaced original | **untouched** |
| `raw_value` | the override value | replaced |
| `override_reason` | mandatory, non-empty | replaced |
| `version` | +1 | +1 |

### The active-override marker is `override_reason`, not `system_derived_value`

This is load-bearing and worth stating explicitly. An `FDA_DERIVED_DEFAULT`
response whose default was never populated has `raw_value = None`, so the first
override legitimately preserves `None`. Keying "is an override already active?"
off `system_derived_value` would then read the **second** override as a first one
and overwrite the preserved original with the *previous override* — precisely the
corruption §AC.5 forbids. `override_reason` is only ever written by this service,
so its emptiness is an honest marker.

Covered by `test_a_null_original_default_does_not_confuse_apply_with_update`, and
mutation-proved (C).

## 6. Clearing refused — §AC.4

Every clearing vector is closed, each with a governed answer:

| Vector | Result |
|---|---|
| `raw_value: null` | 400 `override_clear_not_supported` |
| empty `override_reason` | 400 `override_reason_required` |
| whitespace-only reason | 400 `override_reason_required` |
| missing reason | 400 `override_reason_required` |
| `system_derived_value` in payload | 400 `unknown_field` |
| ordinary PATCH | 400 `unknown_field` |
| a clear route | does not exist |
| `ANSWER_OVERRIDE_CLEARED` | not in the vocabulary |

`trim_whitespace=False` on the reason field is deliberate: DRF trims by default,
which would turn `"   "` into `""` and answer a governed requirement with a
transport-layer message. Leaving the value intact keeps every form of "no reason"
on the same governed path.

## 7. History — `4D4-DEC-004`

One code, `ANSWER_OVERRIDDEN`, for both apply and update. No speculative
apply/update split, no clear code. `ALLOWED_HISTORY_REASON_CODES` is now exactly
`{APPLICABILITY_REEVALUATED, COMPONENT_REBOUND, ANSWER_OVERRIDDEN}`.

Apply and update are reconstructable from one code because the history row
carries the transition: the apply row's `prior_raw_value` is the original
default, the update row's is the previous override, and `new_version` chains to
the next row's `prior_version` without gaps. Covered by
`test_apply_and_update_are_reconstructable_from_one_code`.

**Test-count guard updated, not relaxed.** `test_exact_counts` asserts vocabulary
sizes "here and nowhere else in the codebase" — it exists so a vocabulary change
cannot land silently. `4D4-DEC-004` approved exactly one addition, so the
assertion moved 2 → 3. That is the gate working as designed.

## 8. Audit

`iig_checklist.answer.overridden` — the exact name §12 L725 specifies, distinct
from `response.entered`/`response.updated` so an override is never mistaken for
an ordinary edit.

Payload carries execution / response / question public IDs, question code,
classification snapshot, prior and new version, **actor public ID**, override
reason, prior override reason, prior value, new value, the preserved
`system_derived_value`, whether this call created the override, and the cascade
count. **No database primary keys.**

Emitted through `transaction.on_commit()` after a successful transaction only. A
denied or refused attempt writes nothing, increments no version, creates no
history row and emits no success audit — asserted for both the permission
refusal and the classification refusal.

## 9. Frontend — contract aligned, UI blocked

**Done:** `override_reason` removed from the ordinary `update()` payload type,
and a governed `override()` client added for the dedicated action.

That removal was **required, not cosmetic**: the field was previously accepted by
the update serializer and silently discarded — the ordinary path never wrote it.
This slice makes it an `unknown_field` error, so leaving it in the client type
would have shipped a call that now fails outright.

**Blocked:** the override UI. `4D4-DEC-011` requires the action to be shown only
to a caller holding `iig_checklist.override_execution`, and **the frontend has no
permission surface at all** — no role, capability or effective-permission concept
exists in `src/`. The backend's `authorization/permissions/` endpoint reads the
database `Permission` table, whereas `iig_checklist.ROLE_PERMISSIONS` is a
hardcoded Python dict, so `PERM_OVERRIDE_EXECUTION` would not appear there.

Bridging that dict into a read API is a new governed surface, not the "minimum
safe read metadata" the task authorises. The read model already exposes
everything else the UI would need (`data_source_type_snapshot`,
`override_reason`, `system_derived_value`, `version`), so this is the single
missing piece. **Recommended as its own decision** — proposed `4D4-DEC-012`:
shape of a caller-capability read surface for `iig_checklist` permissions.

Gating the UI on classification and lifecycle alone was rejected: it would show
a Doer an action that always 403s, and `4D4-DEC-011` names permission as a
visibility condition.

## 10. Controlled-export integration

Conditional `override` group, present only when an override is recorded, plus a
separate `override_history` list.

Exported: `override_reason`, `original_system_derived_value`, `overridden_value`,
`overridden_by_public_id`, `overridden_at`, `response_version`,
`data_source_type_snapshot` — allow-listed via `ALLOWED_OVERRIDE_FIELDS` with a
runtime guard that raises on any unlisted key. **No email, no database IDs, no
raw model serialization.**

**`ANSWER_OVERRIDDEN` history is projected separately from
`reviewer_amendments`.** Both live in `ChecklistResponseHistory`, but a row
written by the override service is not a reviewer-conclusion amendment, and
filing it under that key would misdescribe the regulatory record. The governed
code partitions them.

Override provenance participates in the existing canonical payload and therefore
the existing SHA-256. **Checksum semantics are unchanged** — no redesign, and
`generated_at` semantics are untouched. An artifact with no override keeps its
previous shape exactly (`{checksum, payload}`, schema version `1`).

## 11. `ControlledExportError` minor — DEFERRED

The previously documented `ControlledExportError` → unstructured 500 is **not**
fixed here. The obvious narrow mapping is not obvious after all: the exception
covers three unrelated conditions (float rejection, unsupported type,
allow-list breach) whose correct HTTP answers plausibly differ, and choosing one
blanket status would be a governance call rather than a mechanical fix. Per the
task's own instruction not to spend substantial time on it, it stays documented
and deferred. It remains fail-closed: no artifact is issued and no success audit
is emitted.

## 12. Tests

**69 new tests** in `test_4d4_overrides.py`, covering permission (incl. VP,
Reviewer, Doer, edit-alone, cross-tenant 404), the full classification matrix,
lifecycle across five states, storage semantics incl. the null-original edge,
every clearing vector, concurrency incl. six malformed `expected_version` forms,
history reconstruction, audit success and both non-emission paths, ordinary-API
separation, and export provenance.

| Suite | Result |
|---|---|
| Override suite | **69 passed** |
| `iig_checklist` (whole app) | **1319 passed** |
| **Full backend** | **1948 passed, 0 failed, 94.75% coverage** |
| Frontend type-check | clean |
| Frontend lint | clean |
| Frontend unit | **182 passed** |

| | Baseline (`52a6e46`) | This branch | Delta |
|---|---|---|---|
| Passed | 1879 | **1948** | **+69** |
| Failed | 0 | **0** | 0 |
| Skipped / xfailed | 0 | **0** | 0 |
| Coverage | 94.68% | **94.75%** | **+0.07 pp** |

The delta is exactly the 69 new override tests. No pre-existing test was skipped,
xfailed, removed or weakened; the single edit to an existing test was the
`test_exact_counts` vocabulary count (§7), which moved 2 → 3 because
`4D4-DEC-004` approved one addition. Coverage moved **up**.

Static gates: `manage.py check` clean · `makemigrations --check --dry-run` → no
changes · `migrate --check` exit 0 · `ruff check .` all passed ·
`ruff format --check .` 276 formatted · `lint-imports` exit 0.

## 13. Mutation proofs

Each applied, observed, and **fully reverted**; residual marker scan returns NONE.

| # | Mutation | Result |
|---|---|---|
| A | Classification guard disabled | **7 failed** — every non-overridable classification, the service-boundary test, the HTTP code test and the snapshot test |
| B | Override permission check disabled | **2 failed** — `test_doer_may_not_override`, `test_direct_service_call_enforces_permission` |
| C | Update overwrites the preserved original with the previous override | **2 failed** — `test_second_override_keeps_the_original_not_the_previous_override`, `test_a_null_original_default_does_not_confuse_apply_with_update` |
| D | Override provenance removed from the checksum-covered payload | **5 failed** — presence, distinguishability, actor identity, allow-list, CSV |

## 14. What still blocks Milestone 4D-4

1. **`4D4-DEC-008`** (`approval_metadata`) — PENDING APPROVAL.
2. **Production regulatory content — 0 of 20.** Requires human regulatory
   authorship; not an engineering task and not attempted.
3. **Override UI** — blocked on the missing permission surface (§9); proposed
   `4D4-DEC-012`.
4. **Override clearing** — deferred by §AC.4 pending its own decision.
5. `ControlledExportError` structured-failure mapping — deferred (§11).
