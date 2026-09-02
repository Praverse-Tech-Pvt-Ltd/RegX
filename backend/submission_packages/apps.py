from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _register(sender, **kwargs):
    from .permissions import register_permission_codenames

    register_permission_codenames()


def _check_package_entry_reference(document_version) -> bool:
    """True if any package entry cites this version.

    Includes removed entries on purpose: a version that was once in a package is
    part of how that package came to look the way it does, and deleting the
    version would strand the record -- the same reasoning
    `workflows._check_workflow_evidence_reference` gives for including unlinked
    evidence.
    """
    from .models import SubmissionPackageEntry

    return SubmissionPackageEntry.objects.filter(document_version=document_version).exists()


class SubmissionPackagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "submission_packages"
    verbose_name = "Submission packages"

    def ready(self):
        # Discovery only: enforcement reads ROLE_PERMISSIONS, not this table.
        post_migrate.connect(_register, sender=self)

        # A DocumentVersion inside a package must not be deletable. Second
        # defence alongside the FK's on_delete=PROTECT, using the registry that
        # keeps the dependency one-way -- documents never imports this app.
        from documents.deletion_protection import DeletionProtectionRegistry

        DeletionProtectionRegistry.register(
            "submission_package_entry",
            _check_package_entry_reference,
        )
