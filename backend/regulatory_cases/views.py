"""Regulatory case API.

DRF APIViews following the workflows app: explicit permission classes per
method, tenant from `current_tenant()`, public IDs only, and domain exceptions
mapped to status codes here rather than leaking out of the service layer.
"""

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import CaseStatus, RegulatoryCase
from .permissions import (
    PERM_CANCEL,
    PERM_COMPLETE,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_LINKS,
    CanCancelCases,
    CanCompleteCases,
    CanCreateCases,
    CanEditCases,
    CanManageCaseLinks,
    CanViewCases,
    has_case_permission,
)
from .projection import can_view_workflows, project_links
from .serializers import (
    CaseCreateSerializer,
    CaseFilterSerializer,
    CaseUpdateSerializer,
    LinkRequestSerializer,
    RegulatoryCaseSerializer,
    StatusChangeSerializer,
)

VALID_KINDS = ("workflow", "document", "checklist")


def _get_tenant(request):
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _get_case_or_404(public_id, tenant) -> RegulatoryCase:
    """Tenant-scoped lookup. A case in another tenant is 404, not 403 -- a 403
    would confirm the case exists."""
    try:
        return RegulatoryCase.objects.select_related("owner", "created_by").get(
            public_id=public_id, tenant=tenant
        )
    except RegulatoryCase.DoesNotExist as exc:
        raise NotFound("Case not found.") from exc


def _resolve_owner(owner_public_id, tenant):
    """An owner must be an active member of this tenant.

    Same single message as an unknown user: otherwise a caller could enumerate
    which user UUIDs belong to other tenants by comparing the two errors.
    """
    if owner_public_id is None:
        return None
    from tenancy.models import TenantMembership

    membership = (
        TenantMembership.objects.select_related("user")
        .filter(tenant=tenant, user__public_id=owner_public_id, is_active=True)
        .first()
    )
    if membership is None:
        raise services.InvalidLinkTarget("That user cannot be assigned as owner.")
    return membership.user


def _case_permissions(request, tenant) -> dict:
    """What the caller may do, so the UI can render honestly.

    Advisory only -- every endpoint re-checks. Exposed because the alternative
    is the frontend inferring capability from a role name, which drifts.
    """
    return {
        "can_edit": has_case_permission(request.user, tenant, PERM_EDIT),
        "can_manage_links": has_case_permission(request.user, tenant, PERM_MANAGE_LINKS),
        "can_complete": has_case_permission(request.user, tenant, PERM_COMPLETE),
        "can_cancel": has_case_permission(request.user, tenant, PERM_CANCEL),
        "can_create": has_case_permission(request.user, tenant, PERM_CREATE),
    }


class RegulatoryCaseListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateCases()]
        return [CanViewCases()]

    @extend_schema(tags=["regulatory-cases"], responses={200: RegulatoryCaseSerializer(many=True)})
    def get(self, request):
        tenant = _get_tenant(request)
        filters = CaseFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        criteria = filters.validated_data

        qs = RegulatoryCase.objects.filter(tenant=tenant).select_related("owner", "created_by")

        if criteria.get("status"):
            qs = qs.filter(status=criteria["status"])

        search = (criteria.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(case_number__icontains=search)
                | Q(title__icontains=search)
                | Q(product_name__icontains=search)
                | Q(product_code__icontains=search)
                | Q(market__icontains=search)
                | Q(submission_type__icontains=search)
            )

        return Response(
            {
                "results": RegulatoryCaseSerializer(qs, many=True).data,
                "permissions": _case_permissions(request, tenant),
            }
        )

    @extend_schema(
        tags=["regulatory-cases"],
        request=CaseCreateSerializer,
        responses={201: RegulatoryCaseSerializer},
    )
    def post(self, request):
        tenant = _get_tenant(request)
        serializer = CaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)

        owner_public_id = payload.pop("owner_public_id", None)
        try:
            owner = _resolve_owner(owner_public_id, tenant)
        except services.InvalidLinkTarget as exc:
            return Response({"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        case = services.create_case(tenant=tenant, actor=request.user, owner=owner, **payload)
        return Response(RegulatoryCaseSerializer(case).data, status=http_status.HTTP_201_CREATED)


class RegulatoryCaseDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [CanEditCases()]
        return [CanViewCases()]

    @extend_schema(tags=["regulatory-cases"], responses={200: RegulatoryCaseSerializer})
    def get(self, request, public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)

        # Each kind is fetched with its target pre-joined, and the module
        # permission resolved once per kind rather than per row.
        links = {kind: services.active_links(kind=kind, case=case) for kind in VALID_KINDS}
        projected = {
            kind: project_links(kind, links[kind], request.user, tenant) for kind in VALID_KINDS
        }

        return Response(
            {
                "case": RegulatoryCaseSerializer(case).data,
                "workflows": projected["workflow"],
                "documents": projected["document"],
                "checklists": projected["checklist"],
                "summary": _summary(links, request.user, tenant),
                "permissions": _case_permissions(request, tenant),
            }
        )

    @extend_schema(
        tags=["regulatory-cases"],
        request=CaseUpdateSerializer,
        responses={200: RegulatoryCaseSerializer},
    )
    def patch(self, request, public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)
        serializer = CaseUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)

        if "owner_public_id" in payload:
            try:
                payload["owner"] = _resolve_owner(payload.pop("owner_public_id"), tenant)
            except services.InvalidLinkTarget as exc:
                return Response(
                    {"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
                )

        try:
            updated = services.update_case(case=case, tenant=tenant, actor=request.user, **payload)
        except services.CaseLocked as exc:
            return Response(
                {"detail": str(exc), "current_status": case.status},
                status=http_status.HTTP_409_CONFLICT,
            )
        return Response(RegulatoryCaseSerializer(updated).data)


def _summary(links, user, tenant) -> dict:
    """Counts for the workspace header.

    Computed from the already-fetched link lists rather than by re-querying, so
    the detail endpoint stays at a fixed number of queries regardless of how
    many resources a case links.

    **How many things are linked is case-level information** -- the caller can
    already see one row per link, so a count discloses nothing further.

    **What state those things are in is not.** `workflows_open`,
    `workflows_completed` and `evidence_links` all read workflow data, so they
    are gated on `workflows.view` and reported as None otherwise. Returning a
    real state breakdown to a caller who cannot see a single workflow title
    would leak through the summary exactly what the projection withholds from
    the rows.
    """
    from workflows.models import WorkflowEvidence
    from workflows.transitions import TERMINAL_STATES

    workflow_links = list(links["workflow"])

    summary = {
        "documents": len(links["document"]),
        "workflows": len(workflow_links),
        "checklists": len(links["checklist"]),
        "workflows_open": None,
        "workflows_completed": None,
        "evidence_links": None,
    }

    if not can_view_workflows(user, tenant):
        return summary

    states = [link.workflow_item.state for link in workflow_links]
    summary["workflows_open"] = sum(1 for s in states if s not in TERMINAL_STATES)
    summary["workflows_completed"] = sum(1 for s in states if s in TERMINAL_STATES)

    item_ids = [link.workflow_item_id for link in workflow_links]
    summary["evidence_links"] = (
        WorkflowEvidence.objects.filter(
            workflow_item_id__in=item_ids, tenant=tenant, unlinked_at__isnull=True
        ).count()
        if item_ids
        else 0
    )
    return summary


class _CaseStatusActionView(APIView):
    action = ""

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        fn = services.complete_case if self.action == "complete" else services.cancel_case
        try:
            updated = fn(case=case, tenant=tenant, actor=request.user, reason=reason)
        except services.CaseLocked as exc:
            return Response(
                {"detail": str(exc), "current_status": case.status},
                status=http_status.HTTP_409_CONFLICT,
            )
        return Response(RegulatoryCaseSerializer(updated).data)


class RegulatoryCaseCompleteView(_CaseStatusActionView):
    """Completing a case records that work stopped. It is NOT an approval."""

    action = "complete"
    permission_classes = [CanCompleteCases]


class RegulatoryCaseCancelView(_CaseStatusActionView):
    action = "cancel"
    permission_classes = [CanCancelCases]


class CaseLinkListCreateView(APIView):
    """List or create links of one kind. The kind is fixed by the URL."""

    kind = ""

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageCaseLinks()]
        return [CanViewCases()]

    @extend_schema(tags=["regulatory-cases"])
    def get(self, request, public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)
        rows = services.active_links(kind=self.kind, case=case)
        return Response(project_links(self.kind, rows, request.user, tenant))

    @extend_schema(tags=["regulatory-cases"], request=LinkRequestSerializer)
    def post(self, request, public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)
        serializer = LinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            link = services.link_target(
                kind=self.kind,
                case=case,
                target_public_id=serializer.validated_data["target_public_id"],
                actor=request.user,
                tenant=tenant,
                label=serializer.validated_data.get("label", ""),
            )
        except services.CaseLocked as exc:
            return Response(
                {"detail": str(exc), "current_status": case.status},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.DuplicateLink as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        except services.InvalidLinkTarget as exc:
            return Response({"target_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        projected = project_links(self.kind, [link], request.user, tenant)[0]
        return Response(projected, status=http_status.HTTP_201_CREATED)


class CaseLinkDetailView(APIView):
    kind = ""
    permission_classes = [CanManageCaseLinks]

    @extend_schema(tags=["regulatory-cases"])
    def delete(self, request, public_id, link_public_id):
        tenant = _get_tenant(request)
        case = _get_case_or_404(public_id, tenant)
        try:
            services.unlink_target(
                kind=self.kind,
                case=case,
                link_public_id=link_public_id,
                actor=request.user,
                tenant=tenant,
            )
        except services.CaseLocked as exc:
            return Response(
                {"detail": str(exc), "current_status": case.status},
                status=http_status.HTTP_409_CONFLICT,
            )
        except services.InvalidLinkTarget as exc:
            raise NotFound(str(exc)) from exc
        return Response(status=http_status.HTTP_204_NO_CONTENT)


# Concrete per-kind views. Subclassing rather than routing a `kind` URL segment,
# so an unknown kind is a 404 from the URL resolver instead of something the
# view has to validate.
class CaseWorkflowListCreateView(CaseLinkListCreateView):
    kind = "workflow"


class CaseWorkflowDetailView(CaseLinkDetailView):
    kind = "workflow"


class CaseDocumentListCreateView(CaseLinkListCreateView):
    kind = "document"


class CaseDocumentDetailView(CaseLinkDetailView):
    kind = "document"


class CaseChecklistListCreateView(CaseLinkListCreateView):
    kind = "checklist"


class CaseChecklistDetailView(CaseLinkDetailView):
    kind = "checklist"


__all__ = [
    "CaseChecklistDetailView",
    "CaseChecklistListCreateView",
    "CaseDocumentDetailView",
    "CaseDocumentListCreateView",
    "CaseStatus",
    "CaseWorkflowDetailView",
    "CaseWorkflowListCreateView",
    "RegulatoryCaseCancelView",
    "RegulatoryCaseCompleteView",
    "RegulatoryCaseDetailView",
    "RegulatoryCaseListCreateView",
]
