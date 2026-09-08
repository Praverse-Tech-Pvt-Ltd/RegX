"""Deficiency corpus API.

DRF APIViews following the regulatory_cases and workflows apps: explicit
permission classes, tenant from `current_tenant()`, public IDs only.

Read-only over HTTP. The corpus is published reference material; it is loaded by
the `import_deficiencies` management command against a source file with a
recorded checksum, not by API writes.
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.pagination import PageNumberPagination

from .models import DeficiencyRecord
from .permissions import CanViewDeficiencies
from .serializers import DeficiencyFacetsSerializer, DeficiencyRecordSerializer

class DeficiencyPagination(PageNumberPagination):
    """Same shape as FormulationsPagination: caller-controllable page size with
    a hard ceiling, because the corpus is 7,458 rows and a client asking for
    all of them at once is a mistake rather than a use case."""

    page_size_query_param = "page_size"
    max_page_size = 200


FILTERS = ("corpus", "main_category", "dosage_form", "cmc_section", "deficiency_type")


def _filtered_queryset(request):
    """Apply exact-match filters plus a free-text `search` across the body and
    classification columns. Values come from the corpus itself via /facets/."""
    qs = DeficiencyRecord.objects.all()
    for field in FILTERS:
        value = request.query_params.get(field)
        if value:
            qs = qs.filter(**{field: value})
    search = (request.query_params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(deficiency__icontains=search)
            | Q(cmc_section__icontains=search)
            | Q(category_of_deficiency__icontains=search)
            | Q(deficiency_type__icontains=search)
        )
    return qs


class DeficiencyListView(APIView):
    permission_classes = [CanViewDeficiencies]

    @extend_schema(
        parameters=[
            OpenApiParameter(name=f, description=f"Exact match on {f}", required=False, type=str)
            for f in FILTERS
        ]
        + [OpenApiParameter(name="search", description="Free text over the deficiency body and classification", required=False, type=str)],
        responses=DeficiencyRecordSerializer(many=True),
    )
    def get(self, request):
        paginator = DeficiencyPagination()
        page = paginator.paginate_queryset(_filtered_queryset(request), request, view=self)
        return paginator.get_paginated_response(
            DeficiencyRecordSerializer(page, many=True).data
        )


class DeficiencyDetailView(APIView):
    permission_classes = [CanViewDeficiencies]

    @extend_schema(responses=DeficiencyRecordSerializer)
    def get(self, request, public_id):
        record = DeficiencyRecord.objects.filter(public_id=public_id).first()
        if record is None:
            raise NotFound("Deficiency record not found.")
        return Response(DeficiencyRecordSerializer(record).data)


class DeficiencyFacetsView(APIView):
    """Distinct filter values, derived from the loaded corpus.

    The legacy app hardcoded an 11-entry category tuple in the model, which drifts
    the moment a new roadmap is published. These are read from the data.
    """

    permission_classes = [CanViewDeficiencies]

    @extend_schema(responses=DeficiencyFacetsSerializer)
    def get(self, request):
        def distinct(field):
            # .order_by() clears Meta.ordering first. Without it Django adds the
            # ordering columns to the SELECT, so DISTINCT applies to the tuple
            # rather than the single column and every row comes back.
            return sorted(
                v
                for v in DeficiencyRecord.objects.order_by()
                .values_list(field, flat=True)
                .distinct()
                if v
            )

        return Response(
            DeficiencyFacetsSerializer(
                {
                    "corpora": distinct("corpus"),
                    "main_categories": distinct("main_category"),
                    "dosage_forms": distinct("dosage_form"),
                    "cmc_sections": distinct("cmc_section"),
                    "deficiency_types": distinct("deficiency_type"),
                }
            ).data
        )
