# REGX Architecture

## Overview

REGX is a multi-tenant regulatory workflow management platform.

```
frontend (Next.js)  →  backend (Django + DRF)  →  PostgreSQL
                                                 →  Redis (Celery broker)
```

## Domain modules

| Module | Responsibility |
|---|---|
| `common` | Base models, exceptions, health endpoints |
| `identity` | User, MFA, recovery codes |
| `tenancy` | Tenant, TenantMembership, tenant context |
| `authorization` | Roles, permissions, RBAC |
| `audit` | Immutable audit trail |
| `workflows` | Generic tenant-scoped workflow engine: state machine, append-only transition history, assignment, governed document evidence ([`WORKFLOW_ENGINE.md`](WORKFLOW_ENGINE.md), [`WORKFLOW_EVIDENCE.md`](WORKFLOW_EVIDENCE.md)) |
| `regulatory_cases` | Case workspace composing workflows, documents and checklists into one governed folder. Owns no content and duplicates no engine ([`REGULATORY_CASES.md`](REGULATORY_CASES.md)) |
| `submission_dossiers` | Ordered, nested section outline inside a case, with blockers and derived internal readiness. Owns structure only; no content, no approval engine ([`SUBMISSION_DOSSIERS.md`](SUBMISSION_DOSSIERS.md)) |
| `dossier_blueprints` | Reusable, versioned tenant-controlled dossier outlines, and the governed record of which dossier was stamped from which version. Defines structure; owns no execution ([`DOSSIER_BLUEPRINTS.md`](DOSSIER_BLUEPRINTS.md)) |
| `dossier_upgrades` | Blueprint-to-blueprint change impact, and the only sanctioned path for moving an existing dossier onto a newer version. Proposes; never applies on its own ([`DOSSIER_UPGRADES.md`](DOSSIER_UPGRADES.md)) |
| `submission_operations` | Read-only operational view across every governed domain. Owns no data, stores nothing and decides nothing ([`SUBMISSION_OPERATIONS_DASHBOARD.md`](SUBMISSION_OPERATIONS_DASHBOARD.md)) |
| `submission_packages` | Controlled assembly of exact document versions into an internal package, with a frozen manifest and a ZIP export. Binds versions, never documents ([`SUBMISSION_PACKAGES.md`](SUBMISSION_PACKAGES.md)) |

## Key invariants

- Internal PKs (BIGINT) are never exposed in API responses. All public identifiers are UUID `public_id`.
- SQLite is prohibited. PostgreSQL is the only supported database.
- Session authentication uses secure HttpOnly cookies. Auth tokens are never stored in localStorage or sessionStorage.
- The tenant context is thread-local and fail-closed: `TenantScopeMissing` is raised if no tenant is set.
- `AIDatabase` and all legacy booking-demo modules are import-banned by import-linter contracts.
- Derived state is never client-settable. A dossier section's `readiness` is computed by `submission_dossiers.readiness` and is absent from every write serializer: a caller states `status`, the system states readiness.
- READY and COMPLETED are internal states only. Neither asserts regulatory compliance, agency approval, or submission acceptance.
- A blueprint version ACTIVE means only that it is available for creating dossiers inside RegX. It is not a regulatory, QA or agency approval, and there is deliberately no APPROVED state in `dossier_blueprints`.
- An instantiated dossier is a snapshot, never a live view of its blueprint. Publishing a later blueprint version cannot change a dossier already built from an earlier one.
- A dossier moves onto a newer blueprint version only when a person generates a plan, reviews it, and applies it. Generating is not applying, accepting an item is not applying, and a READY plan is an internal review state, not an approval of any kind.
- An upgrade never writes a section row itself. Every dossier mutation it performs goes through `submission_dossiers.services`, so the Milestone 9 sanctioned window and its triggers apply exactly as they do to a hand-edited dossier.
- A plan carries a structural fingerprint of the dossier it described. Apply recomputes it and fails closed: a plan that cannot prove the dossier is unchanged is never applied.
- Provenance is append-only across versions. An upgrade records a new `DossierUpgradeApplication`; it never rewrites the `BlueprintInstantiation` that says how the dossier was originally created.
- The operations dashboard is a read model with no second source of truth: no copied readiness, no cached counts, no stored dashboard state, no model and no migration. Every number is counted at request time from the table that owns it.
- A dashboard permission is a door, not a key. `submission_operations.view` grants only the right to ask; each module stays behind its own view permission, checked independently per request.
- On the dashboard, `0` and `null` are different answers: `0` means there are none, `null` means the caller is not entitled to know. A restricted dimension is never rendered as a zero.
- A submission package binds to an exact `DocumentVersion`, never to a `Document`. Uploading a new version of a cited document changes nothing about any package that already cites an earlier one; the guarantee is a foreign key, not a convention.
- FROZEN on a package means its manifest can no longer change. It is not QA approval, regulatory approval or agency acceptance, there is no unfreeze, and changing a frozen package means cloning it into a new draft.
- A package export is all or nothing. A caller who cannot retrieve every cited document is refused the whole archive rather than handed a shorter one, because a ZIP silently missing files looks complete to whoever receives it.

