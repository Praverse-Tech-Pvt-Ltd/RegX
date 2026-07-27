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

## Substance/UNII synonym mappings

`SubstanceSynonymMapping` (`fda_data/models.py`) is a fourth, richer
mapping type governing ingredient identity — raw ingredient name → a
proposed canonical `IIDIngredient`, UNII, and/or CAS number. It exists
because ingredient identity carries more risk than a route/dosage-form/unit
label: a wrong ingredient match can silently compare the wrong precedent.
Its lifecycle is deliberately larger than the other three types'
`MappingDecisionStatus` (`proposed`/`reviewed`/`approved`/`rejected`):
`SubstanceMappingStatus` adds `under_review` and `returned`, modeling a
real segregation-of-duties review step before approval.

Fields: `release` (nullable — null means "platform master", not scoped to
one release; **`on_delete=PROTECT`**, so a release with mapping history can
never be silently deleted), `source_dataset`, `raw_ingredient_name` /
`normalized_ingredient_name` / `raw_unii` / `raw_cas_number` (all
immutable once the row exists — see `clean()`), `proposed_ingredient` /
`proposed_unii` / `proposed_cas_number`, `mapping_method`
(`exact_name`/`exact_unii`/`exact_cas`/`reviewed_synonym`/`manual`),
`status`, `is_current`, `reviewer` / `review_reason` / `reviewed_at`,
`approved_by` / `approved_at`.

Rules enforced at the model layer:

- Raw source-identity fields (`raw_ingredient_name`, `normalized_ingredient_name`,
  `raw_unii`, `raw_cas_number`, `release`, `source_dataset`,
  `source_row_locator`) are immutable from the moment the row is created —
  never just once approved.
- Once `status == APPROVED`, every field is immutable except `is_current`
  and `updated_at`. A correction requires a new mapping row with the old
  row's `is_current` flipped to `False` — never an in-place edit.
- `UniqueConstraint` on `(source_dataset, raw_ingredient_name, release)`
  where `is_current=True` prevents two simultaneously-active mappings for
  the same raw identity in the same release.

### Candidate generation (`fda_data/substance_matching.py`)

`resolve_substance_identity(normalized_name=, unii=, cas_number=)` is the
single shared service used by IID import normalization, the IID matching
engine, the terminology-review API, and the affected-record drill-down.
It tries, in order: an approved mapping matching UNII, CAS, or normalized
name; then a direct exact match against the canonical `IIDIngredient`
table (covers identities that never needed a governed mapping because the
raw value was already exact). **The direct `IIDIngredient` fallback never
runs if any non-approved mapping already references this identity** — a
proposed/rejected/under-review/returned mapping means a human has already
flagged this identity for governance, and string equality must never
silently bypass that unresolved state.

Returns one of:

- `EXACT_MATCH` — exactly one candidate resolved.
- `MULTIPLE_CANDIDATES` — two or more approved mappings resolve to
  different ingredients; never auto-picked.
- `REVIEW_REQUIRED` — no approved mapping exists, but a
  proposed/under_review/returned one does (reason code
  `MAPPING_PENDING_REVIEW`), or nothing at all was ever proposed (reason
  code `NO_APPROVED_MAPPING`).
- `INGREDIENT_AMBIGUOUS` — either no identity was supplied at all
  (`NO_IDENTITY_SUPPLIED`), or the only mapping found was explicitly
  `REJECTED` (`REJECTED_MAPPING`) — deliberately distinct from
  `REVIEW_REQUIRED` so a denied identity is never confused with one that
  simply hasn't been reviewed yet.

A mapping scoped to a specific (non-null) `release` is only honored while
that release's status is `approved` or `active` — a superseded release's
mappings stop supplying resolutions the moment it is superseded.

## Mapping-review API and UI

`GET /api/regx/v1/fda-data/mappings/` (requires `fda_data.review`) lists
route/dosage-form/unit/substance mappings in one normalized shape
(`TerminologyMappingSerializer.from_instance`), filterable by `?type=`,
`?status=`, `?release=` (release public_id), `?raw_value=` (substring,
case-insensitive), and `?reviewer=` (reviewer email), including a
best-effort `affected_record_count` — informational only, never used to
gate a decision. Substance-mapping rows additionally carry
`proposed_unii`, `proposed_cas_number`, `mapping_method`, and
`release_public_id`.

