# Proposal: generated API types and a mock-contract check (not built)

> **Why:** PR #122 found two places where tests passed on **response shapes nobody's API sends**:
> - the IID preview's `unit_conversion` was mocked as `{status: "OK"}`, while the backend sends `{ok, converted_value, …}`;
> - the tenants list was mocked as a paginated `{results: [...]}`, while the backend sends a plain array.
>
> The page was wrong, and green tests hid it. This proposes how to stop tests passing on invented shapes. **Proposal only; nothing here is built.**

Measured on `regx-main` `47021f7` (2026-11-17, `manage.py spectacular`; raw output in `D:/Praverse/session-work/2026-11-17/api-types/`).

## What the schema covers today

| Measure | Value |
|---|---|
| API operations in the drf-spectacular schema | 276 (224 paths) |
| …with a typed 2xx JSON response | **92 (33%)** |
| drf-spectacular "unable to guess serializer" errors | 154 |
| Named component schemas | 105 |
| Hand-written frontend types in `frontend/src/lib/api.ts` | 146 exported types/interfaces, 3,656 lines |
| Test files that mock API responses (vitest + Playwright) | 42 |

- **Where untyped operations cluster:** `iig-checklists` 40, `fda-data` 24, `templates` 13, `dossier-sections` 12, `formulations` 11, then `documents`, `regulatory-cases` and `submission-dossiers` at 10 each.
- **The two shapes that were invented have no schema at all:** `POST /iid-assessments/preview/` and `GET /tenants/` both document `200` with an **empty** response schema. Many views are `APIView`/`@api_view` functions returning hand-built dicts, which drf-spectacular cannot see into.
- **So generating TypeScript from today's schema would not have caught either bug.** The backend must describe its responses first.

## Proposal

### 1. Make the schema tell the truth (backend)
- **Describe each response:** add `@extend_schema(responses=…)` with real response serializers to the untyped operations, highest risk first:
  - the IID preview and snapshot;
  - IIG checklist executions, outcomes and gap analysis;
  - tenants, auth, documents.
- **Model nested results:** structured results such as `calculations.unit_conversion` (`ConversionResult`), `calculations.potency_comparison` (`ComparisonResult`) and the calculation engine's `CalculationResult` get their own schema components, not a free-form object.
- **Prove the schema matches reality:** a backend **conformance test** calls each covered endpoint in the test suite and validates the real response against the generated schema (OpenAPI → JSON Schema, validated with `jsonschema`).
- **Fail CI** when a covered endpoint has no 2xx schema. The list of covered endpoints grows with each slice.

### 2. Generate the frontend types (frontend)
- **Tooling:** `openapi-typescript` (dev dependency) generates `frontend/src/lib/api/schema.d.ts` from the schema the backend job already builds and validates (`spectacular --validate`).
- **Drift check:** CI regenerates the file and fails on any diff.
- **Wiring:** `api.ts` keeps its functions but takes response types from the generated file, one endpoint at a time, retiring each hand-written interface as it is replaced.
- **Remove loose types:** `Record<string, unknown>` in places such as `AssessmentPreview.calculations` goes away, so a fixture typed against the real shape fails `type-check` when it invents a field.

### 3. Check every mock against the schema (tests)
- **Vitest:** a helper, for example `respond("POST /api/regx/v1/iid-assessments/preview/", 200, body)`, validates `body` against that operation's response schema (ajv) and **fails the test** when it doesn't conform. Fixtures in `tests/unit/fixtures.ts` are typed with the generated types.
- **Playwright:** the same validation wraps `route.fulfill`, through one `fulfillJson(route, operation, status, body)` helper.
- **Enforcement:** a repository test fails on a new raw `route.fulfill({ body: JSON.stringify(...) })` for `/api/regx/v1/` outside the helper. Existing call sites are migrated file by file, with a shrinking allow-list.
- **Scope:** only covered endpoints are checked. An uncovered endpoint is reported, not silently passed.

## Size estimate (one experienced developer)

| Slice | Size |
|---|---|
| Tooling: openapi-typescript, generated file, CI drift check | S (≤1 day) |
| Response schemas + conformance tests for the ~30 highest-risk operations (IID, checklists, tenants, auth, documents) | M (2–3 days) |
| Mock validation helpers (vitest + Playwright) + enforcement test + migrate the IID, tenants and documents mocks | M (2–3 days) |
| **First useful slice (the three rows above)** | **about 1 week** |
| Remaining ~150 untyped operations, plus migrating the remaining mocks of the 42 test files | L (1–2 weeks), can run gradually |

**Risks:**
- **Adding response serializers to `APIView`s is not a pure no-op:** a serializer that drops or renames a field changes the API. The conformance test is what keeps this honest.
- **Some existing mocks will fail validation the day it lands.** That is the point: each one is a test that may have been passing on an invented shape, and each needs a reviewed fix.
