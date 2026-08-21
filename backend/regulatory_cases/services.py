"""Case service layer.

Every governed mutation goes through here: case creation, status changes and
the three link types. Views validate and serialise; this module owns the rules,
the locking and the audit, which is the same split the workflows app uses.
"""

from django.db import IntegrityError, transaction

from .audit_events import CaseEvent, emit
from .models import (
    CaseNumberSequence,
    CaseStatus,
    RegulatoryCase,
    RegulatoryCaseChecklist,
    RegulatoryCaseDocument,
    RegulatoryCaseWorkflow,
)


class InvalidLinkTarget(Exception):
    """The target does not exist, belongs to another tenant, or is not eligible.

    Deliberately one exception for all three. Separate messages would let a
    caller probe another tenant for the existence of a workflow, document or
    checklist by comparing responses.
    """


class CaseLocked(Exception):
    """The case is completed or cancelled and refuses structural changes."""


class DuplicateLink(Exception):
    """That target is already actively linked to this case."""


#: One message for absent, cross-tenant and ineligible. See InvalidLinkTarget.
INVALID_TARGET_MESSAGE = "That item is not available to link to this case."


def _assert_same_tenant(case: RegulatoryCase, tenant) -> None:
    if case.tenant_id != tenant.pk:
        # A caller who reached a case outside their tenant should get the same
        # answer as one asking for a case that does not exist.
        raise RegulatoryCase.DoesNotExist


def _require_mutable(case: RegulatoryCase) -> None:
    if case.is_terminal:
        raise CaseLocked(f"This case is {case.status} and no longer accepts changes.")


# ---------------------------------------------------------------------------
# Case lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def create_case(*, tenant, actor, **fields) -> RegulatoryCase:
    """Create a case, claiming the next tenant-local case number under lock."""
    case_number = CaseNumberSequence.claim(tenant)
    case = RegulatoryCase.objects.create(
        tenant=tenant,
        case_number=case_number,
        created_by=actor,
        **fields,
    )
    emit(
        event_type=CaseEvent.CREATED,
        resource_id=case.public_id,
        actor=actor,
        tenant_id=tenant.pk,
        payload={
            "action": "created",
            "case_public_id": str(case.public_id),
            "case_number": case.case_number,
            "to_status": case.status,
        },
    )
    return case


@transaction.atomic
def update_case(*, case: RegulatoryCase, tenant, actor, **fields) -> RegulatoryCase:
    """Patch editable fields on an open case."""
    _assert_same_tenant(case, tenant)
    locked = RegulatoryCase.objects.select_for_update().get(pk=case.pk)
    _assert_same_tenant(locked, tenant)
    _require_mutable(locked)

    changed = []
    for name, value in fields.items():
        if getattr(locked, name) != value:
            setattr(locked, name, value)
            changed.append(name)

    if changed:
        locked.save(update_fields=[*changed, "updated_at"])
        emit(
            event_type=CaseEvent.UPDATED,
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": "updated",
                "case_public_id": str(locked.public_id),
                "case_number": locked.case_number,
                # Names only. The values themselves can carry product and market
                # detail that does not belong in an audit row.
                "fields_changed": sorted(changed),
            },
        )
    return locked


def _terminate(*, case, tenant, actor, to_status, event_type, reason=""):
    """Shared body for complete and cancel."""
    _assert_same_tenant(case, tenant)
    with transaction.atomic():
        locked = RegulatoryCase.objects.select_for_update().get(pk=case.pk)
        _assert_same_tenant(locked, tenant)
        if locked.is_terminal:
            raise CaseLocked(f"This case is already {locked.status}.")

        from_status = locked.status
        locked.status = to_status
        locked.save(update_fields=["status", "updated_at"])

        emit(
            event_type=event_type,
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=tenant.pk,
            payload={
                "action": to_status,
                "case_public_id": str(locked.public_id),
                "case_number": locked.case_number,
                "from_status": from_status,
                "to_status": to_status,
                # The text itself is not recorded: it is free-form and can
                # describe the submission.
                "reason_supplied": bool(reason),
                "reason_length": len(reason or ""),
            },
        )
    return locked


