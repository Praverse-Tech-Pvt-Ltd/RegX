# Milestone 6 — Workflow Engine Discovery

**Discovery only. No code changed.**

Surveyed against `regx-main` `eaef74f0014248228a62b5bd39979f13abd34a42`.

The headline finding is that **almost nothing here needs inventing**. Every
mechanism Milestone 6 requires — transition tables, locking, append-only
history, immutable audit, tenant scoping, permission classes, public-ID APIs —
already exists in this repository, in at least two independent implementations
each. The work is to follow those conventions for a sixth domain, not to build a
framework.

---

## A. The current workflows scaffold

`backend/workflows/` is five files and one model. There are **no views, no
serializers, no urls, no permissions, no admin and no tests** — the app is not
routed in `regx/api_v1_urls.py` at all.

```python
class WorkflowItem(PublicIDModel, TimeStampedModel):
    """Placeholder workflow item. Full domain implementation in subsequent milestone."""
    class State(models.TextChoices):
        DRAFT / SUBMITTED / APPROVED / REJECTED
    tenant, created_by, title, state
```

One migration, `0001_initial`. `state` is a plain `CharField` with a default —
**nothing prevents arbitrary assignment today**, which is precisely what §2 of
the brief targets.

Two states in the required set are missing: `IN_REVIEW` and `CANCELLED`.

---

## B. Existing lifecycle / state-transition patterns

Five implementations exist. Two share an explicit, documented shape:

| Module | Shape |
|---|---|
| `iig_checklist/transitions.py` | **the reference implementation** |
| `fda_data/mapping_transitions.py` | same shape, keyed additionally by mapping type |
| `fda_data/lifecycle.py` | per-action functions, `select_for_update` + atomic |
| `templates_registry/lifecycle.py` | same, plus sibling-set locking |
| `iid_assessment/services.py` | domain services |

`iig_checklist/transitions.py` states its own lineage: *"structurally identical
in shape to `fda_data/mapping_transitions.py`"*. That makes the shape a
**convention**, not one author's preference:

```python
class VersionAction:            # string constants, not an enum
    SUBMIT_REVIEW = "submit_review"
    ...

class IllegalVersionTransition(Exception):
    def __init__(self, message, current_status): ...

# {action: (frozenset of legal current statuses, resulting status)}
_TRANSITIONS = { ... }

def validate_version_transition(current_status, action) -> str:
    """Returns the resulting status ... Raises IllegalVersionTransition
    otherwise -- callers must not mutate or save the version in that case."""
```

**Milestone 6 will be the third instance of this shape.** A separate generic
state-machine abstraction would be a fourth pattern competing with three
existing ones, and is explicitly rejected — see §J.

### Concurrency is already solved, identically, ~50 times

`select_for_update()` inside `transaction.atomic()`, re-fetch the locked row,
validate against **the locked row's** status, then save. `iig_checklist/views.py`
states the rule in its module docstring: transitions run *"inside
select_for_update()+transaction.atomic(), never"* elsewhere.

This directly satisfies §3 and §11. Validating against a status read before the
lock is the bug this pattern exists to prevent, and it is what makes
"approve vs reject from `IN_REVIEW`" resolve deterministically.

---

## C. Authorization — and a fork that must be resolved

**Two permission conventions coexist.** This is the one genuine architectural
decision in this milestone.

| | Convention 1 | Convention 2 |
|---|---|---|
| Codename | `workflow:submit` (colon) | `formulations.create` (dot) |
| Storage | `Permission` / `RolePermission` DB tables | in-code `ROLE_PERMISSIONS` dict |
| Defined in | `authorization/seed.py` | per-app `permissions.py` |
| Used by | seed + three read-only endpoints | **all six domain apps** |

Enforcement at runtime is **convention 2** everywhere. `documents`, `fda_data`,
`formulations`, `iid_assessment`, `iig_checklist` and `templates_registry` each
ship a `permissions.py` with dot codenames, a `ROLE_PERMISSIONS` map keyed by
`Role.BuiltIn`, a `has_<domain>_permission(user, tenant, codename)` helper and
thin `BasePermission` subclasses.

The DB `Permission` table is not vestigial, but it is **read-only at runtime**:
`authorization/views.py` exposes `permission_list` and `effective_permissions`,
which is how the frontend learns what a user may do. `documents/permissions.py`
bridges the two by calling `Permission.objects.get_or_create(codename=...)` for
each of its dot codenames.

