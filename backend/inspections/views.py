"""FDA inspection corpus API.

Read-only over HTTP. The corpus is published FDA material, loaded by the
`import_inspections` management command; there is no API write path.

Follows the deficiencies and regulatory_cases apps: explicit permission classes,
tenant resolved via `current_tenant()`, public UUIDs only.
"""

from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Form483Inspection,
    Form483Observation,
    Form483System,
    WarningLetter,
)
from .permissions import CanViewInspections
from .serializers import (
    Form483InspectionDetailSerializer,
    Form483InspectionSerializer,
    Form483ObservationSerializer,
    InspectionFacetsSerializer,
    WarningLetterSerializer,
)


class InspectionsPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def _date_range(qs, request, field):
    """Apply `year`, `date_from` and `date_to` against `field`.

    Year is derived from the date rather than read from a stored column: the
    legacy schema kept `year_of_inspection` as a separate CharField, which let
    the two disagree on rows where one was edited and the other was not.
    """
    year = request.query_params.get("year")
    if year and year.isdigit():
        qs = qs.filter(**{f"{field}__year": int(year)})
    date_from = request.query_params.get("date_from")
    if date_from:
        qs = qs.filter(**{f"{field}__gte": date_from})
    date_to = request.query_params.get("date_to")
    if date_to:
        qs = qs.filter(**{f"{field}__lte": date_to})
    return qs


class Form483ListView(APIView):
    permission_classes = [CanViewInspections]

    @extend_schema(
        parameters=[
            OpenApiParameter("company_name", str, description="Case-insensitive contains"),
            OpenApiParameter("investigator_name", str, description="Case-insensitive contains"),
            OpenApiParameter("type_of_establishment", str, description="Exact match"),
            OpenApiParameter("system", str, description="Inspections citing this quality system"),
            OpenApiParameter("year", int),
            OpenApiParameter("date_from", str),
            OpenApiParameter("date_to", str),
        ],
        responses=Form483InspectionSerializer(many=True),
    )
    def get(self, request):
        qs = Form483Inspection.objects.annotate(
            observation_count=Count("systems__observations", distinct=True)
        )
        p = request.query_params
        if p.get("company_name"):
            qs = qs.filter(company_name__icontains=p["company_name"])
        if p.get("investigator_name"):
            qs = qs.filter(investigator_name__icontains=p["investigator_name"])
        if p.get("type_of_establishment"):
            qs = qs.filter(type_of_establishment=p["type_of_establishment"])
        if p.get("system"):
            qs = qs.filter(systems__system=p["system"]).distinct()
        qs = _date_range(qs, request, "date_of_inspection")

        # annotate() clears Meta.ordering, and an unordered queryset paginates
        # inconsistently -- the same row can appear on two pages, or on none.
        qs = qs.order_by("-date_of_inspection", "company_name", "id")

        paginator = InspectionsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(Form483InspectionSerializer(page, many=True).data)


class Form483DetailView(APIView):
    permission_classes = [CanViewInspections]

    @extend_schema(responses=Form483InspectionDetailSerializer)
    def get(self, request, public_id):
        inspection = (
            Form483Inspection.objects.filter(public_id=public_id)
            .annotate(observation_count=Count("systems__observations", distinct=True))
            .prefetch_related("systems__observations")
            .first()
        )
        if inspection is None:
            raise NotFound("Inspection not found.")
        return Response(Form483InspectionDetailSerializer(inspection).data)


class ObservationSearchView(APIView):
    """Free-text search across observation narratives.

    This is the feature the legacy app implemented by asking an LLM to expand the
    query into synonyms before searching. That call is not reproduced: it made a
    paid API request on every keystroke-driven search, and when it failed the
    caller silently fell back to matching nothing. Plain database search is the
    baseline; query expansion can be layered on deliberately later.
    """

    permission_classes = [CanViewInspections]

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Text within the observation"),
            OpenApiParameter("system", str),
            OpenApiParameter("company_name", str),
        ],
        responses=Form483ObservationSerializer(many=True),
    )
    def get(self, request):
        qs = Form483Observation.objects.select_related("system", "system__inspection")
        p = request.query_params
        term = (p.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(content__icontains=term) | Q(summary__icontains=term))
        if p.get("system"):
            qs = qs.filter(system__system=p["system"])
        if p.get("company_name"):
            qs = qs.filter(system__inspection__company_name__icontains=p["company_name"])

        paginator = InspectionsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(Form483ObservationSerializer(page, many=True).data)


class WarningLetterListView(APIView):
    permission_classes = [CanViewInspections]

    @extend_schema(
        parameters=[
            OpenApiParameter("company_name", str),
            OpenApiParameter("country", str),
            OpenApiParameter("search", str, description="Text within the letter body"),
            OpenApiParameter("year", int),
            OpenApiParameter("date_from", str),
            OpenApiParameter("date_to", str),
        ],
        responses=WarningLetterSerializer(many=True),
    )
    def get(self, request):
        qs = WarningLetter.objects.all()
        p = request.query_params
        if p.get("company_name"):
            qs = qs.filter(company_name__icontains=p["company_name"])
        if p.get("country"):
            qs = qs.filter(country=p["country"])
        if p.get("search"):
            qs = qs.filter(Q(body__icontains=p["search"]) | Q(summary__icontains=p["search"]))
        qs = _date_range(qs, request, "date_of_issue")

        paginator = InspectionsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(WarningLetterSerializer(page, many=True).data)


class WarningLetterDetailView(APIView):
    permission_classes = [CanViewInspections]

    @extend_schema(responses=WarningLetterSerializer)
    def get(self, request, public_id):
        letter = WarningLetter.objects.filter(public_id=public_id).first()
        if letter is None:
            raise NotFound("Warning letter not found.")
        return Response(WarningLetterSerializer(letter).data)


class InspectionFacetsView(APIView):
    permission_classes = [CanViewInspections]

    @extend_schema(responses=InspectionFacetsSerializer)
    def get(self, request):
        def distinct(model, field):
            # .order_by() first: Meta.ordering otherwise joins the SELECT and
            # DISTINCT then applies to the tuple, returning one entry per row.
            return sorted(
                v for v in model.objects.order_by().values_list(field, flat=True).distinct() if v
            )

        years = sorted(
            {
                d.year
                for d in Form483Inspection.objects.order_by()
                .values_list("date_of_inspection", flat=True)
                .distinct()
                if d
            },
            reverse=True,
        )
        return Response(
            InspectionFacetsSerializer(
                {
                    "companies": distinct(Form483Inspection, "company_name"),
                    "systems": distinct(Form483System, "system"),
                    "investigators": distinct(Form483Inspection, "investigator_name"),
                    "establishment_types": distinct(Form483Inspection, "type_of_establishment"),
                    "years": years,
                }
            ).data
        )
