"""
FDA data-governance API views.

UUID-only identifiers; permission enforcement on every endpoint; a
missing/forbidden record returns a generic 404.
"""

import io
import json

from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import importer, lifecycle
from .adapters import fda_iid_adapter, orange_book_products_adapter
from .audit_events import FdaDataEvent, emit
from .models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    IIDPrecedentRecord,
    OrangeBookProduct,
)
from .permissions import (
    CanActivateFdaData,
    CanApproveFdaData,
    CanExportFdaReconciliation,
    CanImportFdaData,
    CanRegisterFdaData,
    CanViewFdaData,
    CanViewRawFdaData,
    has_fda_data_permission,
)
from .serializers import (
    ControlledDosageFormSerializer,
    ControlledRouteSerializer,
    ControlledUnitSerializer,
    FDADataSourceReleaseRawSerializer,
    FDADataSourceReleaseSerializer,
    FdaImportRowResultSerializer,
    IIDPrecedentRecordSerializer,
    OrangeBookProductSerializer,
    ReleaseRegistrationSerializer,
    ReviewActionSerializer,
)


class FdaDataPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_tenant(request):
    from rest_framework.exceptions import PermissionDenied

    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("No active tenant context.") from exc


def _can_view_raw(request, tenant) -> bool:
    return has_fda_data_permission(request.user, tenant, CanViewRawFdaData.required_codename)


def _get_release_or_404(public_id) -> FDADataSourceRelease:
    try:
        return FDADataSourceRelease.objects.get(public_id=public_id)
    except FDADataSourceRelease.DoesNotExist as exc:
        raise NotFound("FDA data source release not found.") from exc


