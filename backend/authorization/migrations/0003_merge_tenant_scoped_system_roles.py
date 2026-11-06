"""Merge tenant-scoped copies of the system roles into the platform-wide ones (§11 #25).

`authorization.role_cleanup.merge_tenant_scoped_system_roles` moves assignments
to the platform-wide role and deletes each duplicate; it refuses and changes
nothing if a duplicate cannot be merged safely. No-op on a database without
duplicates. The constraint that forbids such rows is migration 0004: it must be
a separate migration (separate transaction), because PostgreSQL refuses to
ALTER a table that still has deferred foreign-key checks pending from the rows
changed here ("pending trigger events").

Reverse: nothing to undo; merged duplicates are not recreated (their assignments
now point at the platform roles, which is the intended state).
"""

from django.db import migrations

from authorization.role_cleanup import merge_tenant_scoped_system_roles


def forwards(apps, schema_editor):
    merge_tenant_scoped_system_roles(
        apps.get_model("authorization", "Role"),
        apps.get_model("authorization", "MembershipRole"),
        apps.get_model("authorization", "RolePermission"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
