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

## Key invariants

- Internal PKs (BIGINT) are never exposed in API responses. All public identifiers are UUID `public_id`.
- SQLite is prohibited. PostgreSQL is the only supported database.
- Session authentication uses secure HttpOnly cookies. Auth tokens are never stored in localStorage or sessionStorage.
- The tenant context is thread-local and fail-closed: `TenantScopeMissing` is raised if no tenant is set.
- `AIDatabase` and all legacy booking-demo modules are import-banned by import-linter contracts.
- Derived state is never client-settable. A dossier section's `readiness` is computed by `submission_dossiers.readiness` and is absent from every write serializer: a caller states `status`, the system states readiness.
- READY and COMPLETED are internal states only. Neither asserts regulatory compliance, agency approval, or submission acceptance.

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
documents ← never imports workflows (evidence deletion protection goes
            through DeletionProtectionRegistry, keeping it one-way)
```
