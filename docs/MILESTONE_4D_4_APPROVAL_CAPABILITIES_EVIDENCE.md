# Milestone 4D-4 — Approval Metadata and Override Capabilities: Implementation Evidence

**Status of this document:** evidence for **one slice** of Milestone 4D-4.
**Milestone 4D-4 is NOT complete.** Production regulatory content remains at
**0 of 20** approved.

Branch: `regx/feat/milestone-4d-4-approval-capabilities`
Base: `regx-main` @ `4265ce88760e30e63dfa1a767ec91e8dc28d5b51` (PR #16 merged)

Implements `4D4-DEC-008` and `4D4-DEC-012`, both approved 2026-08-12 (§AD of
`MILESTONE_4D_4_DISCOVERY.md`), and completes the override UI that `4D4-DEC-012`
was blocking.

---

## 1. `4D4-DEC-008` — governed `approval_metadata`

### Exact schema

```json
{
  "approval_decision": "approved",
  "approved_by_public_id": "<uuid>",
  "approved_at": "<ISO-8601 UTC, Z-suffixed>",
  "execution_public_id": "<uuid>",
  "checklist_version_public_id": "<uuid>",
  "checklist_version_number": 7,
  "reviewer_conclusion_response_public_id": "<uuid>"
}
```

`reviewer_conclusion_response_public_id` is **conditional** — present only where a
governed reviewer-conclusion response actually carries a value. An unanswered
conclusion question is not a linkage, so the key is omitted rather than nulled.

Enforced by `ALLOWED_APPROVAL_METADATA_FIELDS` with a runtime guard that raises
rather than shipping an unlisted key. **No actor email or display name, no
database primary keys, no free-form extension, no approval comment.**

### It is a projection, not a second approval system

Execution-level approval provenance already existed — `ChecklistExecution`
`approved_by` / `approved_at`, written at the approve transition. This slice
projects that state into the answer; it does not duplicate or replace it.
**No new field, and `makemigrations --check --dry-run` reports no changes.**

### Atomicity and immutability

Generation happens inside the approve transition's own `transaction.atomic()`
block, so metadata and approved status commit together or not at all. Proved two
ways: `test_failed_approval_leaves_no_metadata` drives a rejected approval and
asserts neither status nor metadata moved, and
`test_generation_is_inside_the_approval_transaction` inspects the service source
to confirm the call site sits inside the atomic body rather than after it.

Immutability follows from the **lifecycle**, not a second guard: approval leaves
`EDITABLE_EXECUTION_STATUSES`, so no governed path can rewrite the response
afterwards. `approval_metadata` is also in `_CLIENT_REJECTED_TYPES`, so a client
may never supply it in the first place.

### One necessary change to the completeness gate

`_check_execution_completeness` now exempts `APPROVAL_METADATA`. This is not
scope creep — without it, a **required** approval_metadata question would be
unsatisfiable by construction: it is generated *by* the transition the gate
guards, and its `REVIEWER_CONFIRMED` floor would additionally demand a
confirmation no client may supply. The exemption mirrors the existing
`REVIEWER_CONCLUSION` one.

### The question is not mandatory

An execution whose checklist defines no `approval_metadata` question approves
exactly as before — `populate_approval_metadata()` returning zero is a normal
result, asserted by
`test_execution_without_an_approval_question_still_approves`.

## 2. `4D4-DEC-012` — capability surface

```
GET /api/regx/v1/iig-checklists/capabilities/
→ { "can_override_response": true | false }
```

| Role | Result |
|---|---|
| Reviewer | **true** |
| VP | **true** |
| Doer | **false** |
| Tenant Admin | **false** (governed `ROLE_PERMISSIONS` does not grant it) |

- **Tenant-scoped** via the existing `_require_tenant()` convention; missing
  tenant and unauthenticated both fail closed.
- Derived from **`has_iig_checklist_permission()`** — the same predicate the
  override service enforces with, so the two cannot disagree.
- **Named flags only.** `test_response_exposes_named_capabilities_only` asserts
  the payload contains no permission codename, no `role`, no `permission` token
  and no database identifier.
- **Advisory only.** The governed service remains authoritative.

### `effective_permissions_view` is neither reused nor modified

Two independent disqualifiers, both verified in the repository: it reads the
database `Permission` table while `iig_checklist` authority lives in the governed
`ROLE_PERMISSIONS` mapping — so the override permission would never appear — and
it aggregates across **all** of a user's tenant memberships with no tenant
scoping, which would blur authority between tenants. The second is the more
serious: reusing it would have been a genuine isolation defect, not merely a
missing field.

## 3. Controlled export

`approval_metadata` flows through the **existing** governed `raw_value`
projection, which is already inside the canonical hashed payload. **No duplicate
approval-provenance group was added**, and checksum semantics are untouched —
`generated_at` handling and the one-payload/one-SHA-256 contract are unchanged.

Verified by `test_metadata_flows_through_the_existing_raw_value_projection`,
`test_metadata_is_checksum_covered` and
`test_changing_governed_metadata_changes_the_checksum`.

## 4. Override UI — previously blocked, now complete

Gated on **all four** conditions, matching the server rules rather than replacing
them:

1. `can_override_response === true` (`4D4-DEC-012`)
2. `dataSourceTypeSnapshot === "fda_derived_default"` (`4D4-DEC-010`)
3. execution status is `draft` or `returned` (`4D4-DEC-003`)
4. existing response eligibility

Never offered for `USER_REQUIRED`, `SYSTEM_CALCULATED`, `EVIDENCE_DERIVED` or
`REVIEWER_CONFIRMED`. The form requires a value and a **mandatory reason**; the
submit button stays disabled until a non-blank reason is entered. **There is no
clear-override control** (§AC.4). On success the client performs an authoritative
refetch — the backend may have cascaded dependent calculations, and none of that
is reconstructed client-side. Governed 403 and 409 are handled distinctly.

**Fail-closed by construction:** `canOverride` initialises to `false` and a failed
capability request leaves it `false`, so an unreachable endpoint hides the action
rather than revealing it.

## 5. Tests

| Suite | Result |
|---|---|
| Approval + capabilities (new) | **28 passed** |
| Override UI (new, frontend) | **16 passed** |
| Focused backend (approval + overrides + export) | **161 passed** |
| **Full backend** | **1976 passed, 0 failed, 94.82% coverage** |
| Frontend unit (total) | **198 passed** (was 182) |
| Frontend type-check · lint | clean · clean |

| | Baseline (`4265ce8`) | This branch | Delta |
|---|---|---|---|
| Passed | 1948 | **1976** | **+28** |
| Failed | 0 | **0** | 0 |
| Skipped / xfailed | 0 | **0** | 0 |
| Coverage | 94.75% | **94.82%** | **+0.07 pp** |

The delta is exactly the 28 new approval/capability tests. No pre-existing test
was skipped, xfailed, removed or weakened, and **no existing test was edited at
all** in this slice. Coverage moved **up**.

Static gates: `manage.py check` clean · `makemigrations --check --dry-run` →
**no changes** · `migrate --check` exit 0 · `ruff check .` all passed ·
`ruff format --check .` 278 formatted · `lint-imports` exit 0.

## 6. Mutation proofs

All five applied, observed, and **fully reverted**; residual marker scan NONE.

| # | Mutation | Result |
|---|---|---|
| A | `approval_metadata` made client-writable | **1 failed** — `test_client_rejected_type_registry_includes_it` |
| B | Generation removed from the approve transaction | **13 failed** across generation, export and immutability |
| C | Capability endpoint ignores tenant context | **3 failed** — `test_doer_is_false`, `test_tenant_admin_follows_the_governed_mapping`, `test_authority_does_not_leak_across_tenants` |
| D | Frontend ignores `can_override_response` | **2 failed** — capability-false and fail-closed visibility |
| E | Approval metadata removed from the checksum-covered export | **3 failed** — projection, checksum coverage, checksum sensitivity |

## 7. `ControlledExportError` minor — DEFERRED again

Not fixed. The exception still covers three unrelated conditions (float
rejection, unsupported type, allow-list breach) whose correct HTTP answers
plausibly differ, so a single blanket mapping remains a governance call rather
than a mechanical fix. This slice touched export code only to read
`approval_metadata` through the existing projection, which gave no natural
occasion to resolve it. It remains fail-closed: no artifact is issued and no
success audit is emitted.

## 8. E2E — a pre-existing flake, measured not assumed

The Playwright suite reports **1 failure** on this branch:
`fda-iid.spec.ts:733` "Terminology mapping review › inspects a proposed synonym
mapping and opens the affected-record drill-down".

It is **not caused by this slice**. Evidence:

- It passes in isolation (`-g "affected-record drill-down"` → 1 passed).
- With this branch's changes **stashed**, the same suite on the clean merged base
  `4265ce8` fails **2 tests** — the same one plus
  `fda-iid.spec.ts:68` — i.e. the base is *flakier* than this branch.
- This slice touches no FDA-IID or terminology-mapping code path.

Recorded here rather than reported as green. Worth its own stabilisation task;
it is a parallel-execution race on a URL assertion, not a regression.

## 9. What still blocks Milestone 4D-4

1. **Production regulatory content — 0 of 20.** Human regulatory authorship; not
   an engineering task and not attempted.
2. **Override clearing** — deferred by §AC.4 pending its own decision.
3. **`fda-iid.spec.ts` E2E flakiness** — pre-existing, unrelated, needs its own fix.
4. **`ControlledExportError` structured-failure mapping** — deferred (§7).

Every registered governance decision (`4D4-DEC-001` … `-012`) is now **APPROVED**.
The remaining blocker to milestone completion is regulatory content, not
engineering.
