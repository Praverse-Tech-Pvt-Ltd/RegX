"""
Template registry governance/migration API views.

UUID-only identifiers throughout; tenant and permission enforcement on
every endpoint; a missing/forbidden record returns a generic 404 (never
distinguishing "doesn't exist" from "exists in another tenant").
"""

from django.db import transaction
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import importer, lifecycle, reconciliation
from .models import (
    MigrationBatch,
    RegulatoryTemplate,
    TemplateDuplicateCandidate,
    TemplateItem,
    TemplateSection,
    TemplateSourcePackage,
    TemplateVersion,
)
from .permissions import (
    CanActivate,
    CanApprove,
    CanExportReconciliation,
    CanImportSources,
    CanInventorySources,
    CanRetire,
    CanReview,
    CanSupersede,
    CanViewRawSource,
    CanViewTemplates,
    has_template_permission,
    user_roles_in_tenant,
)
from .serializers import (
    MigrationBatchCreateSerializer,
    MigrationBatchReviewSerializer,
    MigrationBatchSerializer,
    MigrationRecordResultSerializer,
    RegulatoryTemplateSerializer,
    ReviewActionSerializer,
    TemplateItemRawSerializer,
    TemplateItemSerializer,
    TemplateSectionRawSerializer,
    TemplateSectionSerializer,
    TemplateSourcePackageCreateSerializer,
    TemplateSourcePackageRawSerializer,
    TemplateSourcePackageSerializer,
    TemplateVersionRawSerializer,
    TemplateVersionSerializer,
)


def _get_tenant(request):
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("No active tenant context.") from exc


def _can_view_raw(request, tenant) -> bool:
    return has_template_permission(request.user, tenant, CanViewRawSource.required_codename)


def _get_template_or_404(public_id, tenant) -> RegulatoryTemplate:
    try:
        return RegulatoryTemplate.objects.for_tenant_including_platform(tenant).get(
            public_id=public_id
        )
    except RegulatoryTemplate.DoesNotExist as exc:
        raise NotFound("Template not found.") from exc


def _get_version_or_404(template, version_public_id) -> TemplateVersion:
    try:
        return template.versions.get(public_id=version_public_id)
    except TemplateVersion.DoesNotExist as exc:
        raise NotFound("Template version not found.") from exc


def _get_source_package_or_404(public_id, tenant) -> TemplateSourcePackage:
    try:
        return TemplateSourcePackage.objects.for_tenant_including_platform(tenant).get(
            public_id=public_id
        )
    except TemplateSourcePackage.DoesNotExist as exc:
        raise NotFound("Source package not found.") from exc


def _get_batch_or_404(public_id, tenant) -> MigrationBatch:
    try:
        return MigrationBatch.objects.for_tenant_including_platform(tenant).get(public_id=public_id)
    except MigrationBatch.DoesNotExist as exc:
        raise NotFound("Migration batch not found.") from exc


def _role_at_time(request, tenant) -> str:
    roles = user_roles_in_tenant(request.user, tenant)
    return roles[0] if roles else ""


class TemplatePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@extend_schema_view(get=extend_schema(summary="List regulatory templates", tags=["Templates"]))
class TemplateListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = RegulatoryTemplate.objects.for_tenant_including_platform(tenant).order_by(
            "canonical_code"
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(lifecycle_status=status_filter)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(RegulatoryTemplateSerializer(page, many=True).data)


@extend_schema_view(get=extend_schema(summary="Retrieve a regulatory template", tags=["Templates"]))
class TemplateDetailView(APIView):
    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        return Response(RegulatoryTemplateSerializer(template).data)


@extend_schema_view(get=extend_schema(summary="List versions of a template", tags=["Templates"]))
class TemplateVersionListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        qs = template.versions.order_by("-version_number")
        raw = _can_view_raw(request, tenant)
        serializer_class = TemplateVersionRawSerializer if raw else TemplateVersionSerializer
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(serializer_class(page, many=True).data)


@extend_schema_view(get=extend_schema(summary="Retrieve a template version", tags=["Templates"]))
class TemplateVersionDetailView(APIView):
    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        version = _get_version_or_404(template, version_public_id)
        raw = _can_view_raw(request, tenant)
        serializer_class = TemplateVersionRawSerializer if raw else TemplateVersionSerializer
        return Response(serializer_class(version).data)


@extend_schema_view(
    get=extend_schema(summary="List sections in a template version", tags=["Templates"])
)
class TemplateSectionListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        version = _get_version_or_404(template, version_public_id)
        qs = TemplateSection.objects.filter(template_version=version).order_by("display_order")
        raw = _can_view_raw(request, tenant)
        serializer_class = TemplateSectionRawSerializer if raw else TemplateSectionSerializer
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(serializer_class(page, many=True).data)


@extend_schema_view(
    get=extend_schema(summary="List items in a template version", tags=["Templates"])
)
class TemplateItemListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        version = _get_version_or_404(template, version_public_id)
        qs = TemplateItem.objects.filter(template_section__template_version=version).order_by(
            "template_section__display_order", "display_order"
        )
        raw = _can_view_raw(request, tenant)
        serializer_class = TemplateItemRawSerializer if raw else TemplateItemSerializer
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(serializer_class(page, many=True).data)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


class _VersionActionView(APIView):
    action_fn = None
    required_permission_class = None

    def get_permissions(self):
        return [self.required_permission_class()]

    def post(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        template = _get_template_or_404(public_id, tenant)
        version = _get_version_or_404(template, version_public_id)
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role_at_time = _role_at_time(request, tenant)
        try:
            updated = self.run_action(
                version, request.user, serializer.validated_data, role_at_time
            )
        except lifecycle.InvalidTransition as exc:
            raise ValidationError(str(exc)) from exc
        raw = _can_view_raw(request, tenant)
        serializer_class = TemplateVersionRawSerializer if raw else TemplateVersionSerializer
        return Response(serializer_class(updated).data)

    def run_action(self, version, user, data, role_at_time):
        raise NotImplementedError


@extend_schema_view(post=extend_schema(summary="Submit a version for review", tags=["Templates"]))
class TemplateVersionSubmitReviewView(_VersionActionView):
    required_permission_class = CanInventorySources

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.submit_for_review(version, user)


@extend_schema_view(post=extend_schema(summary="Approve a template version", tags=["Templates"]))
class TemplateVersionApproveView(_VersionActionView):
    required_permission_class = CanApprove

    def run_action(self, version, user, data, role_at_time):
        try:
            return lifecycle.approve(version, user, data.get("comments", ""), role_at_time)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc


@extend_schema_view(
    post=extend_schema(summary="Return a version for correction", tags=["Templates"])
)
class TemplateVersionReturnView(_VersionActionView):
    required_permission_class = CanReview

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.return_for_correction(
            version, user, data.get("comments", ""), role_at_time
        )


@extend_schema_view(post=extend_schema(summary="Reject a template version", tags=["Templates"]))
class TemplateVersionRejectView(_VersionActionView):
    required_permission_class = CanApprove

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.reject(version, user, data.get("comments", ""), role_at_time)


@extend_schema_view(
    post=extend_schema(summary="Activate an approved template version", tags=["Templates"])
)
class TemplateVersionActivateView(_VersionActionView):
    required_permission_class = CanActivate

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.activate(version, user)


@extend_schema_view(
    post=extend_schema(summary="Supersede an active template version", tags=["Templates"])
)
class TemplateVersionSupersedeView(_VersionActionView):
    required_permission_class = CanSupersede

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.supersede(version, user, data.get("comments", ""))


@extend_schema_view(post=extend_schema(summary="Retire a template version", tags=["Templates"]))
class TemplateVersionRetireView(_VersionActionView):
    required_permission_class = CanRetire

    def run_action(self, version, user, data, role_at_time):
        return lifecycle.retire(version, user, data.get("comments", ""))


# ---------------------------------------------------------------------------
# Source packages
# ---------------------------------------------------------------------------


@extend_schema_view(
    get=extend_schema(summary="List template source packages", tags=["Template Sources"]),
    post=extend_schema(summary="Register a template source package", tags=["Template Sources"]),
)
class TemplateSourcePackageListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanImportSources()]
        return [CanViewTemplates()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = TemplateSourcePackage.objects.for_tenant_including_platform(tenant).order_by(
            "-imported_at"
        )
        raw = _can_view_raw(request, tenant)
        serializer_class = (
            TemplateSourcePackageRawSerializer if raw else TemplateSourcePackageSerializer
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(serializer_class(page, many=True).data)

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = TemplateSourcePackageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            package = importer.register_source_package(
                tenant=tenant,
                source_name=data["source_name"],
                source_type=data["source_type"],
                source_path_or_reference=data["source_path_or_reference"],
                payload_for_checksum=data["payload"],
                source_version=data.get("source_version", ""),
                source_date=data.get("source_date"),
                licensing_ownership_status=data.get("licensing_ownership_status", ""),
                imported_by=request.user,
            )
        except importer.SourceExcluded as exc:
            raise ValidationError(str(exc)) from exc
        raw = _can_view_raw(request, tenant)
        serializer_class = (
            TemplateSourcePackageRawSerializer if raw else TemplateSourcePackageSerializer
        )
        return Response(serializer_class(package).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Migration batches
# ---------------------------------------------------------------------------


@extend_schema_view(
    get=extend_schema(summary="List migration batches", tags=["Migration Batches"]),
    post=extend_schema(summary="Start a migration batch", tags=["Migration Batches"]),
)
class MigrationBatchListView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanImportSources()]
        return [CanViewTemplates()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = MigrationBatch.objects.for_tenant_including_platform(tenant).order_by("-started_at")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(MigrationBatchSerializer(page, many=True).data)

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = MigrationBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source_package = _get_source_package_or_404(data["source_package"], tenant)
        batch = importer.create_migration_batch(source_package, request.user)
        try:
            importer.run_migration_batch(batch, data["records"], request.user)
        except Exception as exc:
            raise ValidationError(f"Migration batch failed: {exc}") from exc
        return Response(MigrationBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(summary="Retrieve a migration batch", tags=["Migration Batches"])
)
class MigrationBatchDetailView(APIView):
    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        batch = _get_batch_or_404(public_id, tenant)
        return Response(MigrationBatchSerializer(batch).data)


@extend_schema_view(
    get=extend_schema(
        summary="List per-record results for a migration batch", tags=["Migration Batches"]
    )
)
class MigrationBatchResultsView(APIView):
    pagination_class = TemplatePagination

    def get_permissions(self):
        return [CanViewTemplates()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        batch = _get_batch_or_404(public_id, tenant)
        qs = batch.record_results.select_related("source_record").order_by("id")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            MigrationRecordResultSerializer(page, many=True).data
        )


@extend_schema_view(
    post=extend_schema(
        summary="Review a migration batch's duplicate candidates", tags=["Migration Batches"]
    )
)
class MigrationBatchReviewView(APIView):
    def get_permissions(self):
        return [CanReview()]

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        batch = _get_batch_or_404(public_id, tenant)
        serializer = MigrationBatchReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resolved = []
        with transaction.atomic():
            for entry in serializer.validated_data.get("duplicate_resolutions", []):
                candidate_id = entry.get("public_id")
                resolution = entry.get("resolution")
                reason = entry.get("reason", "")
                if not candidate_id or resolution not in (
                    "same",
                    "distinct",
                    "superseded",
                    "merge_approved",
                ):
                    continue
                try:
                    candidate = TemplateDuplicateCandidate.objects.get(public_id=candidate_id)
                except TemplateDuplicateCandidate.DoesNotExist:
                    continue
                candidate.resolution = resolution
                candidate.reviewer = request.user
                candidate.reason = reason
                candidate.save(update_fields=["resolution", "reviewer", "reason", "updated_at"])
                resolved.append(str(candidate.public_id))

        from .audit_events import TemplateEvent, emit

        emit(
            event_type=TemplateEvent.DUPLICATE_CANDIDATE_RESOLVED,
            resource_type="migration_batch",
            resource_id=str(batch.public_id),
            tenant_id=getattr(tenant, "id", None),
            payload={"resolved": resolved},
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response({"resolved": resolved})


@extend_schema_view(
    get=extend_schema(summary="Reconciliation report (CSV)", tags=["Migration Batches"])
)
class MigrationBatchReconciliationCsvView(APIView):
    def get_permissions(self):
        return [CanExportReconciliation()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        batch = _get_batch_or_404(public_id, tenant)
        report = reconciliation.build_reconciliation_report(batch)
        csv_body = reconciliation.render_reconciliation_csv(report)
        response = HttpResponse(csv_body, content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="reconciliation-{batch.public_id}.csv"'
        )
        return response


@extend_schema_view(
    get=extend_schema(summary="Reconciliation report (JSON)", tags=["Migration Batches"])
)
class MigrationBatchReconciliationJsonView(APIView):
    def get_permissions(self):
        # Reviewing reconciliation data (to make duplicate/normalization
        # decisions) and formally exporting it are distinct actions --
        # a Reviewer may view this report, but only VP/Tenant Admin may
        # download it as a file (see MigrationBatchReconciliationCsvView).
        return [(CanReview | CanExportReconciliation)()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        batch = _get_batch_or_404(public_id, tenant)
        return Response(reconciliation.build_reconciliation_report(batch))
