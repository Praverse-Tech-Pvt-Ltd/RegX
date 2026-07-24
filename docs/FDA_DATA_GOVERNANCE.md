# FDA Data Governance

## Overview

The `fda_data` domain is the platform-level, tenant-independent home for
official FDA reference data: Orange Book product/application records, the
FDA Inactive Ingredient Database (IID), and controlled route/dosage-form/unit
terminology. It is a governed reference-data platform, not a formulation or
checklist engine — no scoring, IIG calculation, or AI exists here.

Only official FDA sources are treated as source of truth (Orange Book,
FDA IID, FDA/SPL terminology, FDA substance-registration data). Scraped
commercial websites are never a source of truth.

## What this domain does

- Registers and stages controlled imports of FDA source files (Orange Book
  products/discontinued/patents/exclusivity, FDA IID, substance identifiers,
  route/dosage-form terminology) with checksum-based idempotency.
- Records the source's actual publication/release date rather than assuming
  a fixed calendar cadence — there is no hard-coded sync schedule.
- Extracts, validates, normalizes, and classifies rows through an explicit
  staged pipeline, persisting a per-row `FdaImportRowResult` for every
  outcome (imported, review-required, rejected).
- Enforces controlled-vocabulary mapping: raw source route/dosage-form/unit
  strings only resolve to a `ControlledRoute`/`ControlledDosageForm`/
  `ControlledUnit` via a reviewer-approved `*Mapping` row. No fuzzy mapping
  is ever auto-approved.
- Enforces an explicit release lifecycle (registered → staged → validated →
  under_review → approved → active → superseded, or rejected at any staging
  point) with segregation of duties: the user who imports cannot approve or
  activate the same release.
- Guarantees exactly one ACTIVE release per `dataset_type` at a time (DB
  constraint + app-level lock), and never silently replaces an active
  release — superseding always goes through an explicit action.
- Produces per-release JSON/CSV reconciliation reports with CSV
  formula-injection neutralization on every exported cell.

## What this domain explicitly does not do

- No auto-activation of any release, ever — activation is always an
  explicit, permissioned action.
- No import of legacy IIG answer data, AIDatabase content, or 483
  observations (blocked by `pyproject.toml` import-linter contracts and by
  using only synthetic FDA-shaped fixtures in tests).
- No formulation, product-development, or IID-matching logic — that is
  `formulations` and `iid_assessment` (see those domains' docs). `fda_data`
  is forbidden by import-linter contract from importing either.
- No representation of an IID potency/MDE value as a recommended dose,
  formulation target, or automatic regulatory acceptance — `fda_data` only
  stores the FDA-published precedent value; interpretation is entirely
  `iid_assessment`'s responsibility, and even there decisions never assert
  safety or approval (see `IID_DECISION_STATUSES.md`).

## Domain layout

| Module | Responsibility |
|---|---|
| `models.py` | `FDADataSourceRelease`, `ControlledRoute`/`ControlledDosageForm`/`ControlledUnit`, `RouteMapping`/`DosageFormMapping`/`UnitMapping`, `OrangeBookApplication`/`OrangeBookProduct`/`OrangeBookProductIngredient`, `IIDIngredient`/`IIDPrecedentRecord`, `FdaImportRowResult` |
| `checksums.py` | SHA-256 source-file checksum computation for idempotency/dedup |
| `storage.py` | Thin wrapper over `documents.storage` for platform-owned (non-tenant) source files |
| `permissions.py` | Role → permission matrix (register/import/review/approve/activate/view_raw/export_reconciliation) |
| `lifecycle.py` | Transactional release state machine with `select_for_update()` locking and segregation of duties |
| `terminology.py` | Controlled-vocabulary lookup/mapping resolution (code/symbol/alias, reviewer-approved only) |
| `adapters.py` | Legacy-shape source rows → neutral internal row adapters (Orange Book, FDA IID) |
| `importer.py` | Staged import pipeline orchestration (register → extract → validate → normalize → classify → persist) |
| `audit_events.py` | Structured audit event emission for every governance action |
| `views.py` / `urls.py` / `serializers.py` | REST API under `/api/regx/v1/fda-data/` |

## Roles and responsibilities

| Role | Can | Cannot |
|---|---|---|
| Doer | register releases, import rows | approve, activate, view raw source metadata, export reconciliation |
| Reviewer | view raw metadata, review, export reconciliation | approve, activate |
| VP | approve, activate, review, export reconciliation, view raw | register/import (not their function) |
| Tenant Admin | view (read-only) | anything that mutates FDA master data — tenant users can never edit platform FDA terminology |
| Platform Support | metadata-only view | any raw tenant or FDA content |

See `ORANGE_BOOK_INGESTION.md`, `FDA_IID_INGESTION.md`, and
`FDA_TERMINOLOGY_MAPPING.md` for the ingestion and mapping details, and
`IID_FOUNDATION_TEST_STRATEGY.md` for how this domain is tested.
