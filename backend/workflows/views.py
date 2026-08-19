"""Workflow domain API views. Tenant-scoped, UUID-only, generic 404.

State never changes through a write to the resource. It changes only through the
action endpoints below, each of which delegates to `workflows.services`.
"""

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import WorkflowItem
from .permissions import (
    CanAssignWorkflows,
    CanCreateWorkflows,
    CanEditDraftWorkflows,
    CanManageWorkflowEvidence,
    CanViewWorkflows,
    permitted_actions,
)
from .serializers import (
    AssignRequestSerializer,
    EvidenceLinkRequestSerializer,
    TransitionRequestSerializer,
    UserRefSerializer,
    WorkflowEvidenceSerializer,
    WorkflowItemPatchSerializer,
    WorkflowItemSerializer,
    WorkflowItemWriteSerializer,
    WorkflowTransitionSerializer,
)
from .transitions import IllegalWorkflowTransition, legal_actions_from

#: One message for both "no such user" and "user in another tenant".
#: Distinct wording would let a caller probe for the existence of users
#: outside their own tenant -- caught by
#: test_nonexistent_and_cross_tenant_user_are_indistinguishable.
INVALID_ASSIGNEE_MESSAGE = "User is not an active member of this tenant."


def _get_tenant(request):
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _get_item_or_404(public_id, tenant) -> WorkflowItem:
    """Scoped lookup. A public_id belonging to another tenant produces a 404,
    not a 403 -- a 403 would confirm the item exists somewhere."""
    try:
        return WorkflowItem.objects.select_related("tenant", "created_by", "assigned_to").get(
            public_id=public_id, tenant=tenant
        )
    except WorkflowItem.DoesNotExist as exc:
        raise NotFound("Workflow item not found.") from exc


def _serialize(item, request, tenant):
    data = WorkflowItemSerializer(item).data
    data["available_actions"] = permitted_actions(
        request.user, tenant, legal_actions_from(item.state)
    )
    return data


class WorkflowPagination(PageNumberPagination):
    page_size = 25


class WorkflowItemListCreateView(APIView):
    def get_permissions(self):
        return [CanCreateWorkflows()] if self.request.method == "POST" else [CanViewWorkflows()]

    @extend_schema(tags=["workflows"], responses={200: WorkflowItemSerializer(many=True)})
    def get(self, request):
        tenant = _get_tenant(request)
        qs = WorkflowItem.objects.filter(tenant=tenant).select_related("created_by", "assigned_to")
        state = request.query_params.get("state")
        if state:
            qs = qs.filter(state=state)
        assigned = request.query_params.get("assigned_to")
        if assigned:
            qs = qs.filter(assigned_to__public_id=assigned)

        paginator = WorkflowPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            [_serialize(item, request, tenant) for item in page]
        )

    @extend_schema(
        tags=["workflows"],
        request=WorkflowItemWriteSerializer,
        responses={201: WorkflowItemSerializer},
    )
    def post(self, request):
        tenant = _get_tenant(request)
        payload = WorkflowItemWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        item = services.create_item(
            tenant=tenant,
            actor=request.user,
            title=payload.validated_data["title"],
            description=payload.validated_data.get("description", ""),
            due_at=payload.validated_data.get("due_at"),
        )
        return Response(_serialize(item, request, tenant), status=http_status.HTTP_201_CREATED)


class WorkflowItemDetailView(APIView):
    def get_permissions(self):
        return [CanEditDraftWorkflows()] if self.request.method == "PATCH" else [CanViewWorkflows()]

    @extend_schema(tags=["workflows"], responses={200: WorkflowItemSerializer})
    def get(self, request, public_id):
        tenant = _get_tenant(request)
        return Response(_serialize(_get_item_or_404(public_id, tenant), request, tenant))

    @extend_schema(
        tags=["workflows"],
        request=WorkflowItemPatchSerializer,
        responses={200: WorkflowItemSerializer},
    )
    def patch(self, request, public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)

        # An attempt to move state through the resource is refused explicitly
        # rather than silently ignored, so a caller relying on it learns why.
        if "state" in request.data:
            raise ValidationError(
                {
                    "state": (
                        "State cannot be set directly. Use the transition "
                        "endpoints: submit, begin-review, approve, reject, cancel, "
                        "return-to-draft."
                    )
                }
            )

        payload = WorkflowItemPatchSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        try:
            item = services.update_draft(
                item=item, actor=request.user, tenant=tenant, **payload.validated_data
            )
        except IllegalWorkflowTransition as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        except services.TenantMismatch as exc:
            raise NotFound("Workflow item not found.") from exc
        return Response(_serialize(item, request, tenant))


