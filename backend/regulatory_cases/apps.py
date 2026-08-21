from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _register_case_permissions(sender, **kwargs):
    from .permissions import register_permission_codenames

    register_permission_codenames()


class RegulatoryCasesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "regulatory_cases"
    verbose_name = "Regulatory cases"

    def ready(self):
        # Discovery only: enforcement reads ROLE_PERMISSIONS, not this table.
        # Same arrangement as workflows.
        post_migrate.connect(_register_case_permissions, sender=self)