> **`workflow:submit`, `workflow:approve` and `workflow:reject` are already
> seeded** and mapped to `doer`, `reviewer` and `vp` — leftovers from the
> scaffold era. The `Permission` model's own docstring uses
> `'workflow:submit'` as its example.

**Decision (§I):** follow convention 2 — `workflows.*` dot codenames with a
`workflows/permissions.py` — because that is what all six real domain apps do
and what enforcement actually reads. Register the codenames into the DB table as
`documents` does, so the effective-permissions endpoint can drive the UI.
**The three legacy `workflow:*` seed rows will be left in place**: they are
harmless, and deleting seeded permissions could strip grants from existing role
assignments. They will be documented as legacy rather than silently removed.

---

## D. Immutable audit

`audit.models.AuditEvent`, append-only, enforced by a **PostgreSQL trigger**
created in `audit/migrations/0001_initial.py` — `RunSQL` with `reverse_sql`,
raising on any `UPDATE` or `DELETE` of `audit_auditevent`.

Five apps ship an `audit_events.py` with a keyword-only `emit(...)` helper
taking `event_type`, `resource_type`, `resource_id`, `actor_id`, `actor_email`,
`tenant_id`, `payload`, `ip_address`. Milestone 6 adds a sixth, identical in
shape.

Actor and IP context comes from `audit/middleware.py`, which keeps
`ip_address` and `user_agent` in a thread-local for the request.

---

## E. Append-only history — already solved, do not reinvent

`iig_checklist.models.ChecklistResponseHistory` is the pattern §4 describes:

- `GovernedHistoryMutationForbidden` exception;
- `_ImmutableHistoryQuerySet` overriding `update()`, `delete()`, `bulk_update()`;
- a manager returning it;
- model-level `save()` rejecting any call where `self.pk is not None`, and
  `delete()` always rejecting.

`WorkflowTransition` will reuse this exact structure. Note it is **model-level**,
not a database trigger — the trigger approach is reserved for `AuditEvent`.
Using model guards here keeps a second history table consistent with the first,
which is what §4 asks for; a DB trigger would be a third mechanism.

---

## F. Tenant scoping and public IDs

`tenancy/context.py` provides `set_current_tenant` / `current_tenant` /
`clear_current_tenant`, populated by `TenantMiddleware`. `TenantScopeMissing`
signals absence. Domain views call a local `_require_tenant()` and filter every
queryset by it.

`common.models.PublicIDModel` supplies `public_id` (UUID4, unique, indexed).
Its docstring is unambiguous: *"Internal BigAutoField PK is never exposed in API
responses. Callers use public_id (UUID) for all external references."* This is
the §10 requirement, already the house rule.

---

## G. API conventions

`regx/urls.py` → `api/regx/v1/` → `regx/api_v1_urls.py`, which includes each
app's `urls.py`. Function-based views with `@api_view` and `@extend_schema`
(drf-spectacular) are the prevailing style in the domain apps.
`common/exceptions.py` provides the shared JSON error envelope via
`regx_exception_handler`.

**`workflows` is not currently routed.** Milestone 6 adds
`path("", include("workflows.urls"))`.

---

## H. Frontend and test conventions

Frontend module pages live under `frontend/src/app/(regx)/<module>/`; ten exist.
E2E specs are one file per module under `frontend/e2e/`, run by the F-1 harness
on `:3100` with `reuseExistingServer: false` and a 15s `expect` timeout (F-7).

Backend tests live in `<app>/tests/` with a `conftest.py` per app, pytest with
`@pytest.mark.django_db`. **PostgreSQL only** — `regx/settings/test.py` sets the
Postgres engine, which is what makes the §11 concurrency test possible at all.
Coverage gate is 55%; the suite currently runs 2,198 tests at ~95%.

---

## I. Proposed architecture

Six new modules in `backend/workflows/`, each mirroring an existing app:

| Module | Mirrors | Contents |
|---|---|---|
| `transitions.py` | `iig_checklist/transitions.py` | `WorkflowAction`, `IllegalWorkflowTransition`, `_TRANSITIONS`, `validate_workflow_transition` |
| `services.py` | `fda_data/lifecycle.py` | one function per action; `select_for_update` + atomic; writes history; emits audit |
| `permissions.py` | `formulations/permissions.py` | `workflows.*` codenames, `ROLE_PERMISSIONS`, helper, `BasePermission` classes |
| `audit_events.py` | `documents/audit_events.py` | `WorkflowEvent` constants + `emit()` |
| `serializers.py`, `views.py`, `urls.py` | `formulations` | public-ID-only, action endpoints, no `state` PATCH |
| `models.py` (extended) | `ChecklistResponseHistory` | `WorkflowTransition` append-only |

