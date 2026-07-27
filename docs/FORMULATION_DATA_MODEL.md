# Formulation Data Model

## Overview

`formulations` is the tenant-owned home for a user's proposed product and
formulation data. Unlike `fda_data`, every row here is scoped to a tenant
(`TenantScopedManager.for_tenant()` / `RelatedTenantScopedManager` /
`FormulationVersionRelatedManager`), and no tenant can see another tenant's
records. This domain holds only what the user supplies — it never contains
FDA-populated values itself (those live in `fda_data` and are only read,
never copied in as if user-authored).

## Models

### `ProductDevelopmentRecord`

The proposed product itself: `product_code` (unique per tenant),
`proposed_product_name`, `active_ingredient`, `is_combination_product`,
`release_type`, `route`, `dosage_form`, proposed strength, and
`regulatory_market_context` — all user-entered.

**Reference-product selection** (`selected_ob_application_number`,
`selected_ob_product_number`, `selected_ob_product_public_id`,
`selected_ob_release_public_id`, `selection_timestamp`, `selecting_user`,
`selection_justification`) is deliberately **not** a foreign key to
`fda_data.OrangeBookProduct`. It is a plain-value snapshot of exactly what
was selected and when. This is intentional: if the underlying FDA release is
later superseded or that product row changes, the product's historical
selection must never silently change with it. `has_selected_reference_product`
is `False` until an explicit `select-reference` action runs — there is no
default or auto-selected reference product.

### `FormulationVersion`

One versioned formulation attempt for a product:
`total_dosage_unit_weight` (> 0, DB `CheckConstraint`),
`total_dosage_unit_weight_unit`, `batch_size`, `overage_percentage`,
`maximum_dosage_units_per_day`, `dosing_basis`, `rationale`. `version_number`
is unique per product (`UniqueConstraint`) — versions are never renumbered
or reused.

**Immutability**: once a version reaches `APPROVED`, `SUPERSEDED`, or
`RETIRED` (`IMMUTABLE_FORMULATION_STATUSES`), `clean()` compares every
non-exempt field against the DB row and raises `ValidationError` if anything
but `status`/`updated_at` changed. A correction after approval always means
creating a new version, never editing the approved one.

### `FormulationComponent`

One ingredient line within a version: `component_type` (active/inactive),
`ingredient_name`, optional `resolved_ingredient_public_id`/`resolved_unii`
(set once matched against `fda_data.IIDIngredient` — never guessed),
`quantity_per_dosage_unit` (> 0, DB constraint), `quantity_unit`,
`percentage_w_w_snapshot` (system-calculated, see
`IID_CALCULATION_RULES.md`), batch-level quantity/overage fields, and
justification/specification references.

### `DosingRegimen`

`units_per_administration`, `administrations_per_day`,
`maximum_units_per_day` (> 0, DB constraint), `patient_population`, `basis`,
`source_justification` — all user-supplied dosing assumptions that feed the
daily-exposure calculation.

## Field provenance

| Provenance | Fields |
|---|---|
| User-entered | everything on `ProductDevelopmentRecord` except selection metadata; all of `FormulationVersion`, `FormulationComponent` (except `percentage_w_w_snapshot`), `DosingRegimen` |
| Reviewer-entered | `selection_justification`, `justification` (component), lifecycle review notes |
| System-calculated | `FormulationComponent.percentage_w_w_snapshot`; everything produced by `iid_assessment` (never stored back onto these models — see `AssessmentSnapshot` in `IID_CALCULATION_RULES.md`) |
| FDA source (read-only reference, never copied as user input) | Orange Book / IID values displayed for comparison, always via `fda_data` read endpoints |

## Tenant isolation

Every queryset here goes through `.for_tenant(tenant)`; the API layer
resolves `tenant` once via `tenancy.context.current_tenant()` and never
accepts a tenant identifier from the request body. Cross-tenant access to a
product, version, component, or dosing regimen returns a generic 404 (see
`formulations/tests/test_models_and_api.py::TestTenantIsolationApi` and
`TestFormulationVersionComponentApi`).

## Decimal discipline

Every quantity field is a `DecimalField`; nothing here is ever a `float`.
See `IID_CALCULATION_RULES.md` and `UNIT_CONVERSION_ENGINE.md` for how these
values flow into calculations without ever crossing into floating point.

## API-level validation

Invalid quantities (negative/zero `quantity_per_dosage_unit`, zero
`total_dosage_unit_weight`, zero `administrations_per_day`/
`maximum_units_per_day`) are rejected by serializer-level `validate_*`
methods before they ever reach the database, returning a clean structured
400 — never a raw `IntegrityError`. The DB `CheckConstraint`s remain as a
defense-in-depth backstop (see `formulations/views.py`'s
`_integrity_error_as_validation_error` context manager, which converts any
constraint violation that slips past serializer validation into the same
structured 400 response instead of a 500).
