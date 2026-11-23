"""
FDA data-governance API views.

UUID-only identifiers; permission enforcement on every endpoint; a
missing/forbidden record returns a generic 404.
"""

import io
import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import importer, lifecycle, reresolve
from .audit_events import FdaDataEvent, emit
from .dispatch import SUPPORTED_IMPORTERS, UnsupportedDatasetType, resolve_importer
from .mapping_transitions import MappingAction
from .models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    OrangeBookProduct,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)
from .permissions import (
    CanActivateFdaData,
    CanApproveFdaData,
    CanExportFdaReconciliation,
    CanImportFdaData,
    CanProposeSubstanceMapping,
    CanRegisterFdaData,
    CanReviewFdaData,
    CanViewFdaData,
    CanViewRawFdaData,
    has_fda_data_permission,
)
from .serializers import (
    MAPPING_TYPE_CONFIG,
    ControlledDosageFormSerializer,
    ControlledRouteSerializer,
    ControlledUnitSerializer,
    FDADataSourceReleaseRawSerializer,
    FDADataSourceReleaseSerializer,
    FdaImportRowResultSerializer,
    IIDPrecedentRecordSerializer,
    MappingReviewActionSerializer,
    OrangeBookProductSerializer,
    ReleaseRegistrationSerializer,
    ReviewActionSerializer,
    SubstanceMappingProposalSerializer,
    TerminologyMappingSerializer,
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

        # Resolved BEFORE anything is written. An unsupported dataset type
        # used to reach this point, register a release and return 201 with
        # zero rows imported -- a success response for work that did not
        # happen. Nothing is created unless an importer actually exists.
        try:
            adapter, import_rows = resolve_importer(data["dataset_type"])
        except UnsupportedDatasetType as exc:
            return Response(
                {
                    "error_code": "unsupported_dataset_type",
                    "dataset_type": exc.dataset_type,
                    "detail": exc.reason,
                    "supported_dataset_types": sorted(SUPPORTED_IMPORTERS),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = data["rows"]
        payload_bytes = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
        file_obj = io.BytesIO(payload_bytes)

        # The same payload used to return the existing release with 201 after
        # a no-op import, which looked like a successful new import.
        # The same data in any form is refused: same bytes, or the same
        # normalised content (owner decision 2026-11-18). A deliberate
        # re-import is a management-command action only.
        from .checksums import content_fingerprint

        neutral = adapter(rows)
        fingerprint = content_fingerprint([n["fields"] for n in neutral])
        duplicate = importer.find_imported_duplicate(
            data["dataset_type"], file_obj, content_fingerprint=fingerprint
        )
        if duplicate:
            return Response(
                {
                    "error_code": "duplicate_release",
                    "detail": (
                        "The same rows are already imported as release "
                        f"{duplicate.public_id} (status: {duplicate.status}). Nothing was changed."
                    ),
                    "existing_release_public_id": str(duplicate.public_id),
                    "existing_release_status": duplicate.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
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
                content_fingerprint=fingerprint,
            )
        except importer.DuplicateReleaseContent:
            # QA-10: another request with the same rows passed the check above
            # at the same time and was registered first.
            return Response(
                {
                    "error_code": "duplicate_release",
                    "detail": (
                        "The same rows were registered by another request at the same "
                        "time. Nothing was changed."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Explicit, resolved above. The previous
        # `dataset_type.startswith("orange_book")` routed patents and
        # exclusivity through the PRODUCTS adapter, which turned a patent row
        # into an OrangeBookProduct with an empty ingredient and strength and
        # counted it as imported.
        import_rows(release, neutral, request.user)

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
        except lifecycle.SeparationOfDutiesError as exc:
            return Response(
                {"detail": str(exc), "error_code": exc.error_code},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(FDADataSourceReleaseSerializer(updated).data)

    def run_action(self, release, user, data):
        raise NotImplementedError


class FdaReleaseSubmitReviewView(_ReleaseActionView):
    """Submitting an IID release whose records still lack a route or dosage-form
    link needs `confirm_unmapped: true`. After submission the release can no
    longer be re-resolved (`reresolve.py`), so those records stay unmatched for
    the life of the release."""

    required_permission_class = CanImportFdaData

    def post(self, request, public_id):
        release = _get_release_or_404(public_id)
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unmapped = reresolve.count_unmapped(release)
        if unmapped and not serializer.validated_data["confirm_unmapped"]:
            return Response(
                {
                    "error_code": "unmapped_rows",
                    "unmapped_count": unmapped,
                    "detail": (
                        f"{unmapped} record(s) have no route or dosage-form link. After "
                        "submission they can no longer be re-resolved. Approve the missing "
                        "mappings and run reresolve_terminology first, or resubmit with "
                        '"confirm_unmapped": true.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            updated = lifecycle.submit_for_review(
                release,
                request.user,
                extra_payload={"unmapped_rows_confirmed": unmapped} if unmapped else None,
            )
        except lifecycle.InvalidTransition as exc:
            raise ValidationError(str(exc)) from exc
        body = FDADataSourceReleaseSerializer(updated).data
        if unmapped:
            body = {**body, "warning": f"Submitted with {unmapped} unmapped record(s)."}
        return Response(body)


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


_APPLICATION_PREFIXES = (("ANDA", "A"), ("NDA", "N"), ("A", "A"), ("N", "N"))


def _parse_application_number(value: str) -> tuple[str | None, str | None]:
    """Split user input such as "212379", "N212379", "NDA212379" or "ANDA 210928"
    into (application_type or None, six-digit number or None).

    The Orange Book stores the number zero-padded to six digits ("040603"), so a
    shorter all-digit value is padded. Anything that is not an optional N/A/NDA/
    ANDA prefix followed by digits returns (None, None): no match, never a guess.
    """
    text = value.strip().upper().replace(" ", "")
    app_type = None
    for prefix, code in _APPLICATION_PREFIXES:
        if text.startswith(prefix) and text[len(prefix) :].isdigit():
            app_type, text = code, text[len(prefix) :]
            break
    if not text.isdigit() or len(text) > 6:
        return None, None
    return app_type, text.zfill(6)


class OrangeBookProductListView(APIView):
    pagination_class = FdaDataPagination

    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        qs = OrangeBookProduct.objects.filter(release__status="active").order_by(
            "active_ingredient_raw"
        )
        params = request.query_params
        ingredient = params.get("active_ingredient")
        route = params.get("route")
        dosage_form = params.get("dosage_form")
        strength = params.get("strength")
        application_type = params.get("application_type")
        rld = params.get("rld")
        reference_standard = params.get("reference_standard")
        discontinued = params.get("discontinued")
        trade_name = params.get("trade_name")
        application_number = params.get("application_number")
        if ingredient:
            qs = qs.filter(active_ingredient_raw__icontains=ingredient)
        if trade_name:
            qs = qs.filter(trade_name__icontains=trade_name.strip())
        if application_number:
            app_type, number = _parse_application_number(application_number)
            if number is None:
                qs = qs.none()
            else:
                qs = qs.filter(application__application_number=number)
                if app_type:
                    qs = qs.filter(application__application_type=app_type)
        if route:
            qs = qs.filter(route_normalized__code=route)
        if dosage_form:
            qs = qs.filter(dosage_form_normalized__code=dosage_form)
        if strength:
            qs = qs.filter(strength_raw__icontains=strength)
        if application_type:
            qs = qs.filter(application__application_type=application_type)
        truthy = ("1", "true", "yes")
        if rld is not None:
            qs = qs.filter(rld_flag=rld.lower() in truthy)
        if reference_standard is not None:
            qs = qs.filter(reference_standard_flag=reference_standard.lower() in truthy)
        if discontinued is not None:
            qs = qs.filter(discontinued=discontinued.lower() in truthy)
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


class ControlledUnitMeaningListView(APIView):
    """The quantity meanings a formulation may state (controlled units,
    increment 4): every meaning listed by the ACTIVE controlled-units release,
    except per-day ones (those need the Q8 rule). Empty when no unit list is in
    force. Read-only; platform-level reference data."""

    def get_permissions(self):
        return [CanViewFdaData()]

    def get(self, request):
        from .controlled_units import active_release, in_force_meanings

        release = active_release()
        return Response(
            {
                "unit_list_release_public_id": str(release.public_id) if release else None,
                "meanings": [
                    {
                        "public_id": str(e.public_id),
                        "label": str(e),
                        "family": e.family,
                        "basis": e.basis,
                        "numerator_unit": e.numerator_unit.code if e.numerator_unit_id else None,
                    }
                    for e in in_force_meanings()
                ],
            }
        )


def _affected_record_count(mapping_type: str, mapping) -> int:
    """Best-effort count of records referencing this raw value -- used only
    to inform a reviewer's decision, never to gate it."""
    from django.db.models import Q

    if mapping_type == "substance":
        from .substance_matching import affected_record_count

        return affected_record_count(mapping)
    source_raw_value = mapping.source_raw_value
    if mapping_type == "route":
        return (
            OrangeBookProduct.objects.filter(route_raw=source_raw_value).count()
            + IIDPrecedentRecord.objects.filter(route_raw=source_raw_value).count()
        )
    if mapping_type == "dosage_form":
        return (
            OrangeBookProduct.objects.filter(dosage_form_raw=source_raw_value).count()
            + IIDPrecedentRecord.objects.filter(dosage_form_raw=source_raw_value).count()
        )
    if mapping_type == "unit":
        return IIDPrecedentRecord.objects.filter(
            Q(potency_unit_raw=source_raw_value) | Q(mde_unit_raw=source_raw_value)
        ).count()
    return 0


def _affected_records_page(mapping_type: str, mapping) -> list[dict]:
    """Safe, paginated-by-caller list of records referencing this mapping's
    raw value -- public IDs and safe fields only, never storage keys,
    filesystem paths, or numeric IDs."""
    from django.db.models import Q

    results = []
    if mapping_type == "substance":
        qs = IIDPrecedentRecord.objects.filter(
            ingredient_name_raw=mapping.raw_ingredient_name
        ).select_related("release")
        for record in qs:
            results.append(
                {
                    "record_public_id": str(record.public_id),
                    "dataset_type": record.release.dataset_type,
                    "release_public_id": str(record.release.public_id),
                    "source_row_locator": record.source_row_locator,
                    "raw_value": record.ingredient_name_raw,
                    "normalized_value": (
                        record.ingredient.canonical_name if record.ingredient else None
                    ),
                    "mapping_status": mapping.status,
                    "calculability_status": record.calculability_status,
                    "blocked": record.calculability_status != "calculable",
                    "reason_code": record.calculability_status,
                }
            )
        return results

    source_raw_value = mapping.source_raw_value
    if mapping_type in ("route", "dosage_form"):
        field = "route_raw" if mapping_type == "route" else "dosage_form_raw"
        iid_qs = IIDPrecedentRecord.objects.filter(**{field: source_raw_value}).select_related(
            "release"
        )
        for record in iid_qs:
            results.append(
                {
                    "record_public_id": str(record.public_id),
                    "dataset_type": record.release.dataset_type,
                    "release_public_id": str(record.release.public_id),
                    "source_row_locator": record.source_row_locator,
                    "raw_value": getattr(record, field),
                    "normalized_value": (
                        record.route_normalized.canonical_label
                        if mapping_type == "route" and record.route_normalized
                        else record.dosage_form_normalized.canonical_label
                        if mapping_type == "dosage_form" and record.dosage_form_normalized
                        else None
                    ),
                    "mapping_status": mapping.status,
                    "calculability_status": record.calculability_status,
                    "blocked": record.calculability_status != "calculable",
                    "reason_code": record.calculability_status,
                }
            )
        ob_qs = OrangeBookProduct.objects.filter(**{field: source_raw_value}).select_related(
            "release"
        )
        for product in ob_qs:
            results.append(
                {
                    "record_public_id": str(product.public_id),
                    "dataset_type": product.release.dataset_type,
                    "release_public_id": str(product.release.public_id),
                    "source_row_locator": product.source_row_locator,
                    "raw_value": getattr(product, field),
                    "normalized_value": None,
                    "mapping_status": mapping.status,
                    "calculability_status": None,
                    "blocked": False,
                    "reason_code": "",
                }
            )
    elif mapping_type == "unit":
        qs = IIDPrecedentRecord.objects.filter(
            Q(potency_unit_raw=source_raw_value) | Q(mde_unit_raw=source_raw_value)
        ).select_related("release")
        for record in qs:
            results.append(
                {
                    "record_public_id": str(record.public_id),
                    "dataset_type": record.release.dataset_type,
                    "release_public_id": str(record.release.public_id),
                    "source_row_locator": record.source_row_locator,
                    "raw_value": record.potency_unit_raw or record.mde_unit_raw,
                    "normalized_value": (
                        record.potency_unit_normalized.code
                        if record.potency_unit_normalized
                        else None
                    ),
                    "mapping_status": mapping.status,
                    "calculability_status": record.calculability_status,
                    "blocked": record.calculability_status != "calculable",
                    "reason_code": record.calculability_status,
                }
            )
    return results


def _find_mapping_or_404(public_id) -> tuple[str, object]:
    """Resolve a mapping public_id to (mapping_type, instance) by checking
    each governed mapping model in turn -- UUIDs are unique across all of
    them in practice, so exactly one (or zero) will match."""
    for mapping_type, (model_cls, *_rest) in MAPPING_TYPE_CONFIG.items():
        instance = model_cls.objects.select_related("reviewer").filter(public_id=public_id).first()
        if instance is not None:
            return mapping_type, instance
    raise NotFound("Terminology mapping not found.")


def _get_mapping_or_404(mapping_type: str, public_id):
    model_cls, _, _, _, _ = MAPPING_TYPE_CONFIG.get(mapping_type, (None, None, None, None, None))
    if model_cls is None:
        raise NotFound("Unknown mapping type.")
    try:
        return model_cls.objects.select_related("reviewer").get(public_id=public_id)
    except model_cls.DoesNotExist as exc:
        raise NotFound("Terminology mapping not found.") from exc


class TerminologyMappingListView(APIView):
    """Read-only inventory across route/dosage-form/unit/substance
    mappings, unified into one shape for the mapping-review UI. Filter by
    ?type=, ?status=, ?release=, ?raw_value=, ?reviewer= (all optional;
    omitting type returns every kind)."""

    pagination_class = FdaDataPagination

    def get_permissions(self):
        return [CanReviewFdaData()]

    def get(self, request):
        params = request.query_params
        type_filter = params.get("type")
        status_filter = params.get("status")
        release_filter = params.get("release")
        raw_value_filter = params.get("raw_value")
        reviewer_filter = params.get("reviewer")
        types = [type_filter] if type_filter else list(MAPPING_TYPE_CONFIG.keys())

        results = []
        for mapping_type in types:
            config = MAPPING_TYPE_CONFIG.get(mapping_type)
            if config is None:
                continue
            model_cls, _, _, raw_value_attr, _ = config
            qs = model_cls.objects.select_related("reviewer").order_by("-created_at")
            if status_filter:
                qs = qs.filter(status=status_filter)
            if release_filter and hasattr(model_cls, "release"):
                qs = qs.filter(release__public_id=release_filter)
            if raw_value_filter:
                qs = qs.filter(**{f"{raw_value_attr}__icontains": raw_value_filter})
            if reviewer_filter:
                qs = qs.filter(reviewer__email__iexact=reviewer_filter)
            for instance in qs:
                results.append(
                    TerminologyMappingSerializer.from_instance(
                        mapping_type,
                        instance,
                        _affected_record_count(mapping_type, instance),
                    )
                )
        results.sort(key=lambda r: r["created_at"], reverse=True)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(results, request)
        return paginator.get_paginated_response(page)


class TerminologyMappingDetailView(APIView):
    def get_permissions(self):
        return [CanReviewFdaData()]

    def get(self, request, public_id):
        mapping_type, mapping = _find_mapping_or_404(public_id)
        return Response(
            TerminologyMappingSerializer.from_instance(
                mapping_type, mapping, _affected_record_count(mapping_type, mapping)
            )
        )


class SubstanceMappingProposalView(APIView):
    """The production entry point for creating a new PROPOSED
    SubstanceSynonymMapping. Before this endpoint existed, nothing in the
    shipped application could ever create one -- the entire substance
    mapping-review lifecycle was reachable only by inserting a row
    directly via the Django ORM/shell. See
    docs/HUMAN_REVIEW_PR5_REMEDIATION.md (HR-02).

    Always creates status=PROPOSED -- the request body has no status
    field, so there is no way to submit a pre-approved row. Requires
    fda_data.import or fda_data.review (CanProposeSubstanceMapping);
    ordinary tenant users cannot reach this at all (fda_data has no
    tenant-scoped permission path)."""

    def get_permissions(self):
        return [CanProposeSubstanceMapping()]

    def post(self, request):
        from django.db import IntegrityError, transaction

        from .substance_matching import affected_record_count

        serializer = SubstanceMappingProposalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        release = None
        release_public_id = data.get("release_public_id")
        if release_public_id:
            try:
                release = FDADataSourceRelease.objects.get(public_id=release_public_id)
            except FDADataSourceRelease.DoesNotExist as exc:
                raise NotFound("FDA release not found.") from exc
            if release.status not in (FDAReleaseStatus.APPROVED, FDAReleaseStatus.ACTIVE):
                raise ValidationError(
                    "This release is not in a usable status for new mapping proposals."
                )

        proposed_ingredient = None
        ingredient_public_id = data.get("proposed_ingredient_public_id")
        if ingredient_public_id:
            try:
                proposed_ingredient = IIDIngredient.objects.get(public_id=ingredient_public_id)
            except IIDIngredient.DoesNotExist as exc:
                raise ValidationError("Proposed canonical ingredient not found.") from exc

        mapping = SubstanceSynonymMapping(
            release=release,
            source_dataset="fda_iid",
            raw_ingredient_name=data["raw_ingredient_name"],
            normalized_ingredient_name=data["normalized_ingredient_name"],
            raw_unii=data.get("raw_unii", "") or "",
            raw_cas_number=data.get("raw_cas_number", "") or "",
            source_row_locator=data.get("source_row_locator", "") or "",
            proposed_ingredient=proposed_ingredient,
            proposed_unii=data.get("proposed_unii", "") or "",
            proposed_cas_number=data.get("proposed_cas_number", "") or "",
            mapping_method=data["mapping_method"],
            review_reason=data.get("reason", "") or "",
            status=SubstanceMappingStatus.PROPOSED,
        )
        try:
            mapping.full_clean()
        except DjangoValidationError as exc:
            raise ValidationError(str(exc)) from exc

        try:
            with transaction.atomic():
                mapping.save()
        except IntegrityError as exc:
            raise ValidationError(
                "A current mapping already exists for this raw identity in this release."
            ) from exc

        emit(
            event_type=FdaDataEvent.SUBSTANCE_MAPPING_CANDIDATE_CREATED,
            resource_type="fda_data_mapping",
            resource_id=str(mapping.public_id),
            payload={
                "mapping_type": "substance",
                "release_public_id": str(release.public_id) if release else None,
                "normalized_ingredient_name": mapping.normalized_ingredient_name,
                "mapping_method": mapping.mapping_method,
                "affected_record_count": affected_record_count(mapping),
            },
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(
            TerminologyMappingSerializer.from_instance(
                "substance", mapping, affected_record_count(mapping)
            ),
            status=status.HTTP_201_CREATED,
        )


class _MappingActionViewBase(APIView):
    """Shared action plumbing for submit-review/approve/reject/return.

    Every transition is validated against validate_mapping_transition()
    (fda_data/mapping_transitions.py) -- the single authoritative lifecycle
    source of truth for all four mapping types. An action that is not legal
    from the mapping's CURRENT status (e.g. approving a still-PROPOSED or
    REJECTED mapping, never having gone through submit-review) fails
    closed with a structured 400 and the mapping is left completely
    unchanged -- no partial mutation, no audit event. See
    docs/HUMAN_REVIEW_PR5_REMEDIATION.md (HR-01).

    The row is re-fetched with select_for_update() inside a transaction so
    two concurrent actions against the same mapping can never both
    "succeed" and leave inconsistent provenance."""

    action: str = ""
    event_type: str = ""
    self_approval_forbidden: bool = False
    required_permission = CanReviewFdaData

    def get_permissions(self):
        return [self.required_permission()]

    def post(self, request, public_id):
        from django.db import transaction
        from django.utils import timezone

        from .mapping_transitions import IllegalMappingTransition, validate_mapping_transition

        mapping_type, _ = _find_mapping_or_404(public_id)
        model_cls, _, _, _, reason_attr = MAPPING_TYPE_CONFIG[mapping_type]
        serializer = MappingReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            try:
                mapping = model_cls.objects.select_for_update().get(public_id=public_id)
            except model_cls.DoesNotExist as exc:
                raise NotFound("Terminology mapping not found.") from exc

            try:
                target_status = validate_mapping_transition(
                    mapping_type, mapping.status, self.action
                )
            except IllegalMappingTransition as exc:
                raise ValidationError(str(exc)) from exc

            if self.self_approval_forbidden and mapping.reviewer_id == request.user.id:
                raise ValidationError("A reviewer cannot approve a mapping they already reviewed.")

            reason = serializer.validated_data.get("reason")
            if reason:
                setattr(mapping, reason_attr, reason)

            mapping.status = target_status
            now = timezone.now()
            if self.action == MappingAction.SUBMIT_REVIEW:
                # reviewer/reviewed_at record who moved this into review --
                # never touched again by a later approve/reject/return.
                mapping.reviewer = request.user
                if hasattr(mapping, "reviewed_at"):
                    mapping.reviewed_at = now
            elif self.action == MappingAction.APPROVE and hasattr(mapping, "approved_by"):
                mapping.approved_by = request.user
                mapping.approved_at = now
            elif self.action == MappingAction.REJECT:
                if hasattr(mapping, "rejected_by"):
                    mapping.rejected_by = request.user
                    mapping.rejected_at = now
                elif not mapping.reviewer_id:
                    # Legacy route/dosage_form/unit mappings have no
                    # dedicated rejected_by field; only fall back to
                    # reviewer here if nothing already recorded a reviewer
                    # (i.e. this reject is a direct PROPOSED->REJECTED,
                    # never went through submit-review).
                    mapping.reviewer = request.user
            elif self.action == MappingAction.RETURN and hasattr(mapping, "returned_by"):
                mapping.returned_by = request.user
                mapping.returned_at = now

            try:
                mapping.full_clean()
            except DjangoValidationError as exc:
                raise ValidationError(str(exc)) from exc
            mapping.save()

        emit(
            event_type=self.event_type,
            resource_type="fda_data_mapping",
            resource_id=str(mapping.public_id),
            payload={
                "mapping_type": mapping_type,
                "new_status": target_status,
            },
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(
            TerminologyMappingSerializer.from_instance(
                mapping_type, mapping, _affected_record_count(mapping_type, mapping)
            )
        )


class TerminologyMappingSubmitReviewView(_MappingActionViewBase):
    action = MappingAction.SUBMIT_REVIEW
    event_type = FdaDataEvent.MAPPING_SUBMITTED_FOR_REVIEW


class TerminologyMappingApproveView(_MappingActionViewBase):
    action = MappingAction.APPROVE
    event_type = FdaDataEvent.MAPPING_APPROVED
    self_approval_forbidden = True
    required_permission = CanApproveFdaData


class TerminologyMappingRejectView(_MappingActionViewBase):
    action = MappingAction.REJECT
    event_type = FdaDataEvent.MAPPING_REJECTED


class TerminologyMappingReturnView(_MappingActionViewBase):
    action = MappingAction.RETURN
    event_type = FdaDataEvent.MAPPING_RETURNED


class TerminologyMappingAffectedRecordsView(APIView):
    pagination_class = FdaDataPagination

    def get_permissions(self):
        return [CanReviewFdaData()]

    def get(self, request, public_id):
        mapping_type, mapping = _find_mapping_or_404(public_id)
        records = _affected_records_page(mapping_type, mapping)
        records.sort(key=lambda r: r["record_public_id"])
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(records, request)
        return paginator.get_paginated_response(page)