**State graph** — the brief's set, adopted as specified:

`DRAFT → SUBMITTED → IN_REVIEW → APPROVED | REJECTED`, `REJECTED → DRAFT`,
`CANCELLED` reachable from `DRAFT`, `SUBMITTED` and `IN_REVIEW`.

`APPROVED` and `CANCELLED` terminal. The brief permits a supersede/reopen path
only on repository evidence; such a pattern **does exist**
(`ChecklistVersionStatus.SUPERSEDED`, `TemplateVersion` supersede) but it is
bound to versioned governed content, not to a generic work item. Reusing it here
would import versioning semantics this model does not have, so **`APPROVED`
stays terminal** in this milestone.

---

## J. Non-goals

- **No generic state-machine framework.** Three transition-table
  implementations already exist; a fourth abstraction over them is refactoring
  work with its own risk, and this milestone is not chartered for it.
- **No new immutability mechanism.** Model guards for history, DB trigger for
  audit — as they already are.
- **No new RBAC concepts or regulatory roles.** The five `Role.BuiltIn` roles
  are reused as-is.
- No notifications or email — no framework exists, and §7 forbids inventing one.
- No SLA, escalation or overdue policy. `is_overdue` is computed from `due_at`
  and terminality, nothing more.
- No electronic-signature semantics. A required reason is a required reason.
- **No production regulatory content**, no dosage-form selection, no Item 1
  resolution, no change to the 0/20 count, no policy decision, no S-1/S-2
  closure, no Part 11 claim.

---

## K. Migration risk

Classified per `RELEASE_ROLLBACK_RUNBOOK.md` §4.

| Change | Class | Note |
|---|---|---|
| Add `IN_REVIEW`, `CANCELLED` to `State.choices` | **A** | Choices are not a DB constraint in Django; no data change |
| Add nullable `assigned_to`, `assigned_at`, `due_at` | **A** | Additive, nullable, reversible |
| Create `WorkflowTransition` | **A** | New table; reverse drops it |
| Register permission codenames | **A** | `get_or_create`, idempotent |

**No `RunPython`. No data migration. No destructive operation.** The whole
change set is additive and structurally reversible.

Existing-row check: `WorkflowItem` has no factory, no fixture and no test in the
repository, and the app is not routed, so **no row can have been created through
the application**. A deployed database could still hold rows created by hand;
because every new field is nullable and no existing field changes, such rows
remain valid and land in `DRAFT` semantics unchanged.

**One caveat that is class C if it is ever attempted:** once `WorkflowTransition`
rows exist, reversing the migration drops them. They are append-only *history*,
so that is destruction of an audit-like record, not a schema rollback. The
runbook's answer applies — data restore, not backward migration.

---

## L. Security and data integrity

- **Fail closed.** `has_workflow_permission` returns `False` on missing user,
  missing tenant or missing membership, matching the existing helpers.
- **No `is_staff` / `is_superuser` escape.** No domain app uses them for
  authorization and neither will this one.
- **Tenant isolation is the release-blocking property.** Every queryset filters
  by `current_tenant()`; assignment validates the target user's
  `TenantMembership` in the *same* tenant; `public_id` lookups are scoped, so a
  valid UUID from another tenant returns 404, never 403 — which also avoids
  confirming existence across a tenant boundary.
- **No arbitrary `state` write.** `state` is read-only in the serializer; it
  changes only through action endpoints.
- **Audit payload allow-listed** — action, from/to state, actor, reason
  presence. Never request bodies, credentials or governed document content.
- **Reason is not a signature.** Required on `REJECT` and `CANCEL`, recorded as
  text, and documented as carrying no electronic-signature meaning.
- **Concurrency**: the locked-row re-validation makes the second of two
  conflicting transitions fail deterministically rather than silently winning.

---

## Governance

Unchanged and unaffected by this milestone: governance approvals **0 of 20**,
production questions **0**, Item 1 **PENDING**, production regulatory content
**BLOCKED**, the thirteen owner-policy decisions **PENDING**, S-1 and S-2
**NOT CONFIRMED**.

This is workflow infrastructure. It carries no regulatory content, confers no
approval, and makes no Part 11 or validation claim.
