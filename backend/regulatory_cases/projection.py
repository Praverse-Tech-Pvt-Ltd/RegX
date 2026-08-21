"""Safe projection of linked resources into case responses.

**The rule this module exists to enforce:**

    CASE VIEW != DOCUMENT VIEW
    CASE VIEW != WORKFLOW VIEW
    CASE VIEW != CHECKLIST VIEW

Holding `regulatory_cases.view` tells you that a case links three documents. It
tells you nothing about what those documents are. Detail is added only when the
caller independently holds that module's own view permission, checked through
that module's own helper so the two cannot drift apart.

A caller without the module permission gets the link's own identifiers -- its
public_id, when it was linked, by whom, and the target's public_id -- and a
`restricted: true` marker. Never a title, filename, checksum, scan status,
workflow title, checklist detail or owner email.

The target public_id is included deliberately: it is an opaque UUID that
discloses nothing on its own, and without it the UI cannot offer a "request
access" affordance or a stable key for the row.
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


def _base(link) -> dict:
    """Everything a case-only caller may see about a link."""
    return {
        "public_id": str(link.public_id),
        "label": link.label,
        "linked_at": link.linked_at,
        # The linking actor is case activity, not resource content, so it is
        # part of the case record. Name only -- never the email, which is
        # personal data the case permission does not entitle the caller to.
        "linked_by": ({"full_name": link.linked_by.full_name} if link.linked_by_id else None),
    }


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
    "workflow": project_workflow_link,
    "document": project_document_link,
    "checklist": project_checklist_link,
}

PERMISSION_CHECKS = {
    "workflow": can_view_workflows,
    "document": can_view_documents,
    "checklist": can_view_checklists,
}


def project_links(kind: str, links, user, tenant) -> list[dict]:
    """Project a list of links of one kind.

    The permission is resolved ONCE per request rather than per row: it depends
    only on (user, tenant), and calling it per link would issue a membership
    query for every row in the list.
    """
    allowed = PERMISSION_CHECKS[kind](user, tenant)
    projector = PROJECTORS[kind]
    return [projector(link, allowed=allowed) for link in links]
