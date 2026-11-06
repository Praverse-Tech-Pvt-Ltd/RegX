"""Migrations 0003 + 0004: tenant-scoped copies of system roles are merged, then forbidden (§11 #25).

The "with duplicates" cases must run at migration 0002, because the constraint
added by 0004 makes such rows impossible afterwards. They use Django's
MigrationExecutor in a transactional test and migrate forward again at the end.
"""

import io

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from authorization.role_cleanup import RoleCleanupRefused, merge_tenant_scoped_system_roles

BEFORE = [("authorization", "0002_initial")]
AFTER = [("authorization", "0004_role_system_has_no_tenant")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def _seed_platform_roles(apps):
    """The post_migrate seed creates these in a real database; recreate them at 0002."""
    Role = apps.get_model("authorization", "Role")
    for name in ("doer", "reviewer", "vp", "tenant_admin", "platform_support"):
        Role.objects.get_or_create(tenant=None, name=name, defaults={"is_system": True})


def _member(apps, email, tenant):
    User = apps.get_model("identity", "User")
    TenantMembership = apps.get_model("tenancy", "TenantMembership")
    user = User.objects.create(email=email, password="!")
    return TenantMembership.objects.create(tenant=tenant, user=user)


@pytest.fixture
def at_0002(transactional_db):
    apps = _migrate(BEFORE)
    _seed_platform_roles(apps)
    yield apps
    _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
class TestMigrationWithDuplicates:
    def test_assignments_move_to_platform_roles_and_duplicates_go(self, at_0002):
        apps = at_0002
        Tenant = apps.get_model("tenancy", "Tenant")
        Role = apps.get_model("authorization", "Role")
        MembershipRole = apps.get_model("authorization", "MembershipRole")
        tenant = Tenant.objects.create(name="Dup Tenant", slug="dup-tenant")
        dup_doer = Role.objects.create(tenant=tenant, name="doer", is_system=True)
        dup_vp = Role.objects.create(tenant=tenant, name="vp", is_system=True)
        only_dup = _member(apps, "only-dup@roles.test", tenant)
        both = _member(apps, "both@roles.test", tenant)
        MembershipRole.objects.create(membership=only_dup, role=dup_doer)
        MembershipRole.objects.create(membership=both, role=dup_vp)
        platform_vp = Role.objects.get(tenant=None, name="vp")
        MembershipRole.objects.create(membership=both, role=platform_vp)

        apps = _migrate(AFTER)
        Role = apps.get_model("authorization", "Role")
        MembershipRole = apps.get_model("authorization", "MembershipRole")
        assert not Role.objects.filter(is_system=True, tenant__isnull=False).exists()
        assert not Role.objects.filter(id__in=[dup_doer.id, dup_vp.id]).exists()
        moved = MembershipRole.objects.get(membership_id=only_dup.id)
        assert moved.role.tenant_id is None and moved.role.name == "doer"
        kept = MembershipRole.objects.filter(membership_id=both.id)
        assert [(r.role.name, r.role.tenant_id) for r in kept] == [("vp", None)]

    def test_refuses_and_changes_nothing_without_a_platform_counterpart(self, at_0002):
        apps = at_0002
        Tenant = apps.get_model("tenancy", "Tenant")
        Role = apps.get_model("authorization", "Role")
        MembershipRole = apps.get_model("authorization", "MembershipRole")
        tenant = Tenant.objects.create(name="Odd Tenant", slug="odd-tenant")
        odd = Role.objects.create(tenant=tenant, name="auditor", is_system=True)
        good_dup = Role.objects.create(tenant=tenant, name="doer", is_system=True)
        MembershipRole.objects.create(membership=_member(apps, "odd@roles.test", tenant), role=odd)

        with pytest.raises(RoleCleanupRefused, match="no platform-wide system role"):
            _migrate(AFTER)
        # Nothing changed, the good duplicate included (all checks run first).
        assert Role.objects.filter(id__in=[odd.id, good_dup.id]).count() == 2
        assert MembershipRole.objects.filter(role=odd).count() == 1
        # Clean up so the fixture can migrate forward.
        MembershipRole.objects.filter(role=odd).delete()
        Role.objects.filter(id__in=[odd.id, good_dup.id]).delete()

    def test_refuses_when_the_duplicate_grants_more_than_the_platform_role(self, at_0002):
        apps = at_0002
        Tenant = apps.get_model("tenancy", "Tenant")
        Role = apps.get_model("authorization", "Role")
        Permission = apps.get_model("authorization", "Permission")
        RolePermission = apps.get_model("authorization", "RolePermission")
        MembershipRole = apps.get_model("authorization", "MembershipRole")
        tenant = Tenant.objects.create(name="Perm Tenant", slug="perm-tenant")
        dup = Role.objects.create(tenant=tenant, name="doer", is_system=True)
        extra = Permission.objects.create(codename="test:only-on-the-duplicate")
        RolePermission.objects.create(role=dup, permission=extra)

        with pytest.raises(RoleCleanupRefused, match="would change access"):
            merge_tenant_scoped_system_roles(
                Role, MembershipRole, RolePermission, log=lambda m: None
            )
        assert Role.objects.filter(id=dup.id).exists()
        RolePermission.objects.filter(role=dup).delete()
        dup.delete()
        extra.delete()


@pytest.mark.django_db(transaction=True)
class TestMigrationWithoutDuplicates:
    def test_is_a_no_op(self, at_0002):
        apps = at_0002
        Role = apps.get_model("authorization", "Role")
        MembershipRole = apps.get_model("authorization", "MembershipRole")
        RolePermission = apps.get_model("authorization", "RolePermission")
        before = sorted(Role.objects.values_list("id", "name", "tenant_id"))
        log = []
        result = merge_tenant_scoped_system_roles(
            Role, MembershipRole, RolePermission, log=log.append
        )
        assert result == {"duplicates": 0, "moved": 0, "dropped_redundant": 0}
        assert "nothing to merge" in log[0]
        apps = _migrate(AFTER)
        Role = apps.get_model("authorization", "Role")
        assert sorted(Role.objects.values_list("id", "name", "tenant_id")) == before


@pytest.mark.django_db
class TestConstraint:
    def test_system_role_with_a_tenant_is_refused_by_the_database(self, tenant):
        from authorization.models import Role

        with pytest.raises(IntegrityError), transaction.atomic():
            Role.objects.create(tenant=tenant, name="vp", is_system=True)

    def test_a_tenant_may_still_have_its_own_non_system_role(self, tenant):
        from authorization.models import Role

        role = Role.objects.create(tenant=tenant, name="vp", is_system=False)
        assert role.pk

    def test_platform_system_roles_are_unaffected(self):
        from authorization.models import Role

        names = set(Role.objects.filter(is_system=True).values_list("name", flat=True))
        assert {"doer", "reviewer", "vp", "tenant_admin", "platform_support"} <= names
        assert not Role.objects.filter(is_system=True, tenant__isnull=False).exists()


@pytest.mark.django_db
class TestDemoSeedUsesPlatformRoles:
    def test_seed_binds_platform_roles_even_when_a_tenant_role_shares_the_name(self, tenant):
        """Before the fix the seed looked roles up by name only and failed with
        MultipleObjectsReturned when a tenant role shared a built-in name."""
        from authorization.models import MembershipRole, Role

        Role.objects.create(tenant=tenant, name="doer", is_system=False)
        call_command("seed_regx_demo", stdout=io.StringIO())
        bound = MembershipRole.objects.filter(membership__tenant__slug="demo")
        assert bound.exists()
        assert all(mr.role.tenant_id is None and mr.role.is_system for mr in bound)
