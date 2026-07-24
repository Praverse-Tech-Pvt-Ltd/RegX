# FDA/IID Frontend Foundation

## Scope

The full Milestone 4A-4C frontend route matrix, built against the
existing Next.js App Router conventions (`frontend/src/app/**`, the
typed `@/lib/api.ts` client, `?tenant=slug` query-param tenant scoping).
13/13 required routes are implemented. See "What was not built" below
for the remaining, explicitly out-of-scope gap (mapping-approval detail
drill-down beyond the list view, Milestone 4D).

## Route matrix (13/13 implemented)

| # | Route | Screen | API dependency | Permission dependency |
|---|---|---|---|---|
| 1 | `/fda-data/releases` | Release inventory, dataset-type filter, links to search/mappings/registration | `fdaData.releases.list` | `fda_data.view` |
| 2 | `/fda-data/releases/new` | Registration form (dataset type, source name/reference, schema version, synthetic rows JSON) | `fdaData.releases.register` | `fda_data.register` |
| 3 | `/fda-data/releases/[publicId]` | Release detail: status, provenance, counts, lifecycle actions (submit/approve/activate) | `fdaData.releases.get`, `.submitReview`, `.approve`, `.activate` | `fda_data.view` / `.import` / `.approve` / `.activate` |
| 4 | `/fda-data/releases/[publicId]/reconciliation` | Reconciliation summary: counts, per-row result/reason table, CSV download | `fdaData.releases.reconciliationJson` | `fda_data.export_reconciliation` |
| 5 | `/fda-data/mappings` | Terminology mapping review: type/status filters, approve/reject with confirmation dialog, multi-select bulk-approve | `fdaData.mappings.list/.approve/.reject` | `fda_data.review` |
| 6 | `/fda-data/orange-book` | Orange Book search: ingredient/route/dosage-form/strength/application-type text filters, RLD/reference-standard/discontinued filters, pagination | `fdaData.orangeBook.search` | `fda_data.view` |
| 7 | `/fda-data/orange-book/[publicId]` | Product detail: parsed/raw strength, application/product number, TE code, approval-date text, RLD/RS/discontinued flags | `fdaData.orangeBook.get` | `fda_data.view` |
| 8 | `/formulations` | Product-development record list, links to creation | `formulations.products.list` | `formulations.view` |
| 9 | `/formulations/new` | Product creation form | `formulations.products.create` | `formulations.create` |
| 10 | `/formulations/[publicId]` | Product detail: explicit reference-product selection, formulation-version list + creation | `formulations.products.get/.selectReference`, `.versions.list/.create` | `formulations.view` / `.edit_draft` / `.create` |
| 11 | `/formulations/[publicId]/versions/[versionPublicId]` | Version detail: total weight/max units, component table (active/inactive, % w/w), dosing-regimen list + entry, link to IID preview | `formulations.versions.get`, `.components.list/.create`, `.dosingRegimens.list/.create` | `formulations.view` / `.create` |
| 12 | `/iid-assessments/preview` | Match/calculation/decision preview, multi-candidate selection | `iidAssessments.preview` | `iid_assessment.preview` |
| 13 | `/iid-assessments/[publicId]` | Persisted, immutable assessment snapshot detail | `iidAssessments.get` | `iid_assessment.preview` |

Every route is reachable via in-app navigation (not only direct URL) —
see the cross-links table below.

| From | Links to |
|---|---|
| `/fda-data/releases` | Orange Book search, Terminology mappings, Register release (new), each release's detail |
| `/fda-data/releases/[publicId]` | Reconciliation summary, back to release list |
| `/fda-data/releases/[publicId]/reconciliation` | Back to release detail, CSV download |
| `/fda-data/orange-book` | Each product's detail page, back to release list |
| `/fda-data/orange-book/[publicId]` | Back to search |
| `/formulations` | New product record, each product's detail |
| `/formulations/new` | Back to product list |
| `/formulations/[publicId]` | Each formulation version's detail, back to product list |
| `/formulations/[publicId]/versions/[versionPublicId]` | Back to product detail, IID assessment preview (pre-filled version ID) |
| `/iid-assessments/preview` | (entry point; no persisted snapshot is created from this pass's UI) |
| `/iid-assessments/[publicId]` | Back to a fresh preview |

## Provenance labeling

`frontend/src/components/ProvenanceLabel.tsx` renders one of four
labels — `FDA SOURCE`, `USER INPUT`, `CALCULATED`, `REVIEWER CONFIRMED` —
next to every value across all 13 screens so a viewer can never mistake
an FDA-sourced precedent for a user-entered figure or a system-calculated
result. Each label carries `data-testid="provenance-label"` and
`data-provenance="<KIND>"` for test/automation targeting, and is text
(not colour-only) so it does not depend on color perception.

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
- **No automatic mapping approval**: `/fda-data/mappings` requires an
  explicit confirmation-dialog click for every approve/reject action,
  including the multi-select bulk-approve path (which calls the same
  scoped per-mapping endpoint sequentially — there is no unscoped
  "approve everything" action).
- **No automatic Orange Book RLD/reference-standard selection**: the
  product-detail page's reference-product selection is always a separate,
  explicit, confirmed action — never inferred from a product's RLD/RS
  flags, even when it is the only search result.
- **Blocked calculations never show a value**: `CalculationBlock` renders
  `Blocked: <STATUS>` for any calculation whose `status !== "OK"`, never a
  zero or blank standing in for the real value.
- **Missing FDA values render as text, not zero**: a `null` potency/MDE
  renders `FDA VALUE UNAVAILABLE` / `MDE UNAVAILABLE` inline, on both the
  live preview and the persisted snapshot detail page.
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

Being direct about the remaining gap against the full milestone spec:

- No dedicated UI for substance/UNII synonym mappings — the backend has
  no model for this (only route/dosage-form/unit mappings exist), so no
  frontend or API work was added for it; adding one would have been
  scope creep beyond "the minimal endpoint genuinely missing."
- No standalone "view affected records" drill-down from a mapping row —
  the affected-record *count* is shown, but not a list of the records
  themselves.
- Final checklist execution and approval workflow (Milestone 4D) is
  **not implemented** — this was explicitly out of scope for 4A-4C and
  remains so. No route, component, or backend endpoint in this branch
  performs checklist execution.

See `docs/IID_FOUNDATION_TEST_STRATEGY.md` for the exact unit/
accessibility/Playwright test counts, the full 20/20 E2E scenario
mapping, and what backend work this pass added.
