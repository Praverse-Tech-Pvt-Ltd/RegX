"""A system role must have no tenant (§11 #25). Runs after 0003 has merged any duplicates.

Rollback: drops the constraint.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0003_merge_tenant_scoped_system_roles"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="role",
            constraint=models.CheckConstraint(
                condition=models.Q(is_system=False) | models.Q(tenant__isnull=True),
                name="role_system_has_no_tenant",
            ),
        ),
    ]
