"""Product comparison API.

Tenant-scoped and writable, unlike the FDA reference corpora. Every queryset is
filtered by `current_tenant()`; a comparison belonging to another tenant is a 404,
not a 403, so the API does not confirm that it exists.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from .models import AttributeSource, ComparisonAttribute, ProductComparison
from .permissions import CanManageProductComparisons, CanViewProductComparisons
from .serializers import (
    ComparisonAttributeWriteSerializer,
    ComparisonMatrixSerializer,
    ProductComparisonSerializer,
    ProductComparisonWriteSerializer,
)


class ComparisonPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _tenant():
    try:
        return current_tenant()
    except Exception:
        return None


def _get_or_404(public_id):
    """Scope by tenant before identity: another tenant's comparison must be
    indistinguishable from one that does not exist."""
    comparison = ProductComparison.objects.filter(public_id=public_id, tenant=_tenant()).first()
    if comparison is None:
        raise NotFound("Comparison not found.")
    return comparison


class ComparisonListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageProductComparisons()]
        return [CanViewProductComparisons()]

    @extend_schema(responses=ProductComparisonSerializer(many=True))
    def get(self, request):
        qs = ProductComparison.objects.filter(tenant=_tenant())
        if request.query_params.get("product_type"):
            qs = qs.filter(product_type=request.query_params["product_type"])
        paginator = ComparisonPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(ProductComparisonSerializer(page, many=True).data)

    @extend_schema(request=ProductComparisonWriteSerializer, responses=ProductComparisonSerializer)
    def post(self, request):
        serializer = ProductComparisonWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comparison = ProductComparison.objects.create(
            tenant=_tenant(), created_by=request.user, **serializer.validated_data
        )
        return Response(
            ProductComparisonSerializer(comparison).data,
            status=http_status.HTTP_201_CREATED,
        )


class ComparisonDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [CanViewProductComparisons()]
        return [CanManageProductComparisons()]

    @extend_schema(responses=ProductComparisonSerializer)
    def get(self, request, public_id):
        return Response(ProductComparisonSerializer(_get_or_404(public_id)).data)

    @extend_schema(request=ProductComparisonWriteSerializer, responses=ProductComparisonSerializer)
    def patch(self, request, public_id):
        comparison = _get_or_404(public_id)
        serializer = ProductComparisonWriteSerializer(comparison, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductComparisonSerializer(comparison).data)

    def delete(self, request, public_id):
        _get_or_404(public_id).delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ComparisonAttributeView(APIView):
    """Upsert one attribute value.

    PUT rather than POST: (attribute, source) is unique per comparison, so
    re-sending a value corrects it. A create-only endpoint would force the client
    to know whether a cell had been filled before.
    """

    permission_classes = [CanManageProductComparisons]

    @extend_schema(request=ComparisonAttributeWriteSerializer)
    def put(self, request, public_id):
        comparison = _get_or_404(public_id)
        serializer = ComparisonAttributeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attribute, _ = ComparisonAttribute.objects.update_or_create(
            comparison=comparison,
            attribute=data["attribute"],
            source=data["source"],
            defaults={
                "value": data.get("value", ""),
                "document_reference": data.get("document_reference"),
            },
        )
        return Response(ProductComparisonSerializer(comparison).data)


class ComparisonMatrixView(APIView):
    """The attribute-by-source grid, with every known attribute present even when
    it has no value yet -- so the UI renders a complete form rather than only the
    cells that happen to be filled."""

    permission_classes = [CanViewProductComparisons]

    @extend_schema(responses=ComparisonMatrixSerializer)
    def get(self, request, public_id):
        comparison = _get_or_404(public_id)
        stored = {(a.attribute, a.source): a for a in comparison.attributes.all()}
        sources = [s.value for s in AttributeSource]
        # Known attributes first, then anything the tenant added beyond the list.
        extra = sorted({a for a, _ in stored} - set(comparison.known_attributes))
        rows = []
        for attribute in list(comparison.known_attributes) + extra:
            row = {"attribute": attribute}
            for source in sources:
                found = stored.get((attribute, source))
                row[source] = {
                    "value": found.value if found else "",
                    "document_reference": str(found.document_reference)
                    if found and found.document_reference
                    else None,
                }
            rows.append(row)
        return Response(
            ComparisonMatrixSerializer(
                {"product_type": comparison.product_type, "sources": sources, "rows": rows}
            ).data
        )
