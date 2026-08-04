from django.apps import AppConfig


class IigChecklistConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "iig_checklist"
    verbose_name = "IIG Checklist Definition Governance"

    def ready(self):
        from documents.deletion_protection import DeletionProtectionRegistry

        DeletionProtectionRegistry.register(
            "iig_checklist_response_evidence",
            _check_iig_checklist_evidence_reference,
        )


def _check_iig_checklist_evidence_reference(document_version):
    """Return True if any ChecklistResponse in an approved execution
    references document_version.public_id in its raw_value."""
    from iig_checklist.models import ChecklistResponse

    doc_uuid = str(document_version.public_id)
    candidates = ChecklistResponse.objects.filter(
        execution__status="approved",
        raw_value__isnull=False,
    )
    for response in candidates.iterator():
        rv = response.raw_value
        if isinstance(rv, dict) and rv.get("document_version_public_id") == doc_uuid:
            return True
    return False
