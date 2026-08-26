from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _register(sender, **kwargs):
    from .permissions import register_permission_codenames

    register_permission_codenames()


class DossierUpgradesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dossier_upgrades"
    verbose_name = "Dossier upgrades"

    def ready(self):
        # Discovery only: enforcement reads ROLE_PERMISSIONS, not this table.
        post_migrate.connect(_register, sender=self)