def complete_case(*, case, tenant, actor, reason: str = "") -> RegulatoryCase:
    """Mark a case finished.

    Carries NO claim that any authority approved anything -- see
    docs/REGULATORY_CASES.md. It records that the tenant stopped working it.
    """
    return _terminate(
        case=case,
        tenant=tenant,
        actor=actor,
        to_status=CaseStatus.COMPLETED,
        event_type=CaseEvent.COMPLETED,
        reason=reason,
    )


def cancel_case(*, case, tenant, actor, reason: str = "") -> RegulatoryCase:
    return _terminate(
        case=case,
        tenant=tenant,
        actor=actor,
        to_status=CaseStatus.CANCELLED,
        event_type=CaseEvent.CANCELLED,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Links
#
# The three targets differ only in model, lookup and audit event, so they share
# one implementation with a small spec each. Duplicating this three times would
# invite the three from drifting apart, which is how one of them would quietly
# lose its tenant check.
# ---------------------------------------------------------------------------
def _resolve_workflow(public_id, tenant):
    from workflows.models import WorkflowItem

    return WorkflowItem.objects.filter(public_id=public_id, tenant=tenant).first()


def _resolve_document(public_id, tenant):
    from documents.models import Document

    return Document.objects.filter(public_id=public_id, tenant=tenant).first()


def _resolve_checklist(public_id, tenant):
    from iig_checklist.models import ChecklistExecution

    return ChecklistExecution.objects.filter(public_id=public_id, tenant=tenant).first()


def _may_view_workflows(user, tenant):
    from .projection import can_view_workflows

    return can_view_workflows(user, tenant)


def _may_view_documents(user, tenant):
    from .projection import can_view_documents

    return can_view_documents(user, tenant)


def _may_view_checklists(user, tenant):
    from .projection import can_view_checklists

    return can_view_checklists(user, tenant)


LINK_SPECS = {
    "workflow": {
        "model": RegulatoryCaseWorkflow,
        "field": "workflow_item",
        "resolve": _resolve_workflow,
        "may_view": _may_view_workflows,
        "linked_event": CaseEvent.WORKFLOW_LINKED,
        "unlinked_event": CaseEvent.WORKFLOW_UNLINKED,
    },
    "document": {
        "model": RegulatoryCaseDocument,
        "field": "document",
        "resolve": _resolve_document,
        "may_view": _may_view_documents,
        "linked_event": CaseEvent.DOCUMENT_LINKED,
        "unlinked_event": CaseEvent.DOCUMENT_UNLINKED,
    },
    "checklist": {
        "model": RegulatoryCaseChecklist,
        "field": "checklist_execution",
        "resolve": _resolve_checklist,
        "may_view": _may_view_checklists,
        "linked_event": CaseEvent.CHECKLIST_LINKED,
        "unlinked_event": CaseEvent.CHECKLIST_UNLINKED,
    },
}


def link_target(*, kind: str, case, target_public_id, actor, tenant, label: str = ""):
    """Link one workflow item, document or checklist execution to a case.

    TWO authorization gates, both required and checked separately:

      * `regulatory_cases.manage_links` -- may this caller change this case's
        link set (checked by the view's permission class); and
      * the TARGET MODULE's own view permission -- may this caller act on that
        workflow, document or checklist at all.

    Neither implies the other. Without the second gate, `manage_links` alone
    would turn this endpoint into an existence oracle: link a same-tenant UUID
    the caller may not see, and a success told them it exists while an error
    told them it does not. The target permission is resolved through that
    module's own helper, the same ones the projection layer uses, so read and
    link cannot drift apart.
    """
    spec = LINK_SPECS[kind]
    _assert_same_tenant(case, tenant)

    with transaction.atomic():
        # Lock the case so a concurrent complete/cancel cannot slip between the
        # mutability check and the insert.
        locked = RegulatoryCase.objects.select_for_update().get(pk=case.pk)
        _assert_same_tenant(locked, tenant)
        _require_mutable(locked)

        # Checked BEFORE resolving the target, and raising the same exception
        # with the same message: absent, cross-tenant and unauthorized must be
        # one indistinguishable outcome. Resolving first would let response
        # timing separate "does not exist" from "not yours to see".
        if not spec["may_view"](actor, tenant):
            raise InvalidLinkTarget(INVALID_TARGET_MESSAGE)

        target = spec["resolve"](target_public_id, tenant)
        if target is None:
            raise InvalidLinkTarget(INVALID_TARGET_MESSAGE)

        try:
            with transaction.atomic():
                link = spec["model"].objects.create(
                    case=locked,
                    tenant=locked.tenant,
                    linked_by=actor,
                    label=(label or "").strip()[:255],
                    **{spec["field"]: target},
                )
        except IntegrityError as exc:
            # The partial unique constraint fired: another caller won the race,
            # or it was already linked. Either way exactly one active link
            # exists, which is the property that matters.
            raise DuplicateLink("That item is already linked to this case.") from exc

        emit(
            event_type=spec["linked_event"],
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=locked.tenant_id,
            payload={
                "action": f"{kind}_linked",
                "case_public_id": str(locked.public_id),
                "case_number": locked.case_number,
                "link_kind": kind,
                "link_public_id": str(link.public_id),
                "target_public_id": str(target.public_id),
            },
        )
    return link


def unlink_target(*, kind: str, case, link_public_id, actor, tenant):
    """Retire a link. Stamps, never deletes."""
    spec = LINK_SPECS[kind]
    _assert_same_tenant(case, tenant)

    with transaction.atomic():
        locked = RegulatoryCase.objects.select_for_update().get(pk=case.pk)
        _assert_same_tenant(locked, tenant)
        _require_mutable(locked)

        record = (
            spec["model"]
            .objects.select_for_update()
            .filter(
                public_id=link_public_id,
                case=locked,
                tenant=tenant,
                unlinked_at__isnull=True,
            )
            .first()
        )
        if record is None:
            raise InvalidLinkTarget(INVALID_TARGET_MESSAGE)

        from django.db import models as _models
        from django.utils import timezone

        record.unlinked_at = timezone.now()
        record.unlinked_by = actor
        # The manager blocks `update()` on purpose; this is the one sanctioned
        # write, so it goes through the base Model.save rather than the
        # governed manager.
        _models.Model.save(record, update_fields=["unlinked_at", "unlinked_by", "updated_at"])

        emit(
            event_type=spec["unlinked_event"],
            resource_id=locked.public_id,
            actor=actor,
            tenant_id=locked.tenant_id,
            payload={
                "action": f"{kind}_unlinked",
                "case_public_id": str(locked.public_id),
                "case_number": locked.case_number,
                "link_kind": kind,
                "link_public_id": str(record.public_id),
            },
        )
    return record


def active_links(*, kind: str, case):
    """Active links of one kind, with their target pre-joined.

    `select_related` on the target and its own FKs, because the projection layer
    reads target fields for every row -- without it a case with twenty documents
    issues twenty-one queries.
    """
    spec = LINK_SPECS[kind]
    related = [spec["field"], "linked_by"]
    if kind == "document":
        related.append("document__current_version")
    if kind == "workflow":
        related.append("workflow_item__assigned_to")
    if kind == "checklist":
        related.append("checklist_execution__checklist_version")
    return (
        spec["model"]
        .objects.filter(case=case, unlinked_at__isnull=True)
        .select_related(*related)
        .order_by("linked_at", "id")
    )
