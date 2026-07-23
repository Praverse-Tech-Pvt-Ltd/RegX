# Template Governance

## Overview

The `templates_registry` domain is the canonical, independent home for regulatory
template content (ANDA/DMF/validation checklists, question banks, and similar
reference material) migrated out of the legacy monolith under controlled
review. It is a governance and migration platform, not a checklist-execution
engine — no scoring, IIG calculation, AI, or report generation exists here.

## What this domain does

- Imports approved, non-confidential legacy checklist/template content from
  controlled exports (JSON/CSV/DB extracts), never live legacy databases.
- Preserves original raw text/HTML/encoding/numbering alongside a
  non-destructive normalized value, with every normalization decision
  auditable.
- Detects duplicate/near-duplicate content deterministically and flags fuzzy
  matches for human review — it never auto-merges or deletes.
- Enforces an explicit approval lifecycle: imported content is inactive by
  default, and only an approved version can be activated by an authorized
  reviewer (VP/Tenant Admin), never automatically.
- Produces a per-batch reconciliation report (JSON/CSV) for governance
  review.

## What this domain explicitly does not do (out of scope this milestone)

- No checklist execution, scoring, or IIG calculation.
- No Orange Book, AI chat, or report generation (Word/PDF).
- No import of 483 observations, warning letters, inspection analytics, or
  any AIDatabase-sourced content — these are rejected at both the source
  package and individual record level (see `TEMPLATE_MIGRATION_TEST_STRATEGY.md`).
- No live coupling to legacy SQLite at runtime.

## Domain layout

| Module | Responsibility |
|---|---|
| `models.py` | 12 canonical models: template/version/section/item/option, source package/record, normalization mapping, duplicate candidate, migration batch/result, approval |
| `permissions.py` | Role → permission matrix (Doer/Reviewer/VP/Tenant Admin/Platform Support) |
| `lifecycle.py` | Transactional state machine: submit → review → approve/reject/return → activate → supersede/retire |
| `classification.py` | Fail-closed content exclusion guard (483/warning letter/AIDatabase/inspection analytics) |
| `normalization.py` | Non-destructive text/category normalization (HTML strip, mojibake repair, numbering split, unicode NFC) |
| `duplicates.py` | Deterministic duplicate-candidate detection |
| `adapters.py` | Legacy-shape → neutral record adapters (ANDA-like, DMF-like) |
| `importer.py` | Staged import pipeline orchestration |
| `reconciliation.py` | Per-batch JSON/CSV reconciliation report |
| `views.py` / `urls.py` / `serializers.py` | REST API under `/api/regx/v1/templates/` |

## Roles and responsibilities

| Role | Can | Cannot |
|---|---|---|
| Doer | inventory sources, register source packages, run migration batches | approve, activate, supersede, retire, export reconciliation |
| Reviewer | view raw content, review normalization/reconciliation, resolve duplicate candidates | activate (unless separately authorized), import |
| VP | approve, activate, supersede, retire, export reconciliation | inventory/import (not their function) |
| Tenant Admin | everything a Reviewer/Doer can, plus export reconciliation | approve, activate, supersede, retire — cannot bypass the approval chain |
| Platform Support | nothing content-related by default | — |

See `TEMPLATE_APPROVAL_LIFECYCLE.md` for the full state machine and
segregation-of-duties rule (an approver may never be the version's creator).

## Client inputs still required

- Real, approved regulatory template content (this milestone ships only
  synthetic fixtures and a read-only inventory of eligible legacy tables).
- A named regulatory sign-off process for who holds the VP/Tenant Admin role
  in production tenants.
- Decisions on which of the "requires review" legacy sources (CCTemplate,
  AppendixWhitePaper, IIG question bank) are in scope for a future migration
  batch.
