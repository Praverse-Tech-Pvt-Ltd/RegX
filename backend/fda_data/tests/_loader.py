"""A Doer who may be named as `--actor` by the loader commands in tests.

`import_fda_release` and `load_spl_terminology` require `--actor`, an existing
active user holding fda_data.import. Module-level test helpers have no access
to fixtures, so this creates that user on demand (inside the test database).
"""

LOADER_EMAIL = "loader-doer@example.com"


def loader_email() -> str:
    from authorization.models import MembershipRole, Role
    from identity.models import User
    from tenancy.models import Tenant, TenantMembership

    user, created = User.objects.get_or_create(
        email=LOADER_EMAIL, defaults={"full_name": "Loader (Doer)"}
    )
    if created:
        user.set_unusable_password()
        user.save()
        tenant, _ = Tenant.objects.get_or_create(
            slug="loader-tenant", defaults={"name": "Loader Tenant"}
        )
        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
        role, _ = Role.objects.get_or_create(
            tenant=tenant, name=Role.BuiltIn.DOER, defaults={"is_system": True}
        )
        MembershipRole.objects.get_or_create(membership=membership, role=role)
    return LOADER_EMAIL
