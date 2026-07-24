# FDA/IID Frontend Foundation

## Scope

A working subset of the Milestone 4A-4C frontend, built against the
existing Next.js App Router conventions (`frontend/src/app/**`, the
typed `@/lib/api.ts` client, `?tenant=slug` query-param tenant scoping).
**This is not the full 14-screen surface the milestone spec lists** — see
"What was not built" below for the exact gap.

## Routes implemented

| Route | Screen |
|---|---|
| `/fda-data/releases` | FDA release inventory + registration form |
| `/fda-data/releases/[publicId]` | Release detail, lifecycle actions (submit/approve/activate), reconciliation CSV download |
| `/fda-data/orange-book` | Orange Book product search |
| `/formulations` | Product-development record list + creation |
| `/formulations/[publicId]` | Product detail: explicit reference-product selection, formulation version, component table, dosing regimen |
| `/iid-assessments/preview` | IID match/calculation/decision preview |

## Provenance labeling

`frontend/src/components/ProvenanceLabel.tsx` renders one of four
labels — `FDA SOURCE`, `USER INPUT`, `CALCULATED`, `REVIEWER CONFIRMED` —
next to every value on these screens so a viewer can never mistake an
FDA-sourced precedent for a user-entered figure or a system-calculated
result. Each label carries `data-testid="provenance-label"` and
`data-provenance="<KIND>"` for test/automation targeting.

## Safety behaviors implemented and tested

- **No IID-to-formulation prefill**: the IID preview form's proposed-
  quantity field always starts empty; nothing on `/iid-assessments/preview`
  ever copies an IID value into a user-input field.
- **No auto-selected reference product**: `/formulations/[publicId]`
  shows "No reference product selected" until an explicit selection is
  submitted, and the selection form requires an unchecked-by-default
  confirmation checkbox before it will submit.
- **No automatic candidate selection**: when the backend returns
  `MULTIPLE_EXACT_MATCHES`, every candidate is listed with its own
  "Select this precedent" button — nothing is pre-selected or
  auto-highlighted as preferred.
- **Blocked calculations never show a value**: `CalculationBlock` renders
  `Blocked: <STATUS>` for any calculation whose `status !== "OK"`, never a
  zero or blank standing in for the real value.
- **Missing FDA values render as text, not zero**: a `null` potency/MDE
  renders `FDA VALUE UNAVAILABLE` / `MDE UNAVAILABLE` inline.
- **No automatic safety language**: `MATCH_STATUS_LABELS` and
  `DECISION_STATUS_LABELS` are closed lookup tables containing none of
  SAFE / FDA APPROVED / AUTOMATICALLY ACCEPTABLE / REGULATORILY CLEARED;
  the required disclaimer text is rendered verbatim from the backend's
  `decision_note`, never paraphrased.
- **No numeric IDs or raw paths rendered**: every list/detail screen
  reads only the UUID `public_id` and FDA-serializer fields — there is no
  code path that could render `storage_key` or a filesystem path (the
  backend never serializes them to non-`view_raw` holders either; see
  `FDA_DATA_GOVERNANCE.md`).
- **No sensitive data in browser storage**: the shared `apiRequest()`
  client (`frontend/src/lib/api.ts`) uses `credentials: "include"`
  (HttpOnly session cookies) exclusively — no `localStorage`/
  `sessionStorage` write exists anywhere in the new code, consistent with
  the existing repo-wide guard in `frontend.yml`.

## What was not built

Being direct about the gap against the full milestone spec:

- Not built as separate routes: `/fda-data/releases/new` (folded into the
  list page, matching the existing `template-sources` convention),
  `/fda-data/releases/[publicId]/reconciliation` (folded into the release
  detail page as a CSV download link), `/fda-data/mappings` (terminology
  mapping-review table), `/fda-data/orange-book/[publicId]` (detail page),
  `/formulations/new` (folded into the list page), `/formulations/
  [publicId]/versions/[versionPublicId]` (folded into the product detail
  page), `/iid-assessments/[publicId]` (persisted-snapshot detail view).
- No dedicated mapping-review UI for `RouteMapping`/`DosageFormMapping`/
  `UnitMapping` approval — those are currently backend-only (API +
  pytest coverage, no frontend).
- Final checklist execution and approval workflow (Milestone 4D) is
  **not implemented** — this was explicitly out of scope for 4A-4C and
  remains so.

See `docs/IID_FOUNDATION_TEST_STRATEGY.md` for the exact unit/
accessibility/Playwright test counts and what they cover.
