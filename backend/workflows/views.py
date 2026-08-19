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
    CanViewWorkflows,
    permitted_actions,
)
from .serializers import (
    AssignRequestSerializer,
    TransitionRequestSerializer,
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
