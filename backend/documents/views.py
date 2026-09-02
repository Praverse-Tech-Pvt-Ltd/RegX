"""
Document domain views.

Rules:
- UUID public identifiers only in responses.
- Tenant isolation enforced at every query.
- No storage key or server path exposure.
- No cross-tenant existence disclosure (404 on access to another tenant's doc).
- Correct HTTP status codes per spec.
- Quarantined content cannot be downloaded.
"""

import os

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit_events import DocumentEvent, emit
from .ingest import ingest_new_document
from .models import (
    Document,
    DocumentDuplicateLink,
    DocumentStatus,
    DocumentVersion,
    ScanStatus,
)
from .permissions import (
    CanArchiveDocument,
    CanCreateDocument,
    CanRestoreDocument,
    CanUploadVersion,
    CanViewDocument,
    CanViewPreviousVersions,
    CanViewProcessingStatus,
)
from .serializers import (
    DocumentCreateSerializer,
    DocumentLocatorSerializer,
    DocumentSerializer,
    DocumentVersionSerializer,
    DocumentVersionStatusSerializer,
    DocumentVersionUploadSerializer,
)
from .storage import compute_sha256, get_storage_backend
from .tasks import scan_document_version
from .validators import UploadValidationError, validate_upload


def _get_tenant(request):
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("No active tenant context.") from exc


def _get_document_or_404(public_id, tenant):
    """Return a Document belonging to the tenant or raise 404."""
    try:
        return Document.objects.for_tenant(tenant).get(public_id=public_id)
    except Document.DoesNotExist as exc:
        raise NotFound("Document not found.") from exc


def _get_version_or_404(document, version_public_id):
    try:
        return document.versions.get(public_id=version_public_id)
    except DocumentVersion.DoesNotExist as exc:
        raise NotFound("Version not found.") from exc


def _normalize_filename(filename: str) -> str:
    base = os.path.basename(filename)
    # Replace spaces and unsafe chars
    import re

    safe = re.sub(r"[^\w.\-]", "_", base)
    return safe[:255]


class DocumentPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    get=extend_schema(summary="List documents", tags=["Documents"]),
    post=extend_schema(summary="Create document with initial version", tags=["Documents"]),
)
class DocumentListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = DocumentPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateDocument()]
        return [CanViewDocument()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = Document.objects.for_tenant(tenant).select_related("current_version", "created_by")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        doc_type = request.query_params.get("document_type")
        if doc_type:
            qs = qs.filter(document_type=doc_type)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = DocumentSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = DocumentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)

        file_obj = serializer.validated_data["file"]
        filename = file_obj.name
        declared_mime = file_obj.content_type or ""

        # The pipeline lives in `ingest` so that it is the same pipeline
        # wherever bytes come from. Milestone 14 fetches documents from external
        # connectors and calls exactly this function; there is no second path,
        # and therefore no "trusted source" shortcut for one of them to acquire.
        try:
            doc, _version = ingest_new_document(
                tenant=tenant,
                actor=request.user,
                file_obj=file_obj,
                filename=filename,
                declared_mime=declared_mime,
                title=serializer.validated_data["title"],
                document_type=serializer.validated_data["document_type"],
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except UploadValidationError as exc:
            emit(
                event_type=DocumentEvent.UPLOAD_REJECTED,
                actor_id=request.user.pk,
                actor_email=request.user.email,
                tenant_id=tenant.pk,
                payload={"code": exc.safe_code, "filename": filename[:200]},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(
                {"code": exc.safe_code, "detail": exc.safe_message},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(summary="Get document detail", tags=["Documents"]),
)
class DocumentDetailView(APIView):
    def get_permissions(self):
        return [CanViewDocument()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)
        doc = (
            Document.objects.for_tenant(tenant)
            .select_related("current_version", "created_by")
            .get(pk=doc.pk)
        )
        return Response(DocumentSerializer(doc).data)


@extend_schema_view(
    get=extend_schema(summary="List versions", tags=["Documents"]),
    post=extend_schema(summary="Upload new version", tags=["Documents"]),
)
class DocumentVersionListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = DocumentPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanUploadVersion()]
        return [CanViewDocument()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)
        versions = doc.versions.select_related("uploaded_by").order_by("-version_number")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(versions, request)
        serializer = DocumentVersionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)

        if doc.status == DocumentStatus.ARCHIVED:
            return Response(
                {"detail": "Cannot upload a version to an archived document."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = DocumentVersionUploadSerializer(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)

        file_obj = serializer.validated_data["file"]
        filename = file_obj.name
        declared_mime = file_obj.content_type or ""

        try:
            validation_meta = validate_upload(
                file_obj=file_obj,
                filename=filename,
                declared_mime=declared_mime,
            )
        except UploadValidationError as exc:
            emit(
                event_type=DocumentEvent.UPLOAD_REJECTED,
                actor_id=request.user.pk,
                actor_email=request.user.email,
                tenant_id=tenant.pk,
                payload={"code": exc.safe_code, "filename": filename[:200]},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(
                {"code": exc.safe_code, "detail": exc.safe_message},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        sha256 = compute_sha256(file_obj)
        storage = get_storage_backend()

        with transaction.atomic():
            # Atomic version number assignment
            locked_doc = Document.objects.select_for_update().get(pk=doc.pk)
            last_version = locked_doc.versions.order_by("-version_number").first()
            next_version_number = (last_version.version_number + 1) if last_version else 1

            existing_duplicate = (
                DocumentVersion.objects.for_tenant(tenant).filter(sha256_checksum=sha256).first()
            )

            storage_key = storage.store(
                tenant_id=tenant.pk,
                file_obj=file_obj,
                expected_sha256=sha256,
                content_type=validation_meta.get("detected_mime_type", declared_mime),
                original_filename=filename,
            )

            version = DocumentVersion.objects.create(
                document=locked_doc,
                version_number=next_version_number,
                original_filename=filename,
                normalized_filename=_normalize_filename(filename),
                extension=validation_meta["extension"],
                declared_mime_type=declared_mime,
                detected_mime_type=validation_meta.get("detected_mime_type", ""),
                size_bytes=validation_meta["size_bytes"],
                sha256_checksum=sha256,
                storage_key=storage_key,
                uploaded_by=request.user,
            )

            locked_doc.current_version = version
            locked_doc.save(update_fields=["current_version"])

            if existing_duplicate:
                DocumentDuplicateLink.objects.get_or_create(
                    tenant=tenant,
                    source_version=version,
                    matching_version=existing_duplicate,
                    defaults={"checksum": sha256, "relationship_type": "exact"},
                )

        emit(
            event_type=DocumentEvent.VERSION_CREATED,
            resource_id=str(version.public_id),
            actor_id=request.user.pk,
            actor_email=request.user.email,
            tenant_id=tenant.pk,
            payload={
                "version_number": next_version_number,
                "document_public_id": str(doc.public_id),
            },
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        scan_document_version.delay(version.pk, tenant.pk)

        return Response(DocumentVersionSerializer(version).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(summary="Get version detail", tags=["Documents"]),
)
class DocumentVersionDetailView(APIView):
    def get_permissions(self):
        return [CanViewPreviousVersions()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)
        version = _get_version_or_404(doc, version_public_id)
        return Response(DocumentVersionSerializer(version).data)


@extend_schema_view(
    get=extend_schema(summary="Get version processing status", tags=["Documents"]),
)
class DocumentVersionStatusView(APIView):
    def get_permissions(self):
        return [CanViewProcessingStatus()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)
        version = _get_version_or_404(doc, version_public_id)
        return Response(DocumentVersionStatusSerializer(version).data)


@extend_schema_view(
    get=extend_schema(summary="List locators for a version", tags=["Documents"]),
)
class DocumentLocatorListView(APIView):
    pagination_class = DocumentPagination

    def get_permissions(self):
        return [CanViewDocument()]

    def get(self, request, public_id, version_public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)
        version = _get_version_or_404(doc, version_public_id)

        # Quarantined content must not be accessible
        if version.scan_status == ScanStatus.QUARANTINED:
            raise PermissionDenied(
                "This version has been quarantined and its content is not accessible."
            )

        locators = version.locators.all()
        locator_type = request.query_params.get("locator_type")
        if locator_type:
            locators = locators.filter(locator_type=locator_type)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(locators, request)
        serializer = DocumentLocatorSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


@extend_schema_view(
    post=extend_schema(summary="Archive a document", tags=["Documents"]),
)
class DocumentArchiveView(APIView):
    def get_permissions(self):
        return [CanArchiveDocument()]

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)

        if doc.status == DocumentStatus.ARCHIVED:
            return Response(
                {"detail": "Document is already archived."},
                status=status.HTTP_409_CONFLICT,
            )

        doc.status = DocumentStatus.ARCHIVED
        doc.archived_at = timezone.now()
        doc.archived_by = request.user
        doc.save(update_fields=["status", "archived_at", "archived_by"])

        emit(
            event_type=DocumentEvent.DOCUMENT_ARCHIVED,
            resource_id=str(doc.public_id),
            actor_id=request.user.pk,
            actor_email=request.user.email,
            tenant_id=tenant.pk,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return Response(DocumentSerializer(doc).data)


@extend_schema_view(
    post=extend_schema(summary="Restore an archived document", tags=["Documents"]),
)
class DocumentRestoreView(APIView):
    def get_permissions(self):
        return [CanRestoreDocument()]

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        doc = _get_document_or_404(public_id, tenant)

        if doc.status != DocumentStatus.ARCHIVED:
            return Response(
                {"detail": "Document is not archived."},
                status=status.HTTP_409_CONFLICT,
            )

        doc.status = DocumentStatus.ACTIVE
        doc.archived_at = None
        doc.archived_by = None
        doc.save(update_fields=["status", "archived_at", "archived_by"])

        emit(
            event_type=DocumentEvent.DOCUMENT_RESTORED,
            resource_id=str(doc.public_id),
            actor_id=request.user.pk,
            actor_email=request.user.email,
            tenant_id=tenant.pk,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return Response(DocumentSerializer(doc).data)
