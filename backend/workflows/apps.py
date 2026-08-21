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

        # A DocumentVersion cited as workflow evidence must not be deletable.
        # The registry keeps the dependency one-way -- documents never imports
        # workflows -- and is the same mechanism iig_checklist uses. This is a
        # second defence alongside the FK's on_delete=PROTECT, matching how the
        # repository already guards governed references.
        from documents.deletion_protection import DeletionProtectionRegistry

        DeletionProtectionRegistry.register(
            "workflow_evidence",
            _check_workflow_evidence_reference,
        )


def _check_workflow_evidence_reference(document_version) -> bool:
    """True if any workflow evidence link cites this version.

    Includes unlinked rows on purpose: the historical record that a version was
    once cited is itself governed, and deleting the version would strand it.
    """
    from workflows.models import WorkflowEvidence

    return WorkflowEvidence.objects.filter(document_version=document_version).exists()