The mapping action routes are **type-less** — a mapping's `public_id` is
resolved across all four model types by `_find_mapping_or_404`, so the URL
never needs to encode which kind of mapping it is:

```
GET  /api/regx/v1/fda-data/mappings/{public_id}/
GET  /api/regx/v1/fda-data/mappings/{public_id}/affected-records/
POST /api/regx/v1/fda-data/mappings/{public_id}/submit-review/
POST /api/regx/v1/fda-data/mappings/{public_id}/approve/
POST /api/regx/v1/fda-data/mappings/{public_id}/reject/
POST /api/regx/v1/fda-data/mappings/{public_id}/return/
```

`submit-review` and `return` transition to `under_review`/`returned` —
statuses that only exist on `SubstanceSynonymMapping`; calling them on a
route/dosage-form/unit mapping fails closed with a structured 400 (model
`full_clean()` rejects the invalid status choice) rather than a raw
exception. `approve` requires `fda_data.approve` (VP only); `submit-review`/
`reject`/`return` require `fda_data.review` (Reviewer or VP). Approval is
blocked with a 400 if the acting user is already the mapping's `reviewer`
(segregation of duties). Every action emits an audit event
(`fda_data.mapping.submitted_for_review` / `.approved` / `.rejected` /
`.returned`).

Every action is additionally validated against a single authoritative
transition table (`fda_data/mapping_transitions.py`) before any mutation:
`approve` is only legal from `under_review` (never directly from
`proposed`/`returned`/`rejected`), `submit-review` only from
`proposed`/`returned`, `return` only from `under_review`, and
`approved`/`rejected` are terminal for every mapping type. An illegal
transition returns a structured 400, leaves the mapping's status
unchanged, and emits no audit event — see
[`HUMAN_REVIEW_PR5_REMEDIATION.md`](HUMAN_REVIEW_PR5_REMEDIATION.md)
(HR-01). Provenance fields are single-write: `reviewer`/`reviewed_at` are
set only by `submit-review`, `approved_by`/`approved_at` only by
`approve`, `rejected_by`/`rejected_at` only by `reject` (substance only —
falls back to `reviewer` for the three legacy mapping types, which have no
dedicated `rejected_by` field), `returned_by`/`returned_at` only by
`return` — no action overwrites another action's actor (HR-03).

### Creating a substance mapping proposal

`POST /api/regx/v1/fda-data/mappings/substances/proposals/` is the
production entry point for creating a new `PROPOSED`
`SubstanceSynonymMapping` — before this endpoint existed, the only way to
start the substance mapping-review workflow was direct Django shell/ORM
insertion, which is not a viable production path (HR-02). It requires
`fda_data.import` or `fda_data.review` (`CanProposeSubstanceMapping`);
accepts release public ID, raw/normalized ingredient name, an optional
proposed canonical `IIDIngredient` public ID / UNII / CAS, a source row
locator, `mapping_method`, and a reason/evidence field; always creates the
row as `PROPOSED` (the request body has no `status` field, so a
pre-approved row can never be created this way); and emits a
`fda_data.substance_mapping.candidate_created` audit event with safe
metadata (mapping/release public IDs, mapping method, actor — never the
full raw FDA row). The frontend "Propose substance mapping" action on
`frontend/src/app/fda-data/mappings/page.tsx` wraps this endpoint with a
confirmation dialog that states explicitly the proposal is not
auto-approved.

### Affected-record drill-down

`GET .../mappings/{public_id}/affected-records/` returns the paginated set
of FDA records (IID precedent rows, Orange Book products) whose raw value
matches this mapping's raw identity. Response fields are deliberately
narrow and safe: `record_public_id`, `dataset_type`, `release_public_id`,
`source_row_locator`, `raw_value`, `normalized_value`, `mapping_status`,
`calculability_status`, `blocked`, `reason_code`. Never present: storage
keys, filesystem paths, the full raw source row, or any internal numeric
ID. A nonexistent mapping returns a generic 404, matching the rest of the
mapping API.

`frontend/src/app/fda-data/mappings/page.tsx` consumes this API: type tabs
(Routes/Dosage forms/Units/Substance-UNII), every lifecycle action requires
an explicit confirmation-dialog click (never a bare button click), a
visible segregation-of-duties notice, and a link from each row's affected-
record count to `frontend/src/app/fda-data/mappings/[publicId]/page.tsx` —
the drill-down screen showing the mapping summary, FDA release provenance,
and the paginated affected-record table.
