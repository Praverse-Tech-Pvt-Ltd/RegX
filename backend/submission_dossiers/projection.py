"""Safe projection of linked resources into section responses.

    SECTION VIEW != DOCUMENT VIEW
    SECTION VIEW != WORKFLOW VIEW
    SECTION VIEW != CHECKLIST VIEW

Holding `submission_dossiers.view` tells you a section links three documents. It
tells you nothing about what they are. Detail is added only when the caller
independently holds that module's own view permission, checked through that
module's own helper so the two cannot drift apart.

Reused verbatim from `regulatory_cases.projection` in intent: same helpers, same
restricted shape, so a reviewer comparing the two finds no divergence to reason
about.
"""

from documents.permissions import PERM_VIEW as DOCUMENTS_PERM_VIEW
from documents.permissions import has_document_permission
from iig_checklist.permissions import PERM_VIEW_EXECUTION, has_iig_checklist_permission
from workflows.permissions import PERM_VIEW as WORKFLOWS_PERM_VIEW
from workflows.permissions import has_workflow_permission


def can_view_documents(user, tenant) -> bool:
    return has_document_permission(user, tenant, DOCUMENTS_PERM_VIEW)


def can_view_workflows(user, tenant) -> bool:
    return has_workflow_permission(user, tenant, WORKFLOWS_PERM_VIEW)


def can_view_checklists(user, tenant) -> bool:
    return has_iig_checklist_permission(user, tenant, PERM_VIEW_EXECUTION)


PERMISSION_CHECKS = {
    "document": can_view_documents,
    "workflow": can_view_workflows,
    "checklist": can_view_checklists,
}


def _base(link) -> dict:
    """Everything a section-only caller may see about a link."""
    return {
        "public_id": str(link.public_id),
        "purpose": link.purpose,
        "linked_at": link.linked_at,
        # Name only -- never the email, which is personal data the section
        # permission does not entitle the caller to.
        "linked_by": {"full_name": link.linked_by.full_name} if link.linked_by_id else None,
    }


def project_document_link(link, *, allowed: bool) -> dict:
    data = _base(link)
    data["document_public_id"] = str(link.document.public_id)
    if not allowed:
        data["restricted"] = True
        return data
    doc = link.document
    version = doc.current_version
    data["document"] = {
        "title": doc.title,
        "document_type": doc.document_type,
        "status": doc.status,
        "current_version_number": version.version_number if version else None,
        "scan_status": version.scan_status if version else None,
    }
    return data


def project_workflow_link(link, *, allowed: bool) -> dict:
    data = _base(link)
    data["workflow_public_id"] = str(link.workflow_item.public_id)
    if not allowed:
        data["restricted"] = True
        return data
    item = link.workflow_item
    data["workflow"] = {
        "title": item.title,
        "state": item.state,
        "is_terminal": item.is_terminal,
        "due_at": item.due_at,
        "is_overdue": item.is_overdue,
    }
    return data


def project_checklist_link(link, *, allowed: bool) -> dict:
    data = _base(link)
    data["execution_public_id"] = str(link.checklist_execution.public_id)
    if not allowed:
        data["restricted"] = True
        return data
    execution = link.checklist_execution
    data["checklist"] = {
        "status": execution.status,
        "checklist_version_public_id": str(execution.checklist_version.public_id),
    }
    return data


PROJECTORS = {
    "document": project_document_link,
    "workflow": project_workflow_link,
    "checklist": project_checklist_link,
}


def project_links(kind: str, links, user, tenant) -> list[dict]:
    """Project one kind. The permission is resolved ONCE per request rather than
    per row -- it depends only on (user, tenant), and a per-row check would
    issue a membership query for every link."""
    allowed = PERMISSION_CHECKS[kind](user, tenant)
    projector = PROJECTORS[kind]
    return [projector(link, allowed=allowed) for link in links]


def module_counts(section_ids, user, tenant) -> dict:
    """Module-state counts, or None where the caller lacks the permission.

    **None, never zero.** Milestone 8 originally reported a real state
    breakdown to callers who could not see a single workflow, disclosing through
    a count exactly what the projection withholds from the rows. Reporting zero
    would be worse than reporting nothing: it asserts something false.
    """
    from workflows.models import WorkflowEvidence

    from .models import DossierSectionWorkflow

    if not can_view_workflows(user, tenant):
        return {"workflow_evidence_links": None}

    item_ids = list(
        DossierSectionWorkflow.objects.filter(
            section_id__in=section_ids, unlinked_at__isnull=True
        ).values_list("workflow_item_id", flat=True)
    )
    if not item_ids:
        return {"workflow_evidence_links": 0}
    return {
        "workflow_evidence_links": WorkflowEvidence.objects.filter(
            workflow_item_id__in=item_ids, tenant=tenant, unlinked_at__isnull=True
        ).count()
    }