class FdaReleaseListView(APIView):
    pagination_class = FdaDataPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanRegisterFdaData()]
        return [CanViewFdaData()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = FDADataSourceRelease.objects.all().order_by("-created_at")
        dataset_type = request.query_params.get("dataset_type")
        if dataset_type:
            qs = qs.filter(dataset_type=dataset_type)
        raw = _can_view_raw(request, tenant)
        serializer_class = (
            FDADataSourceReleaseRawSerializer if raw else FDADataSourceReleaseSerializer
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(serializer_class(page, many=True).data)

    def post(self, request):
        serializer = ReleaseRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rows = data["rows"]
        payload_bytes = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
        file_obj = io.BytesIO(payload_bytes)

        release = importer.register_release(
            dataset_type=data["dataset_type"],
            source_name=data["source_name"],
            official_source_reference=data["official_source_reference"],
            file_obj=file_obj,
            original_filename=data.get("file_name") or "synthetic-upload.json",
            media_type="application/json",
            schema_version=data.get("schema_version", ""),
            publication_date=data.get("publication_date"),
            imported_by=request.user,
        )

        if data["dataset_type"].startswith("orange_book"):
            neutral = orange_book_products_adapter(rows)
            importer.import_orange_book_rows(release, neutral, request.user)
        elif data["dataset_type"] == "fda_iid":
            neutral = fda_iid_adapter(rows)
            importer.import_iid_rows(release, neutral, request.user)

        release.refresh_from_db()
        return Response(
            FDADataSourceReleaseSerializer(release).data, status=status.HTTP_201_CREATED
        )


class FdaReleaseDetailView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        release = _get_release_or_404(public_id)
        raw = _can_view_raw(request, tenant)
        serializer_class = (
            FDADataSourceReleaseRawSerializer if raw else FDADataSourceReleaseSerializer
        )
        return Response(serializer_class(release).data)


class _ReleaseActionView(APIView):
    required_permission_class = None

    def get_permissions(self):
        return [self.required_permission_class()]

    def post(self, request, public_id):
        release = _get_release_or_404(public_id)
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = self.run_action(release, request.user, serializer.validated_data)
        except lifecycle.InvalidTransition as exc:
            raise ValidationError(str(exc)) from exc
        return Response(FDADataSourceReleaseSerializer(updated).data)

    def run_action(self, release, user, data):
        raise NotImplementedError


class FdaReleaseSubmitReviewView(_ReleaseActionView):
    required_permission_class = CanImportFdaData

    def run_action(self, release, user, data):
        return lifecycle.submit_for_review(release, user)


class FdaReleaseApproveView(_ReleaseActionView):
    required_permission_class = CanApproveFdaData

    def run_action(self, release, user, data):
        return lifecycle.approve(release, user, data.get("notes", ""))


class FdaReleaseActivateView(_ReleaseActionView):
    required_permission_class = CanActivateFdaData

    def run_action(self, release, user, data):
        return lifecycle.activate(release, user)


class FdaReleaseValidateView(APIView):
    """Schema/consistency check without transitioning status -- a no-op
    confirmation endpoint for the 'validated' checkpoint in the pipeline."""

    def get_permissions(self):
        return [CanImportFdaData()]

    def post(self, request, public_id):
        release = _get_release_or_404(public_id)
        emit(
            event_type=FdaDataEvent.SCHEMA_VALIDATED,
            resource_id=str(release.public_id),
            payload={"record_count_extracted": release.record_count_extracted},
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(FDADataSourceReleaseSerializer(release).data)


class FdaReleaseReconciliationJsonView(APIView):
    def get_permissions(self):
        return [CanExportFdaReconciliation()]

    def get(self, request, public_id):
        release = _get_release_or_404(public_id)
        from .models import FdaImportRowResult

        results = FdaImportRowResult.objects.filter(release=release)
        report = {
            "release": {
                "public_id": str(release.public_id),
                "dataset_type": release.dataset_type,
                "status": release.status,
            },
            "counts": {
                "expected": release.record_count_expected,
                "extracted": release.record_count_extracted,
                "imported": release.record_count_imported,
                "failed": release.record_count_failed,
            },
            "results": FdaImportRowResultSerializer(results, many=True).data,
        }
        emit(
            event_type=FdaDataEvent.RECONCILIATION_EXPORTED,
            resource_id=str(release.public_id),
            payload={"format": "json", "counts": report["counts"]},
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(report)


def _csv_safe_cell(value) -> str:
    text = "" if value is None else str(value)
    effective_first_char = text.lstrip(" ")[:1]
    if effective_first_char in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + text
    return text


class FdaReleaseReconciliationCsvView(APIView):
    def get_permissions(self):
        return [CanExportFdaReconciliation()]

    def get(self, request, public_id):
        import csv

        release = _get_release_or_404(public_id)
        from .models import FdaImportRowResult

        results = FdaImportRowResult.objects.filter(release=release)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["row_locator", "target_public_identifier", "result", "reason_code"])
        for r in results:
            writer.writerow(
                [
                    _csv_safe_cell(r.row_locator),
                    _csv_safe_cell(
                        str(r.target_public_identifier) if r.target_public_identifier else ""
                    ),
                    _csv_safe_cell(r.result),
                    _csv_safe_cell(r.reason_code),
                ]
            )
        emit(
            event_type=FdaDataEvent.RECONCILIATION_EXPORTED,
            resource_id=str(release.public_id),
            payload={"format": "csv"},
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="fda-reconciliation-{release.public_id}.csv"'
        )
        return response


class OrangeBookProductListView(APIView):
    pagination_class = FdaDataPagination

    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = OrangeBookProduct.objects.filter(release__status="active").order_by(
            "active_ingredient_raw"
        )
        ingredient = request.query_params.get("active_ingredient")
        route = request.query_params.get("route")
        dosage_form = request.query_params.get("dosage_form")
        if ingredient:
            qs = qs.filter(active_ingredient_raw__icontains=ingredient)
        if route:
            qs = qs.filter(route_normalized__code=route)
        if dosage_form:
            qs = qs.filter(dosage_form_normalized__code=dosage_form)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(OrangeBookProductSerializer(page, many=True).data)


class OrangeBookProductDetailView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request, public_id):
        try:
            product = OrangeBookProduct.objects.get(public_id=public_id)
        except OrangeBookProduct.DoesNotExist as exc:
            raise NotFound("Orange Book product not found.") from exc
        return Response(OrangeBookProductSerializer(product).data)


class IidRecordListView(APIView):
    pagination_class = FdaDataPagination

    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = IIDPrecedentRecord.objects.filter(release__status="active").order_by(
            "ingredient_name_raw"
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(IIDPrecedentRecordSerializer(page, many=True).data)


class IidRecordDetailView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request, public_id):
        try:
            record = IIDPrecedentRecord.objects.get(public_id=public_id)
        except IIDPrecedentRecord.DoesNotExist as exc:
            raise NotFound("IID precedent record not found.") from exc
        return Response(IIDPrecedentRecordSerializer(record).data)


class ControlledRouteListView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = ControlledRoute.objects.filter(lifecycle="active")
        return Response(ControlledRouteSerializer(qs, many=True).data)


class ControlledDosageFormListView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = ControlledDosageForm.objects.filter(lifecycle="active")
        return Response(ControlledDosageFormSerializer(qs, many=True).data)


class ControlledUnitListView(APIView):
    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = ControlledUnit.objects.filter(active=True)
        return Response(ControlledUnitSerializer(qs, many=True).data)
