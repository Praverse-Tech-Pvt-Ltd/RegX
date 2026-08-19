from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _register_workflow_permissions(sender, **kwargs):
    from .permissions import register_permission_codenames

    register_permission_codenames()


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "workflows"
    verbose_name = "Workflows"

    def ready(self):
        # Registers codenames in the Permission table so /permissions/ and
        # /permissions/effective/ can surface them. Enforcement does not read
        # that table -- it reads ROLE_PERMISSIONS -- so this is discovery only.
        #
        # NOTE: documents/permissions.py defines an equivalent
        # seed_document_permissions() that has no caller, so its dot-form
        # codenames never reach the table. That is pre-existing and out of
        # scope here; this app wires its own registration rather than copying
        # the omission.
        post_migrate.connect(_register_workflow_permissions, sender=self)