class _TransitionView(APIView):
    """Shared body for the six action endpoints.

    Permission is checked by the service layer, not here: it depends on the
    action, and keeping one authority avoids the two drifting apart.
    """

    permission_classes = [CanViewWorkflows]
    action: str = ""

    @extend_schema(
        tags=["workflows"],
        request=TransitionRequestSerializer,
        responses={200: WorkflowItemSerializer},
    )
    def post(self, request, public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        payload = TransitionRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            item = services.perform_transition(
                item=item,
                action=self.action,
                actor=request.user,
                tenant=tenant,
                reason=payload.validated_data.get("reason", ""),
            )
        except IllegalWorkflowTransition as exc:
            # 409: the request was well-formed but the item is not in a state
            # where it applies. This is also what the loser of a concurrent
            # transition receives.
            return Response(
                {"detail": str(exc), "current_state": exc.current_state},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.ReasonRequired as exc:
            raise ValidationError({"reason": str(exc)}) from exc
        except services.WorkflowPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        except services.TenantMismatch as exc:
            raise NotFound("Workflow item not found.") from exc

        return Response(_serialize(item, request, tenant))


class SubmitView(_TransitionView):
    action = "submit"


class BeginReviewView(_TransitionView):
    action = "begin_review"


class ApproveView(_TransitionView):
    action = "approve"


class RejectView(_TransitionView):
    action = "reject"


class CancelView(_TransitionView):
    action = "cancel"


class ReturnToDraftView(_TransitionView):
    action = "return_to_draft"


class AssignView(APIView):
    permission_classes = [CanAssignWorkflows]

    @extend_schema(
        tags=["workflows"],
        request=AssignRequestSerializer,
        responses={200: WorkflowItemSerializer},
    )
    def post(self, request, public_id):
        from identity.models import User

        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        payload = AssignRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        assignee = None
        assignee_id = payload.validated_data.get("assigned_to")
        if assignee_id is not None:
            try:
                assignee = User.objects.get(public_id=assignee_id)
            except User.DoesNotExist as exc:
                raise ValidationError({"assigned_to": INVALID_ASSIGNEE_MESSAGE}) from exc

        try:
            with transaction.atomic():
                item = services.assign(
                    item=item, assignee=assignee, actor=request.user, tenant=tenant
                )
        except services.InvalidAssignee as exc:
            # Not str(exc): the service's wording differs, and the difference
            # would itself be the leak.
            raise ValidationError({"assigned_to": INVALID_ASSIGNEE_MESSAGE}) from exc
        except IllegalWorkflowTransition as exc:
            return Response(
                {"detail": str(exc), "current_state": exc.current_state},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.TenantMismatch as exc:
            raise NotFound("Workflow item not found.") from exc

        return Response(_serialize(item, request, tenant))


class WorkflowHistoryView(APIView):
    """Read-only. There is no update or delete endpoint for history, and the
    model refuses those operations regardless of caller."""

    permission_classes = [CanViewWorkflows]

    @extend_schema(tags=["workflows"], responses={200: WorkflowTransitionSerializer(many=True)})
    def get(self, request, public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        rows = item.transitions.filter(tenant=tenant).select_related("actor")
        return Response(WorkflowTransitionSerializer(rows, many=True).data)


def _has_document_access(request, tenant) -> bool:
    """Whether this caller holds documents.view in this tenant.

    Read through the documents app's own helper rather than reimplemented, so
    the two cannot drift.
    """
    from documents.permissions import PERM_VIEW as DOCUMENTS_PERM_VIEW
    from documents.permissions import has_document_permission

    return has_document_permission(request.user, tenant, DOCUMENTS_PERM_VIEW)


def _require_document_access(request, tenant) -> None:
    if not _has_document_access(request, tenant):
        raise PermissionDenied(
            "Linking evidence requires permission to view documents in this tenant."
        )


def _serialize_evidence(record, request, tenant):
    """One evidence row. Document detail only for callers holding documents.view."""
    version = record.document_version
    data = {
        "public_id": str(record.public_id),
        "label": record.label,
        "linked_by": UserRefSerializer(record.linked_by).data if record.linked_by else None,
        "linked_at": record.linked_at,
        "document_version_public_id": str(version.public_id),
        "document_public_id": str(version.document.public_id),
    }
    if _has_document_access(request, tenant):
        data["document"] = {
            "title": version.document.title,
            "document_type": version.document.document_type,
            "version_number": version.version_number,
            "original_filename": version.original_filename,
            "size_bytes": version.size_bytes,
            "sha256_checksum": version.sha256_checksum,
            "scan_status": version.scan_status,
            "uploaded_at": version.uploaded_at,
        }
    return data


def _serialize_evidence_list(rows, request, tenant):
    # Resolved once for the whole list rather than per row: the answer cannot
    # change mid-response, and the check hits the database.
    include_detail = _has_document_access(request, tenant)
    out = []
    for record in rows:
        version = record.document_version
        entry = {
            "public_id": str(record.public_id),
            "label": record.label,
            "linked_by": UserRefSerializer(record.linked_by).data if record.linked_by else None,
            "linked_at": record.linked_at,
            "document_version_public_id": str(version.public_id),
            "document_public_id": str(version.document.public_id),
        }
        if include_detail:
            entry["document"] = {
                "title": version.document.title,
                "document_type": version.document.document_type,
                "version_number": version.version_number,
                "original_filename": version.original_filename,
                "size_bytes": version.size_bytes,
                "sha256_checksum": version.sha256_checksum,
                "scan_status": version.scan_status,
                "uploaded_at": version.uploaded_at,
            }
        out.append(entry)
    return out


class WorkflowEvidenceView(APIView):
    """List and create evidence links for a workflow item.

    Authorization is TWO independent gates and both are always evaluated:

      * `workflows.view` / `workflows.manage_evidence` -- may this caller see or
        change this workflow's evidence set;
      * `documents.view` -- may this caller see document detail.

    Neither implies the other. A caller with workflow access but no document
    permission gets identifiers and link metadata, never document detail. That
    is a real configuration, not a hypothetical: PLATFORM_SUPPORT holds
    `workflows.view` and has no document permissions.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageWorkflowEvidence()]
        return [CanViewWorkflows()]

    @extend_schema(tags=["workflows"], responses={200: WorkflowEvidenceSerializer(many=True)})
    def get(self, request, public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        rows = services.active_evidence_for(item, tenant)
        return Response(_serialize_evidence_list(rows, request, tenant))

    @extend_schema(
        tags=["workflows"],
        request=EvidenceLinkRequestSerializer,
        responses={201: WorkflowEvidenceSerializer},
    )
    def post(self, request, public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        payload = EvidenceLinkRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # The second gate. Linking cites a document, so the caller must be
        # entitled to the document as well as to the workflow.
        _require_document_access(request, tenant)

        try:
            record = services.link_evidence(
                item=item,
                document_version_public_id=payload.validated_data["document_version_public_id"],
                actor=request.user,
                tenant=tenant,
                label=payload.validated_data.get("label", ""),
            )
        except services.EvidenceLocked as exc:
            return Response(
                {"detail": str(exc), "current_state": item.state},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.DuplicateEvidence as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        except services.InvalidEvidenceTarget as exc:
            raise ValidationError({"document_version_public_id": str(exc)}) from exc
        except services.TenantMismatch as exc:
            raise NotFound("Workflow item not found.") from exc

        return Response(
            _serialize_evidence(record, request, tenant),
            status=http_status.HTTP_201_CREATED,
        )


class WorkflowEvidenceDetailView(APIView):
    """Unlink one evidence link. There is no update endpoint."""

    permission_classes = [CanManageWorkflowEvidence]

    @extend_schema(tags=["workflows"], responses={200: WorkflowEvidenceSerializer})
    def delete(self, request, public_id, evidence_public_id):
        tenant = _get_tenant(request)
        item = _get_item_or_404(public_id, tenant)
        try:
            record = services.unlink_evidence(
                item=item,
                evidence_public_id=evidence_public_id,
                actor=request.user,
                tenant=tenant,
            )
        except services.EvidenceLocked as exc:
            return Response(
                {"detail": str(exc), "current_state": item.state},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.InvalidEvidenceTarget as exc:
            raise NotFound(str(exc)) from exc
        except services.TenantMismatch as exc:
            raise NotFound("Workflow item not found.") from exc

        return Response(_serialize_evidence(record, request, tenant))
