# IID Matching Engine

`iid_assessment/matching.py`, `find_iid_candidates(...)`. Deterministic
precedent matching. No fuzzy ingredient match ever becomes final
automatically. No substring route matching. No dosage-form family
substitution without an approved mapping. No automatic selection of the
"most favourable" IID value when multiple exact matches exist.

## Match sequence

1. **Ingredient identity** — `ingredient_public_id is None` → immediate
   `INGREDIENT_AMBIGUOUS` (`reason_code=INGREDIENT_UNRESOLVED`). This step
   only checks *presence* of an identity; a syntactically valid but
   nonexistent identity is not caught here (see step 4).
2. **Controlled route** — `controlled_route_id is None` → `ROUTE_MISMATCH`
   (`reason_code=ROUTE_UNMAPPED_OR_UNCONFIRMED`). The caller
   (`assess.run_preview`) only ever passes a route ID once it has been
   resolved through an approved `RouteMapping`/`ControlledRoute` lookup —
   there is no substring or partial match here or upstream.
3. **Controlled dosage form** — same pattern,
   `DOSAGE_FORM_MISMATCH` / `DOSAGE_FORM_UNMAPPED_OR_UNCONFIRMED`.
4. **Restrict to the selected release** — queries
   `IIDPrecedentRecord` filtered to exact
   `(ingredient, route_normalized, dosage_form_normalized, release)` with
   `release.status in (APPROVED, ACTIVE)` only. Zero rows (including the
   "nonexistent ingredient identity" case from step 1) →
   `NO_MATCHING_IID_PRECEDENT`.
5. **Multiple exact matches** — more than one row survives step 4 →
   `MULTIPLE_EXACT_MATCHES` with all candidates returned. The engine never
   picks one; a human/reviewer must select via
   `selected_precedent_record_public_id` on a subsequent call.
6. **Single-record calculability gate** — for exactly one surviving record:
   - `calculability_status == POTENCY_MISSING` → `POTENCY_UNAVAILABLE`.
   - `calculability_status in (INGREDIENT_AMBIGUOUS, REVIEW_REQUIRED)` →
     `REVIEW_REQUIRED`.
   - otherwise → `EXACT_MATCH`.

## `MatchCandidate` fields

`precedent_record_public_id`, `ingredient_name`, `route`, `dosage_form`,
`potency_amount`, `potency_unit`, `maximum_daily_exposure`, `mde_unit`,
`calculability_status`. **`potency_unit`/`mde_unit` are the controlled
unit's canonical `.code`** (e.g. `"milligram"`), not the display `.symbol`
(e.g. `"MG"`) — this is what feeds directly into
`unit_conversion.convert()` in `assess.py`, and `unit_conversion.py`'s
lookup tables are keyed by `.code`, not `.symbol`.

## Statuses (`MatchStatus`)

`EXACT_MATCH`, `MULTIPLE_EXACT_MATCHES`, `INGREDIENT_AMBIGUOUS`,
`ROUTE_MISMATCH`, `DOSAGE_FORM_MISMATCH`, `NO_MATCHING_IID_PRECEDENT`,
`POTENCY_UNAVAILABLE`, `MDE_UNAVAILABLE`, `UNIT_MISMATCH`,
`NOT_COMPARABLE`, `REVIEW_REQUIRED`.

`INGREDIENT_AMBIGUOUS` vs. `NO_MATCHING_IID_PRECEDENT`: the former means no
ingredient identity was supplied at all (genuinely ambiguous); the latter
means a real identity was supplied but no precedent record exists for it —
these are deliberately distinguishable and map to different
`PrecedentDecisionStatus` outcomes (`REVIEW_REQUIRED` vs. `NO_MATCH`, see
`IID_DECISION_STATUSES.md`).

See `iid_assessment/tests/test_matching_and_assess.py` for the full test
matrix, including the planted-and-detected violations (unconfirmed route,
multiple exact matches never auto-resolved).

## Substance/UNII synonym governance in `assess.run_preview`

`run_preview` accepts either an already-resolved `ingredient_public_id`
**or** a raw substance identity (`substance_name`/`substance_unii`/
`substance_cas`). When a raw identity is supplied, it is resolved through
`fda_data.substance_matching.resolve_substance_identity` (see
`FDA_TERMINOLOGY_MAPPING.md`) before `find_iid_candidates` ever runs:

- `EXACT_MATCH` — the confirmed ingredient's public_id and the selected
  mapping's public_id (`substance_mapping_public_id` on the returned
  `AssessmentPreview`) feed into the normal match sequence above.
- `MULTIPLE_CANDIDATES` or `REVIEW_REQUIRED` (proposed/under-review/
  returned mapping, or none at all) — the match is overridden to
  `MatchStatus.REVIEW_REQUIRED` with zero candidates. No IID lookup runs;
  no calculation happens.
- `INGREDIENT_AMBIGUOUS` (no identity supplied, or the only matching
  mapping was `REJECTED`) — overridden to `MatchStatus.INGREDIENT_AMBIGUOUS`,
  same fail-closed effect.

**Ingredient-name string equality alone never overrides an unresolved
identity state.** A raw name that happens to equal an `IIDIngredient`'s
`normalized_name` only resolves if no non-approved `SubstanceSynonymMapping`
already references that identity — the direct-`IIDIngredient` fallback in
`resolve_substance_identity` is disabled the moment *any*
proposed/rejected/under-review/returned mapping exists for it, precisely to
prevent this override.

### Snapshot preservation

`AssessmentSnapshot.iid_substance_mapping_public_id` freezes exactly which
`SubstanceSynonymMapping` version confirmed the ingredient identity used in
that assessment. Like every other snapshot field, it is immutable once
created (see `_BaseTerminologyMapping`-style `clean()` on
`AssessmentSnapshot`). Retiring or superseding the mapping afterward
(`is_current=False` + a new corrected row) never changes an
already-persisted snapshot's frozen reference — a later re-assessment
against the corrected mapping produces a distinct new snapshot instead.
