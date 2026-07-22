"""
Thread-local tenant context.

Every request that enters a tenant-scoped endpoint must call `set_current_tenant`.
Querysets that call `current_tenant()` will raise TenantScopeMissing (fail-closed)
if the context was never set.
"""

import threading

from common.exceptions import TenantScopeMissing

_ctx = threading.local()


def set_current_tenant(tenant) -> None:
    _ctx.tenant = tenant


def clear_current_tenant() -> None:
    _ctx.tenant = None


def current_tenant():
    tenant = getattr(_ctx, "tenant", None)
    if tenant is None:
        raise TenantScopeMissing(
            "Tenant context is required but was not set. "
            "Ensure TenantMiddleware is installed and the request carries a valid tenant."
        )
    return tenant
