# FDA Terminology Mapping

## Why this exists

FDA source files use inconsistent free-text route/dosage-form/unit strings
(`"ORAL"`, `"Oral"`, `"PO"`, `"MG"`, `"mg"` ...). Every downstream engine in
`iid_assessment` needs an exact, controlled identity to compare against —
never a raw string. This module is the single place raw strings become
controlled vocabulary, and it is deliberately conservative: **no fuzzy
mapping may become approved automatically.**

## Controlled vocabularies

- `ControlledRoute` — canonical route (`code`, `canonical_label`,
  `lifecycle`).
- `ControlledDosageForm` — canonical dosage form, same shape.
- `ControlledUnit` — canonical unit (`code`, `symbol`, `dimension`,
  `aliases`, `active`). `code` is the canonical identifier used everywhere
  a unit needs to be looked up programmatically (e.g. `"milligram"`);
  `symbol` (e.g. `"MG"`) is a **display-only** abbreviation.

## Mapping rows

`RouteMapping`, `DosageFormMapping`, `UnitMapping` (all subclasses of
`_BaseTerminologyMapping` in `fda_data/models.py`) each record:
`source_dataset`, `source_raw_value`, the target controlled row, `status`
(`proposed`/`approved`/`rejected`), `is_current`, and reviewer/timestamp
fields.

Rules, enforced at the model and lookup level:

- A mapping starts `proposed`. Only an explicit reviewer action moves it to
  `approved` — there is no automatic promotion.
- `lookup_route_mapping` / `lookup_dosage_form_mapping` only resolve a raw
  value through a row that is **both** `status="approved"` **and**
  `is_current=True`. A `proposed` or `rejected` mapping resolves nothing —
  the raw value stays unmapped (`None`), which fails downstream matching
  closed (`ROUTE_UNMAPPED`/`DOSAGE_FORM_UNMAPPED`) rather than guessing.
- Mapping history is immutable after approval — an approved mapping row is
  never edited in place; superseding a mapping means creating a new row and
  retiring the old one's `is_current` flag, preserving full audit history.
- Tenant users can never edit platform FDA terminology — mapping management
  requires an `fda_data` role (Reviewer/VP), not any `formulations` role.

## Unit lookup (`lookup_unit`)

Exact match only, in order: `code` (case-insensitive) → `symbol`
(case-insensitive) → an explicit alias in `ControlledUnit.aliases`. No
substring, prefix, or fuzzy match. A unit string that matches none of these
resolves to `None`, which the unit-conversion engine treats as
`UNIT_UNKNOWN` (see `UNIT_CONVERSION_ENGINE.md`) — it is never guessed from
context.

## Dosage-form/route splitting

`split_dosage_form_route` handles the Orange Book combined `DF;Route` field
using an explicit, small separator list (`;`, `" - "`). An unrecognized
separator returns `("", "")` rather than guessing which half is which — an
empty raw value simply fails the subsequent mapping lookup.

## Strength parsing

`parse_strength` only accepts the single-number/single-unit shape
(`"500 MG"`). Ratios, combination-product strengths, and ranges are left
`status="review_required"` with the original text preserved verbatim — never
partially parsed or guessed.

## Mapping-review API and UI

`GET /api/regx/v1/fda-data/mappings/` (requires `fda_data.review`) lists
route/dosage-form/unit mappings in one normalized shape
(`TerminologyMappingSerializer.from_instance`), optionally filtered by
`?type=` and `?status=`, including a best-effort `affected_record_count`
(a count of Orange Book/IID rows referencing that raw value — informational
only, never used to gate the decision). `POST .../mappings/{type}/{public_id}/
approve/` and `.../reject/` require the same permission and always set the
acting user as `reviewer`; both are rejected by `full_clean()` if the
mapping is already approved (immutability, see `_BaseTerminologyMapping.clean()`
in `FDA_DATA_GOVERNANCE.md`).

`frontend/src/app/fda-data/mappings/page.tsx` consumes this API: every
approve/reject requires an explicit confirmation-dialog click (never a
bare button click), and the multi-select bulk-approve control calls the
same per-mapping scoped endpoint for each selection sequentially — there
is no unscoped "approve everything" action, consistent with the
"no bulk operation without tenant/platform scope" requirement.
