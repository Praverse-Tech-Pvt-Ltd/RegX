# Tenancy

## Model

A `Tenant` is an isolated organisational unit. A `User` may belong to multiple tenants via `TenantMembership`. There is no direct tenant FK on the User model.

## Request-scoped context

`TenantMiddleware` resolves the current tenant from the `X-Tenant-Slug` request header and stores it in thread-local state for the duration of the request.

If `current_tenant()` is called without a tenant set, `TenantScopeMissing` is raised (fail-closed).

## Tenant status

| Status | Effect |
|---|---|
| `active` | Normal operation |
| `suspended` | Login blocked |
| `deprovisioned` | Archived; no access |
