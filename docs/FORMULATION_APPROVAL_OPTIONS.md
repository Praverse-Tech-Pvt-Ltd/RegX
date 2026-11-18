# Formulation version approval: options (for decision)

**Status:** options only, nothing built. Owner + Pratham to decide. (PROJECT_OVERVIEW §11 item 32.)

## The problem

- **The rule:** the IIG checklist runs only on an **approved** formulation version. The API refuses a draft with `formulation_version_not_approved` (`backend/iig_checklist/views.py`).
- **The gap:** nothing in the app approves a formulation version. There is no endpoint and no screen. Only the demo seed (`seed_regx_demo`) creates approved versions, by writing to the database directly.
- **The consequence:** a formulation a user creates today can never have the IIG checklist run on it. Since PR #130 the app shows such versions as "not approved" and blocks the action with an explanation. The workflow itself is still missing.

What already exists and the options build on:
- **Statuses:** `FormulationVersion.status` already has draft, under_review, approved, superseded and retired (`backend/formulations/models.py`).
- **Immutability, in Python only:** an approved, superseded or retired version cannot be changed. This is enforced in `FormulationVersion.clean()` only; there is no database trigger, unlike the other governed objects.
- **Unused permission:** `formulations.submit_review` exists and Doer and Tenant Admin hold it, but no endpoint uses it. Reviewer and VP hold view only. Nobody holds an approve permission (`backend/formulations/permissions.py`).
- **The pattern to copy:** checklist versions and checklist executions already go Doer submits → Reviewer can return or reject → VP approves.
  - A user cannot approve what they submitted (`iig_checklist/views.py:630`).
  - Writes by Reviewer and VP require MFA enrolment (`authorization.middleware.MFAEnrolmentMiddleware`).
- **Existing tools:** a generic workflow engine (`backend/workflows`), and an append-only audit trail with Postgres immutability triggers.

All effort figures below are **[Estimate]**, for one developer who knows the codebase, and include tests, a real-stack check and docs.

---

## Option A (recommended): the existing Doer → Reviewer → VP pattern, on the formulation version itself

**How it works**
1. **Doer or Tenant Admin** submits a draft version for review: draft → under_review.
   - Submitting checks the version is complete: at least one component, a unit weight, and every component has a unit.
   - Submitting freezes the version's components and dosing regimen until the version is returned.
2. **Reviewer** (or VP) can **return** it with a reason (→ draft, editable again) or **reject** it (→ retired).
3. **VP** approves it with a short conclusion note: under_review → approved. After that, the version can be used for IIG checklist runs and is permanently frozen.
4. **Superseding:**
   - Approving a newer version of the same product marks the previous approved version **superseded**.
   - Checklist executions already run on the old version keep pointing at it, unchanged.
   - Changes after approval mean creating a new version. A "copy this version as a new draft" action is part of this option.

**Who can approve:** VP only (a new `formulations.approve` permission held by the VP role).

**Separation of duties**
- The user who submitted a version cannot approve it. This is checked in the view and the service, the same way as checklist versions.
- The Doer has no approve permission.
- The Tenant Admin can submit but not approve, so an administrator cannot approve their own organisation's formulation alone.

**MFA:** required for Reviewer and VP writes, through the existing middleware. Nothing new.

**Audit**
- **Audit trail:** one append-only event per transition — submitted, returned (with reason), rejected, approved (with note), superseded. Each records who, when, from and to status, and the version's public ID.
- **Recorded on the version:** submitted_by/at, approved_by/at and the note.
- **Database trigger, recommended:** add one so an approved, superseded or retired version, and its components and regimen, cannot be changed at the database level. That matches checklist versions and packages.

**Effort [Estimate]: about 5–7 days.**
- Backend: transitions, service, three endpoints, migration (new fields + trigger), permission, audit events.
- Frontend: buttons on the version page, an "awaiting approval" list for the VP, the copy-as-new-draft action.
- Tests, the real-stack check, docs.

**What changes for users**
- The version page gains: **Submit for review** (Doer/Admin); **Return**, **Reject** (Reviewer/VP); **Approve** (VP).
- New formulations can run the IIG checklist once approved.
- Editing a submitted or approved version is no longer possible: users return it to draft, or create a new version.
- The demo seed keeps working. It should switch from a direct database write to the new service.

