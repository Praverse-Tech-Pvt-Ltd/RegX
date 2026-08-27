"""Submission operations dashboard API. Read-only, tenant-scoped, no writes.

`submission_operations.view` opens the door. It does not unlock a single room:
every module is re-gated per request through its own helper, and a dimension the
caller may not see comes back `null`, never `0`.

Nothing here mutates anything, so nothing here emits an audit event. The
repository does not audit reads, and inventing that for one screen would both
break the convention and bury the write trail under dashboard noise.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from . import services
from .permissions import CanViewOperations
from .projection import MODULE_CASES, MODULE_DOSSIERS, visibility_for
from .serializers import (
    OperationsActivityRowSerializer,
    OperationsAttentionRowSerializer,
    OperationsCaseRowSerializer,
    OperationsDossierRowSerializer,
    OperationsOverviewSerializer,
    OperationsOwnerRowSerializer,
)

TAGS = ["submission-operations"]


def _tenant_or_403():
    from tenancy.context import TenantScopeMissing

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


class _Pagination(PageNumberPagination):
    """Project default page size, with a bounded client override.

    `max_page_size` is the point: without it `?page_size=100000` turns a
    bounded-query dashboard into a full-table materialisation, and the query
    budget the tests defend says nothing about how many rows come back.
    """

    page_size_query_param = "page_size"
    max_page_size = 200


def _paginate(request, rows, serializer_cls, extra=None):
    paginator = _Pagination()
    page = paginator.paginate_queryset(rows, request)
    payload = paginator.get_paginated_response(serializer_cls(page, many=True).data)
    if extra:
        payload.data.update(extra)
    return payload


class OperationsOverviewView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(tags=TAGS, responses=OperationsOverviewSerializer)
    def get(self, request):
        tenant = _tenant_or_403()
        data = services.overview(user=request.user, tenant=tenant)
        return Response(OperationsOverviewSerializer(data).data)


class OperationsAttentionView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("severity", str, description="Filter by operational severity."),
            OpenApiParameter("reason_code", str, description="Filter by reason code."),
        ],
        responses=OperationsAttentionRowSerializer(many=True),
    )
    def get(self, request):
        tenant = _tenant_or_403()
        visibility = visibility_for(request.user, tenant)
        rows, truncated = services.attention_rows(tenant=tenant, visibility=visibility)

        severity = request.query_params.get("severity")
        if severity:
            _validate_choice(severity, set(services.REASON_SEVERITY.values()), "severity")
            rows = [r for r in rows if r["severity"] == severity]

        reason = request.query_params.get("reason_code")
        if reason:
            _validate_choice(reason, set(services.REASON_SEVERITY.keys()), "reason_code")
            rows = [r for r in rows if r["reason_code"] == reason]

        return _paginate(
            request,
            rows,
            OperationsAttentionRowSerializer,
            extra={"truncated": truncated, "semantics": services.SEMANTICS},
        )


class OperationsCaseListView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, description="Case status."),
            OpenApiParameter("search", str, description="Case number or title."),
        ],
        responses=OperationsCaseRowSerializer(many=True),
    )
    def get(self, request):
        tenant = _tenant_or_403()
        visibility = visibility_for(request.user, tenant)
        if not visibility.allows(MODULE_CASES):
            # Not 403: the caller may legitimately open the dashboard. The case
            # panel simply has no answer for them, which is what `null` says.
            return Response({"results": None, "count": None, "restricted": True})

        from regulatory_cases.models import CaseStatus, RegulatoryCase

        qs = RegulatoryCase.objects.filter(tenant=tenant).select_related("owner")

        status = request.query_params.get("status")
        if status:
            _validate_choice(status, set(CaseStatus.values), "status")
            qs = qs.filter(status=status)

        search = (request.query_params.get("search") or "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(Q(case_number__icontains=search) | Q(title__icontains=search))

        qs = qs.order_by("-updated_at", "-id")
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        rows = services.case_rows(tenant=tenant, visibility=visibility, queryset=page)
        return paginator.get_paginated_response(OperationsCaseRowSerializer(rows, many=True).data)


class OperationsDossierListView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, description="Dossier status."),
            OpenApiParameter("internal_readiness", str, description="Internal readiness label."),
            OpenApiParameter("search", str, description="Dossier title."),
        ],
        responses=OperationsDossierRowSerializer(many=True),
    )
    def get(self, request):
        tenant = _tenant_or_403()
        visibility = visibility_for(request.user, tenant)
        if not visibility.allows(MODULE_DOSSIERS):
            return Response({"results": None, "count": None, "restricted": True})

        from submission_dossiers.models import DossierStatus, SubmissionDossier

        qs = SubmissionDossier.objects.filter(tenant=tenant).select_related(
            "owner", "regulatory_case"
        )

        status = request.query_params.get("status")
        if status:
            _validate_choice(status, set(DossierStatus.values), "status")
            qs = qs.filter(status=status)

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(title__icontains=search)

        # BEFORE pagination. Filtering the page after slicing would make `count`
        # describe the unfiltered set and hide matches that fall on later pages.
        readiness = request.query_params.get("internal_readiness")
        if readiness:
            _validate_choice(readiness, services.INTERNAL_READINESS_VALUES, "internal_readiness")
            qs = services.filter_by_internal_readiness(qs, readiness)

        qs = qs.order_by("-updated_at", "-id")
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        rows = services.dossier_rows(tenant=tenant, visibility=visibility, queryset=page)

        return paginator.get_paginated_response(
            OperationsDossierRowSerializer(rows, many=True).data
        )


class OperationsOwnerListView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(tags=TAGS, responses=OperationsOwnerRowSerializer(many=True))
    def get(self, request):
        tenant = _tenant_or_403()
        visibility = visibility_for(request.user, tenant)
        if not visibility.allows(MODULE_DOSSIERS):
            return Response({"results": None, "count": None, "restricted": True})
        rows = services.owner_workload(tenant=tenant, visibility=visibility)
        return _paginate(request, rows, OperationsOwnerRowSerializer)


class OperationsRecentActivityView(APIView):
    permission_classes = [CanViewOperations]

    @extend_schema(tags=TAGS, responses=OperationsActivityRowSerializer(many=True))
    def get(self, request):
        tenant = _tenant_or_403()
        visibility = visibility_for(request.user, tenant)
        rows = services.recent_activity(tenant=tenant, visibility=visibility)
        return Response(
            {
                "results": OperationsActivityRowSerializer(rows, many=True).data,
                "count": len(rows),
                "semantics": services.SEMANTICS,
            }
        )


def _validate_choice(value, allowed, field):
    """Reject anything not in the enum.

    Filters are the classic place a dashboard turns into an oracle: an
    unvalidated value reaching the ORM lets a caller probe fields the API never
    meant to expose, and an unvalidated *sort* field is worse. Neither list nor
    ordering is ever taken from the request unchecked.
    """
    if value not in allowed:
        raise ValidationError({field: f"Unsupported value for {field}."})
