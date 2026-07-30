# Milestone 4D-1: Checklist Definition Governance — Implementation Record

Status: implemented, pending CI verification and human review before merge.
Scope: this milestone implements checklist **definition governance** only.

## What this milestone does NOT implement

Per the approved specification, the following are explicitly out of scope
and are not present anywhere in this branch:

- ChecklistExecution, ChecklistResponse, CalculationOutcome
- Draft-answer generation or any checklist execution workflow
- Overrides or deviations for executions, or execution approval
- JSON/CSV execution exports
- Real regulatory checklist content, FDA data imports, or client data
- Milestone 4D-2 work of any kind

## Backend: `iig_checklist` app

New Django app at `backend/iig_checklist/`, registered in `INSTALLED_APPS`
and mounted at `/api/regx/v1/iig-checklists/`.

### Domain model

- **`ChecklistDefinition`** — stable identity (code + scope). No lifecycle
  status of its own; a definition can be `platform_master` or `tenant`
  scoped, with DB-level constraints enforcing scope/tenant consistency and
  normalized-code uniqueness per scope.
- **`ChecklistVersion`** — carries the full 8-status lifecycle (`draft`,
  `under_review`, `returned`, `approved`, `active`, `superseded`,
  `rejected`, `retired`). This split (definition vs. version) is a
  disclosed, approved refinement of the original single-model design —
  see `docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md` §3a.
- **`ApplicabilityRule`** — a structured, allow-listed JSON condition tree
  (10 leaf operators, 2 composite operators) that decides whether a
  section/question applies. No `eval`/`exec`; bounded recursion depth (5),
  condition count (50), and payload size (8KB).
- **`ChecklistSection`** / **`ChecklistQuestion`** — structural content of a
  version, each with an optional applicability rule.

### Lifecycle

Seven actions, an 8-status table, implemented once as the authoritative
source of truth in `transitions.py::validate_version_transition()`:

| Action | Legal from | Result |
|---|---|---|
| `submit_review` | draft, returned | under_review |
| `approve` | under_review | approved |
| `return` | under_review | returned |
| `reject` | draft, under_review | rejected (terminal) |
| `activate` | approved | active |
| `supersede` | active | superseded (terminal) |
| `retire` | draft, approved, active, returned | retired (terminal) |

This adds `return`/`returned` and a distinct terminal `rejected` beyond the
original 6-action design — an approved refinement, not a defect.

Key invariants enforced server-side, not just in the UI:

- Self-approval is blocked: the actor who submitted a version cannot
  approve it, even if they hold both permissions via multiple roles.
- A Doer can never approve or activate (segregation of duties).
- Only one version per definition may be `active` at a time — enforced by
  a partial unique DB constraint plus `select_for_update()` in the
  activation path, so it holds under concurrency, not just in the happy
  path.
- Version numbers are never client-supplied; allocation locks the parent
  `ChecklistDefinition` row and takes `MAX(version_number) + 1` inside
  `transaction.atomic()`.
- `effective_date` (required before activation) can only be set while a
  version is still `draft`/`returned` — the model blocks mutating it, or
  `regulatory_basis`/`change_summary`/`expiry_date`, once a version is no
  longer editable.
- No audit event is emitted on a failed/illegal transition.

### Clone

`services.py::clone_definition()` creates a brand-new `ChecklistDefinition`
and a fresh `version_number=1` `DRAFT` version. Eligible source statuses
are `approved`, `active`, `superseded` only. Nothing about prior approval,
audit history, or the active-version pointer is copied — every row gets a
new UUID `public_id`. Cross-tenant cloning and platform-to-tenant cloning
both require explicit authorization beyond ordinary clone permission.

### Deletion policy

Governed versions are never hard-deleted. The one narrow exception: a
definition with exactly one version, that version still `draft` and never
submitted, may be deleted by an actor holding `delete_draft` permission.
The audit event is emitted before the delete call (since `AuditEvent`
stores denormalized string/UUID metadata, not live foreign keys).

