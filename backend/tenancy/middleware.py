"""
TenantMiddleware: resolves tenant from request header X-Tenant-Slug
and stores it in thread-local context for the duration of the request.
"""

from django.http import JsonResponse

from .context import clear_current_tenant, set_current_tenant
from .models import Tenant, TenantMembership


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_current_tenant()

        slug = request.headers.get("X-Tenant-Slug")
        if slug and request.user and request.user.is_authenticated:
            try:
                tenant = Tenant.objects.get(slug=slug, status=Tenant.Status.ACTIVE)
                if TenantMembership.objects.filter(
                    tenant=tenant, user=request.user, is_active=True
                ).exists():
                    set_current_tenant(tenant)
                else:
                    return JsonResponse(
                        {"detail": "User is not a member of this tenant."}, status=403
                    )
            except Tenant.DoesNotExist:
                return JsonResponse({"detail": "Tenant not found."}, status=404)

        response = self.get_response(request)
        clear_current_tenant()
        return response
