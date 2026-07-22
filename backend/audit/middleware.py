"""AuditMiddleware: attaches request metadata to thread-local for audit logging."""

import threading

_ctx = threading.local()


def get_audit_context() -> dict:
    return getattr(_ctx, "audit_ctx", {})


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _ctx.audit_ctx = {
            "ip_address": _get_ip(request),
            "user_agent": request.headers.get("User-Agent", "")[:512],
        }
        response = self.get_response(request)
        _ctx.audit_ctx = {}
        return response


def log_event(
    event_type: str,
    resource_type: str = "",
    resource_id: str = "",
    payload: dict | None = None,
    user=None,
    tenant=None,
):
    """Convenience helper to create an immutable AuditEvent."""
    from .models import AuditEvent

    ctx = get_audit_context()
    AuditEvent.objects.create(
        event_type=event_type,
        resource_type=resource_type,
        resource_id=str(resource_id),
        payload=payload or {},
        ip_address=ctx.get("ip_address"),
        actor_id=user.pk if user and user.is_authenticated else None,
        actor_email=user.email if user and user.is_authenticated else "",
        tenant_id=tenant.pk if tenant else None,
    )


def _get_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