## Import dependency rules

```
regx (settings/urls) → any domain
common ← no domain imports
identity ← no tenancy/authorization imports
tenancy → identity (via string FK), common
authorization → tenancy, identity, common
audit → no domain imports (self-contained)
workflows → tenancy, identity, authorization, audit, documents, common
regulatory_cases → tenancy, identity, authorization, audit, documents,
                   workflows, iig_checklist, common
                   Depends on the modules it composes and is depended on by
                   none of them: the arrow only ever points this way, so a case
                   can be removed without touching any engine.
submission_dossiers → regulatory_cases, tenancy, identity, authorization,
                   audit, documents, workflows, iig_checklist, common
                   The outermost composition layer. It depends on the case it
                   lives in and on the engines it links to; nothing depends on
                   it, so the whole app can be removed without touching a case
                   or an engine.
dossier_blueprints → submission_dossiers, regulatory_cases, tenancy,
                   identity, authorization, audit, common
                   Above submission_dossiers. It reads
                   a case, writes dossiers and sections, and is depended on by
                   nothing. Deliberately NOT built inside templates_registry:
                   that app's APPROVED lifecycle belongs to the regulatory
                   content gate, and a tenant's dossier outline must not borrow
                   the word. See DOSSIER_BLUEPRINTS.md section 4.
dossier_upgrades → dossier_blueprints, submission_dossiers, regulatory_cases,
                   tenancy, identity, authorization, audit, common
                   (+ documents, in tests only — a linked document is one of the
                   runtime signals that blocks a retirement, so a test has to
                   create one)
                   Now the outermost layer, above both. It is the only module
                   that reads a blueprint and writes an existing dossier in the
                   same operation, and nothing depends on it, so the whole app
                   can be removed and every dossier and blueprint still stands.
                   Neither dossier_blueprints nor submission_dossiers may import
                   it: a section knows nothing about being upgraded.
submission_operations → dossier_upgrades, dossier_blueprints,
                   submission_dossiers, regulatory_cases, workflows, documents,
                   iig_checklist, audit, tenancy, identity, authorization,
                   common
                   A read model, and now the outermost layer of all. It depends
                   on every domain it aggregates and NOTHING may depend on it:
                   the moment a domain imports the dashboard, the dashboard has
                   become a source of truth rather than a view of one, and
                   deleting it stops being free. Enforced by the
                   `nothing-depends-on-submission-operations` contract.
submission_packages → documents, submission_dossiers, regulatory_cases,
                   tenancy, identity, authorization, audit, common
                   Composes the document platform and a case. It stores no file
                   bytes: the document platform stays the sole owner of stored
                   content, and a package holds exact references plus an
                   immutable manifest. Nothing depends on it, so the whole app
                   can be removed and every document and case still stands.
                   `documents` never imports it -- the deletion-protection
                   registry keeps that arrow one-way, exactly as it does for
                   workflow evidence.
documents ← never imports workflows (evidence deletion protection goes
            through DeletionProtectionRegistry, keeping it one-way)
```
