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
        if slug:
            try:
                tenant = Tenant.objects.get(slug=slug, status=Tenant.Status.ACTIVE)
            except Tenant.DoesNotExist:
                return JsonResponse({"detail": "Tenant not found."}, status=404)

            # If Django auth has already resolved a session user, check membership now.
            # DRF force_authenticate / token auth run inside the view, so we can't
            # check membership for requests that authenticate at the view layer;
            # permission classes enforce tenant membership for those requests.
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                if not TenantMembership.objects.filter(
                    tenant=tenant, user=user, is_active=True
                ).exists():
                    return JsonResponse(
                        {"detail": "User is not a member of this tenant."}, status=403
                    )
            set_current_tenant(tenant)

        response = self.get_response(request)
        clear_current_tenant()
        return response
