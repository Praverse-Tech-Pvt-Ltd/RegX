"""
Seed built-in system roles and permissions on app startup.
Idempotent: safe to call multiple times.
"""

from django.db.models.signals import post_migrate
from django.dispatch import receiver


SYSTEM_ROLES = [
    ("doer", "Initiates and submits workflow items."),
    ("reviewer", "Reviews and approves submitted items."),
    ("vp", "Final approval authority."),
    ("tenant_admin", "Manages tenant membership and settings."),
    ("platform_support", "Cross-tenant read-only support access."),
]

BUILTIN_PERMISSIONS = [
    ("workflow:submit", "Submit a workflow item for review."),
    ("workflow:approve", "Approve a workflow item."),
    ("workflow:reject", "Reject a workflow item."),
    ("tenant:manage_members", "Add or remove tenant members."),
    ("audit:view", "View audit trail entries."),
]

ROLE_PERMISSIONS = {
    "doer": ["workflow:submit"],
    "reviewer": ["workflow:submit", "workflow:approve", "workflow:reject", "audit:view"],
    "vp": ["workflow:submit", "workflow:approve", "workflow:reject", "audit:view"],
    "tenant_admin": ["tenant:manage_members", "audit:view"],
    "platform_support": ["audit:view"],
}


@receiver(post_migrate)
def seed_roles_and_permissions(sender, **kwargs):
    if sender.name != "authorization":
        return

    from .models import Permission, Role, RolePermission

    for codename, desc in BUILTIN_PERMISSIONS:
        Permission.objects.get_or_create(codename=codename, defaults={"description": desc})

    for name, desc in SYSTEM_ROLES:
        role, _ = Role.objects.get_or_create(
            tenant=None,
            name=name,
            defaults={"is_system": True, "description": desc},
        )
        for perm_code in ROLE_PERMISSIONS.get(name, []):
            perm = Permission.objects.get(codename=perm_code)
            RolePermission.objects.get_or_create(role=role, permission=perm)
