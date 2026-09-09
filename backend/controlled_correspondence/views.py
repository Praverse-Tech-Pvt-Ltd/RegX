"""Controlled Correspondence API.

Two halves with different ownership:

* Best practices are published guidance -- platform-level and read-only.
* Drafts are the tenant's own work -- tenant-scoped and writable.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from .models import BestPractice, CorrespondenceDraft
from .permissions import CanManageCorrespondence, CanViewCorrespondence
from .serializers import (
    BestPracticeSerializer,
    CorrespondenceDraftSerializer,
    CorrespondenceDraftWriteSerializer,
)


class CorrespondencePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _tenant():
    try:
        return current_tenant()
    except Exception:
        return None


class BestPracticeListView(APIView):
    """Published guidance. Read-only: a tenant cannot edit it."""

    permission_classes = [CanViewCorrespondence]

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str, description="Exact match"),
            OpenApiParameter("search", str, description="Text within the guidance"),
        ],
        responses=BestPracticeSerializer(many=True),
    )
    def get(self, request):
        qs = BestPractice.objects.all()
        if request.query_params.get("category"):
            qs = qs.filter(category=request.query_params["category"])
        if request.query_params.get("search"):
            qs = qs.filter(guidance__icontains=request.query_params["search"])
        paginator = CorrespondencePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(BestPracticeSerializer(page, many=True).data)


class BestPracticeCategoriesView(APIView):
    permission_classes = [CanViewCorrespondence]

    def get(self, request):
        # .order_by() first: Meta.ordering otherwise joins the SELECT and
        # DISTINCT applies to the tuple, returning one entry per row.
        categories = sorted(
            c
            for c in BestPractice.objects.order_by().values_list("category", flat=True).distinct()
            if c
        )
        return Response({"categories": categories})


def _draft_or_404(public_id):
    draft = CorrespondenceDraft.objects.filter(public_id=public_id, tenant=_tenant()).first()
    if draft is None:
        raise NotFound("Draft not found.")
    return draft


class DraftListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageCorrespondence()]
        return [CanViewCorrespondence()]

    @extend_schema(responses=CorrespondenceDraftSerializer(many=True))
    def get(self, request):
        qs = CorrespondenceDraft.objects.filter(tenant=_tenant())
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        paginator = CorrespondencePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(CorrespondenceDraftSerializer(page, many=True).data)

    @extend_schema(
        request=CorrespondenceDraftWriteSerializer, responses=CorrespondenceDraftSerializer
    )
    def post(self, request):
        serializer = CorrespondenceDraftWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = CorrespondenceDraft.objects.create(
            tenant=_tenant(), created_by=request.user, **serializer.validated_data
        )
        return Response(
            CorrespondenceDraftSerializer(draft).data, status=http_status.HTTP_201_CREATED
        )


class DraftDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [CanViewCorrespondence()]
        return [CanManageCorrespondence()]

    @extend_schema(responses=CorrespondenceDraftSerializer)
    def get(self, request, public_id):
        return Response(CorrespondenceDraftSerializer(_draft_or_404(public_id)).data)

    @extend_schema(
        request=CorrespondenceDraftWriteSerializer, responses=CorrespondenceDraftSerializer
    )
    def patch(self, request, public_id):
        draft = _draft_or_404(public_id)
        serializer = CorrespondenceDraftWriteSerializer(draft, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CorrespondenceDraftSerializer(draft).data)

    def delete(self, request, public_id):
        _draft_or_404(public_id).delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)