### Permissions

Eleven ordinary codenames (`iig_checklist.view_definition`, `create_definition`,
`edit_draft`, `submit_review`, `review`, `approve`, `activate`, `retire`,
`clone`, `delete_draft`, `view_audit`), mapped to the platform's five
built-in roles the same way `fda_data` does it — fail-closed, tenant-
membership-based lookup, server-side authoritative (never trust a client-
supplied role).

#### Platform-master authorization (post-review remediation)

A human review of the initial implementation found a Major defect: creating
a `platform_master`-scoped definition (globally visible to every tenant)
required only ordinary `create_definition`/`clone` permission — held by any
Doer, in any tenant. Nothing distinguished "author tenant-scoped content"
from "author platform-wide content."

The fix adds a twelfth codename, `iig_checklist.create_platform_definition`,
that is **deliberately absent from every built-in role's `ROLE_PERMISSIONS`
entry** — Doer, Reviewer, VP, Tenant Admin, and Platform Support all fail
this check regardless of what else they hold. The actual grant is
represented by Django's `is_superuser` flag (`can_author_platform_master()`
in `permissions.py`) — the same mechanism already used elsewhere in this
codebase (`identity/managers.py`) to represent authority that is not
tenant-scoped, rather than inventing a parallel "platform role" concept.

Both code paths that can produce a `platform_master` definition —
`ChecklistDefinitionListCreateView.post` (direct create) and
`ChecklistDefinitionCloneView.post` (clone) — call the same single function,
`can_create_definition_for_scope(actor=..., scope_type=...)`, before any
database write and before the transaction opens, so a denied request never
creates a definition/version and never emits a success audit event. This
was a deliberate design choice to prevent the two paths drifting apart
again (which is exactly how the original defect happened — the clone path
had its own ad hoc, narrower guard that the direct-create path never
received).

#### Platform-master content-MUTATION authorization (second post-review remediation)

An independent adversarial re-review, performed specifically before merge,
found a second, related defect: the first fix only closed the *creation*
boundary. `ChecklistDefinitionManager.visible_to()` (and every manager built
on it) deliberately exposes `platform_master` rows to **every** tenant so
they can be read — that is correct and unchanged. But every endpoint that
mutates content on an *already-existing* platform-master version —
`ChecklistVersionCreateView.post` (new version), `ChecklistVersionDetailView.patch`,
every lifecycle action (submit-review/approve/return/reject/activate/
supersede/retire), section/question/applicability-rule create/update/
delete — was still gated only by the ordinary, object-agnostic tenant-
membership permission classes (`CanEditChecklistDraft`, `CanCreateChecklistDefinition`,
etc.). None of them re-checked that the specific object's scope matched
the actor's authorization. Net effect: any ordinary Doer in any unrelated
tenant could mutate someone else's platform-master content once they had
its public_id (discoverable through the same universally-visible read
endpoints).

**Root cause:** visibility and mutation authority were never distinguished
at the object level — only at the two definition/clone entry points.

**Correction:** `permissions.py::can_mutate_definition_scope(*, actor,
definition, tenant, required_permission)` is now the single authoritative
object-scope mutation check. It:
- requires the ordinary action permission (`edit_draft`, `create_definition`,
  `submit_review`, `review`, `approve`, `activate`, `retire`, `delete_draft`)
  in the actor's current tenant context, exactly as before;
- **additionally** requires `can_author_platform_master()` when the
  resolved definition is `platform_master` — the same platform grant
  required to create/clone platform-master content in the first place;
  neither Reviewer, VP, Tenant Admin, nor Platform Support role membership
  ever substitutes for it, and the platform grant never substitutes for
  the ordinary action permission either (additive, not either/or);
