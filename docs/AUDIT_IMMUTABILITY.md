# Audit Immutability

`AuditEvent` rows are append-only and enforced at two layers:

## ORM layer

`AuditEvent.save()` raises `PermissionError` if `self.pk is not None`.  
`AuditEvent.delete()` always raises `PermissionError`.

## Database layer

`audit/migrations/0001_initial.py` installs two PostgreSQL triggers:

- `no_update_audit_event` — `BEFORE UPDATE FOR EACH ROW` → raises exception
- `no_delete_audit_event` — `BEFORE DELETE FOR EACH ROW` → raises exception

These triggers fire even if the ORM guard is bypassed (e.g. raw SQL, psql session).

## Writing audit events

Use `audit.middleware.log_event(event_type, ...)` from any domain.
