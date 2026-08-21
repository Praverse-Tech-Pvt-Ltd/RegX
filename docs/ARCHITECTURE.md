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

## Key invariants

- Internal PKs (BIGINT) are never exposed in API responses. All public identifiers are UUID `public_id`.
- SQLite is prohibited. PostgreSQL is the only supported database.
- Session authentication uses secure HttpOnly cookies. Auth tokens are never stored in localStorage or sessionStorage.
- The tenant context is thread-local and fail-closed: `TenantScopeMissing` is raised if no tenant is set.
- `AIDatabase` and all legacy booking-demo modules are import-banned by import-linter contracts.

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
documents ← never imports workflows (evidence deletion protection goes
            through DeletionProtectionRegistry, keeping it one-way)
```