- validates tenant ownership for `tenant`-scoped objects as defense in
  depth (already guaranteed structurally by `visible_to()`, which never
  returns a different tenant's row in the first place).

Every mutating endpoint in `views.py` calls this through one helper,
`_authorize_mutation(request, tenant, definition, required_codename)`,
immediately after resolving the target object and before any write or
audit emission — applied uniformly to version create/patch/all seven
lifecycle actions, section create/update/delete, question create/update/
delete, applicability-rule create, and definition deletion.

A pre-existing, unrelated bug was also found and fixed while adding
regression coverage for the applicability-rule endpoint:
`ApplicabilityRuleListCreateView.post` never set `created_by`, a required
field, so every rule-creation request — authorized or not — would have
failed with a validation error regardless of this remediation. Fixed by
passing `created_by=request.user` alongside the existing fields.

### Audit

Twenty distinct event types (`iig_checklist.definition.created`,
`.version.activated`, `.definition.cloned`, etc.) via a shared `emit()`
wrapper. Every event carries public IDs only — no numeric PKs, no storage
paths, no full proprietary payload.

### API surface

UUID-only request/response bodies, generic 404s (never distinguishing
"not found" from "not authorized" to a client probing for existence),
structured `{"error_code": ..., "detail": ...}` bodies on 400/409 (never a
raw DB exception), bounded pagination, and `status` is never patchable
through the generic version PATCH endpoint — only through the dedicated
lifecycle-action endpoints.

## Frontend

Minimal administration screens under `/iig-checklists`, mirroring the
conventions already established by the `fda-data`/`formulations` screens
(inline styles, no component library, `apiRequest` wrapper in
`src/lib/api.ts`):

- `/iig-checklists` — definition list, create.
- `/iig-checklists/[publicId]` — definition detail: version history,
  create-new-version, clone-into-new-definition, delete-empty-draft.
- `/iig-checklists/versions/[versionPublicId]` — version detail: read-only
  section/question listing, and the seven lifecycle-action buttons gated
  by current status (never rendering an execution-domain control).

No checklist-execution UI exists anywhere in this milestone's frontend.

The create-definition form distinguishes a 401 (unauthenticated → redirect
to sign-in) from a 403 (authorized-but-denied → inline message, no
redirect) — selecting "Platform master" also shows an inline notice that it
requires a separate, explicit platform-level authorization before the form
is even submitted. This was itself a small defect found while implementing
the platform-master remediation: the form previously treated every 403 the
same as a 401 and silently redirected to `/signin`, which would have hidden
a legitimate platform-authorization denial from the user. The frontend has
no signal for `is_superuser` (exposing it would require changing the shared
`identity` app's user-profile serializer, judged out of scope for this
narrowly-scoped remediation), so the option is not hidden — the server
remains the sole source of truth, and the denial is now surfaced clearly
rather than concealed.

The version-detail screen now also exposes `scope_type` on the version
serializer (a small, in-domain, additive field — not a change to the
shared `identity` app) and shows a passive notice when a version belongs
to a `platform_master` definition: "requires a separate, explicit
platform-level authorization." Since the frontend still cannot determine
whether the *current* actor holds that grant without the same shared-
identity change judged out of scope, the lifecycle/edit controls are not
hidden — they remain visible for every actor, and a 403 from any of them
is handled exactly like the create-form fix above: inline message, no
signin redirect, no optimistic status change (the version is only
reloaded after a real 2xx response).

## A real defect this milestone's own process caught

While wiring the Docker CI production-API flow (`docker-integration.yml`),
running the flow against the live backend (not the frontend's mocks)
surfaced that `ChecklistDefinitionCloneView`'s actual response is a flat
object (`{public_id, code, ..., current_version: {...}}`), while the
frontend's `iigChecklists.definitions.clone()` type and the definition-
detail page's clone handler both assumed a nested
`{definition: {...}, current_version: {...}}` shape — a contract mismatch
that the frontend's own mocked unit/Playwright tests could not have
caught, because the mocks encoded the same wrong assumption. This is the
justification for the CI script's design: it drives the real Django view
stack (`django.test.Client` through `manage.py shell`), not just ORM calls
or frontend mocks, specifically to catch this class of defect. See the
"fix(iig_checklist): correct clone-endpoint response shape mismatch"
commit.
