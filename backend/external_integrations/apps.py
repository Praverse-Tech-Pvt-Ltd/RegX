from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _register(sender, **kwargs):
    from .permissions import register_permission_codenames

    register_permission_codenames()


class ExternalIntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "external_integrations"
    verbose_name = "External integrations"

    def ready(self):
        # Discovery only: enforcement reads ROLE_PERMISSIONS, not this table.
        post_migrate.connect(_register, sender=self)
        # The AI gateway's HTTP providers live here, at the network edge, and
        # are handed to the gateway rather than imported by it.
        from .ai_http import register

        register()