**Risks:** low. The same shape is already tested three times in this codebase (checklist versions, executions, mappings).

---

## Option B: drive the approval through the generic workflow engine

**How it works**
- Submitting a version creates a `WorkflowItem` linked to it.
- Approval happens on the workflow item, using the existing Workflows pages. On approval, a service marks the formulation version approved.

**Who can approve:** whoever the workflow engine's role map allows. Today that is the **Reviewer and the VP** (both hold `workflows.approve`; `backend/workflows/permissions.py`). A Reviewer could therefore approve a formulation alone, with no VP.

**Separation of duties**
- The engine separates duties only through roles: the Doer creates, the Reviewer and VP approve. There is no explicit "creator cannot approve" check in `backend/workflows/services.py`, so a user holding two roles could approve their own item.
- That check has to be added, and enforced again on the formulation side, so approving the item and approving the version cannot drift apart.

**MFA:** same middleware as Option A.

**Audit:**
- The engine already records an append-only transition history.
- An audit event on the formulation version is still needed. Otherwise "why is this version approved?" means following a link into another app.

**Effort [Estimate]: about 6–9 days.**
- Less new lifecycle code than A.
- More wiring: a link from workflow item to version, a callback on approval, keeping two states consistent, and layering rules. `workflows` must not import `formulations`, so this needs a registry or hook, similar to `DeletionProtectionRegistry`.

**What changes for users:** approval happens on the Workflows pages, not on the formulation version page. Users go to two places.

**Risks: medium.**
- Two states can disagree (workflow approved, version not yet).
- The engine's own description (`backend/workflows/models.py`) says it "carries no regulatory content, confers no approval". Using it to approve a governed object goes against its stated design and needs that decision recorded.

---

## Option C: single-step approval by the VP (or Tenant Admin), no review step

**How it works:** a VP approves a draft version directly: draft → approved. There is no under_review state and no return or reject.

**Who can approve:** the VP. A variant would let the Tenant Admin approve as well; that is not recommended.

**Separation of duties:**
- The creator cannot approve.
- There is no independent reviewer step. That is weaker than every other governed object in REGX.

**MFA:** same middleware.

**Audit:** one event, "approved", with the note. Database trigger as in A.

**Effort [Estimate]: about 2–3 days.**

**What changes for users:** one **Approve** button for the VP; nothing for the Doer or Reviewer.

**Risks**
- Fastest, but inconsistent with checklist and mapping governance. There is no way to send a version back with a reason.
- Moving to A later means a second migration and changing what "approved" meant for versions approved under C.
- Acceptable only as a short-term demo unblocker, and only if the owner records that decision.

---

## Not recommended: let the checklist run on a draft version

Removing the "approved version" rule for checklist executions would unblock the demo with no new workflow. But:
- checklist results would then rest on a formulation that can still change;
- it would undo a deliberate rule (`formulation_version_not_approved`).

It is listed only so it is not proposed again without this context.

---

## Comparison

| | A (recommended) | B | C |
|---|---|---|---|
| Who approves | VP | Reviewer or VP (workflow role map) | VP |
| Independent review step | Yes (Reviewer can return / reject) | Yes | No |
| Creator cannot approve | Yes | Roles only; explicit check has to be added | Yes |
| MFA | Existing middleware | Existing middleware | Existing middleware |
| Audit | Event per transition + DB trigger | Workflow history + version event | One event + DB trigger |
| Effort [Estimate] | ~5–7 days | ~6–9 days | ~2–3 days |
| Where users act | Formulation version page | Workflows pages | Formulation version page |
| Consistency with REGX | Same as checklist versions / executions / mappings | New use of the engine | Weaker than other approvals |

## Questions the decision should answer

1. **Who approves?** Option A as written: VP. Should a Reviewer's "recommend" be recorded as a separate step?
2. **What does approval mean?** In wording (no regulatory or agency approval claims), "approved" is an internal workflow state. The screens should keep that clear.
3. **Must a version be complete to be submitted?** At least one component, unit weight, units on every component. And does a version need an IID preview or a reference product first?
4. **Can an approval be withdrawn?** Option A allows only superseding by a newer approved version, never un-approving. Is that right?
5. **What happens to the demo seed's approved version?** It should be re-created through the new service, so the audit trail shows a real approval.
