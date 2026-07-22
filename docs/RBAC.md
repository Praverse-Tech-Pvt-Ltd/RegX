# RBAC

## Built-in roles

| Role | Key permissions |
|---|---|
| `doer` | `workflow:submit` |
| `reviewer` | `workflow:submit`, `workflow:approve`, `workflow:reject`, `audit:view` |
| `vp` | All reviewer permissions |
| `tenant_admin` | `tenant:manage_members`, `audit:view` |
| `platform_support` | `audit:view` (read-only, cross-tenant) |

## Assignment

Roles are assigned to users per tenant via `MembershipRole`, which links a `TenantMembership` to a `Role`.

## Seeding

Built-in roles and permissions are seeded idempotently via the `post_migrate` signal in `authorization.seed`.
