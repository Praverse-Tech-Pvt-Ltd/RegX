"""Submission package API.

Public IDs only; internal PKs are never exposed. Cross-tenant is 404, never 403
-- a 403 would confirm the row exists. Every endpoint re-checks permission; the
`permissions` block in a response is advisory, for hiding controls.

**Package permission is never document permission.** Adding an entry needs
`documents.view` as well; exporting needs it too, and needs it for the whole
package at once -- see `export`.

**Frozen is an internal RegX state.** It is not regulatory approval or agency
acceptance, and no endpoint here produces anything an agency ingests.
"""

import tempfile

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from . import services
from .audit_events import PackageEvent, emit
from .models import PackageStatus, SubmissionPackage, SubmissionPackageEntry
from .permissions import (
    PERM_CANCEL,
    PERM_CREATE,
    PERM_EDIT,
    PERM_EXPORT,
    PERM_FREEZE,
    PERM_MANAGE_ENTRIES,
    PERM_REVIEW,
    PERM_VIEW,
    CanCancelPackages,
    CanCreatePackages,
    CanEditPackages,
    CanExportPackages,
    CanFreezePackages,
    CanManageEntries,
    CanReviewPackages,
    CanViewPackages,
    has_package_permission,
)
from .serializers import (
    PackageCloneSerializer,
    PackageCreateSerializer,
    PackageDetailSerializer,
    PackageEntryCreateSerializer,
    PackageEntryReorderSerializer,
    PackageEntrySerializer,
    PackageIntegritySerializer,
    PackageManifestSerializer,
    PackageSerializer,
    PackageUpdateSerializer,
)

TAGS = ["submission-packages"]

#: Exactly the service exceptions the API knows how to answer. Anything else is
#: a bug and must surface as a 500, not be flattened into a 4xx.
SERVICE_ERRORS = (
    services.InvalidTarget,
    services.PackageLocked,
    services.PackageIntegrityError,
)


def _tenant_or_403():
    from tenancy.context import TenantScopeMissing

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _handle(exc):
    if isinstance(exc, services.InvalidTarget):
        return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, services.PackageIntegrityError):
        return Response(
            {"detail": str(exc), "issues": exc.issues}, status=http_status.HTTP_409_CONFLICT
        )
    return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)


class _Pagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 200


def _get_package_or_404(public_id, tenant):
    package = (
        SubmissionPackage.objects.select_related(
            "regulatory_case", "created_by", "frozen_by", "source_package"
        )
        .filter(public_id=public_id, tenant=tenant)
        .first()
    )
    if package is None:
        raise NotFound("Package not found.")
    return package


def _get_entry_or_404(entry_public_id, package, tenant):
    entry = SubmissionPackageEntry.objects.filter(
        public_id=entry_public_id, package=package, tenant=tenant
    ).first()
    if entry is None:
        raise NotFound("Package entry not found.")
    return entry


def _may_see_documents(request, tenant) -> bool:
    from documents.permissions import PERM_VIEW as DOCUMENTS_VIEW
    from documents.permissions import has_document_permission

    return has_document_permission(request.user, tenant, DOCUMENTS_VIEW)


def _may_see_cases(request, tenant) -> bool:
    from regulatory_cases.permissions import PERM_VIEW as CASE_VIEW
    from regulatory_cases.permissions import has_case_permission

    return has_case_permission(request.user, tenant, CASE_VIEW)


def _user_ref(user):
    return {"public_id": str(user.public_id), "full_name": user.full_name} if user else None


def _entry_payload(entry, *, may_see_documents: bool) -> dict:
    version = entry.document_version
    return {
        "public_id": str(entry.public_id),
        "sequence": entry.sequence,
        "logical_path": entry.logical_path,
        "export_filename": entry.export_filename,
        "display_name": entry.display_name,
        "dossier_section_public_id": (
            str(entry.dossier_section.public_id) if entry.dossier_section_id else None
        ),
        "is_active": entry.is_active,
        "added_at": entry.created_at,
        # `null`, not omitted and not redacted-in-place: the entry exists
        # because the package is visible, and the document does not because the
        # caller holds no document permission.
        "document": (
            {
                "document_public_id": str(version.document.public_id),
                "document_version_public_id": str(version.public_id),
                "version_number": version.version_number,
                "title": version.document.title,
                "checksum_sha256": version.sha256_checksum,
                "size_bytes": version.size_bytes,
                "mime_type": version.detected_mime_type or version.declared_mime_type,
                "scan_status": version.scan_status,
            }
            if may_see_documents
            else None
        ),
    }


def _package_payload(package, *, entry_count, may_see_cases, permissions=None) -> dict:
    return {
        "public_id": str(package.public_id),
        "name": package.name,
        "description": package.description,
        "status": package.status,
        "revision_number": package.revision_number,
        # The case identity belongs to `regulatory_cases` and is gated on its
        # permission, not on the one that surfaced this row.
        "case_public_id": (str(package.regulatory_case.public_id) if may_see_cases else None),
        "source_package_public_id": (
            str(package.source_package.public_id) if package.source_package_id else None
        ),
        "entry_count": entry_count,
        "manifest_checksum": package.manifest_checksum,
        "created_by": _user_ref(package.created_by),
        "created_at": package.created_at,
        "frozen_by": _user_ref(package.frozen_by),
        "frozen_at": package.frozen_at,
        "cancelled_at": package.cancelled_at,
        **({"permissions": permissions} if permissions is not None else {}),
    }


def _permissions_block(request, tenant) -> dict:
    user = request.user
    return {
        "can_view": has_package_permission(user, tenant, PERM_VIEW),
        "can_create": has_package_permission(user, tenant, PERM_CREATE),
        "can_edit": has_package_permission(user, tenant, PERM_EDIT),
        "can_manage_entries": has_package_permission(user, tenant, PERM_MANAGE_ENTRIES),
        "can_review": has_package_permission(user, tenant, PERM_REVIEW),
        "can_freeze": has_package_permission(user, tenant, PERM_FREEZE),
        "can_cancel": has_package_permission(user, tenant, PERM_CANCEL),
        "can_export": has_package_permission(user, tenant, PERM_EXPORT),
    }


# ---------------------------------------------------------------------------
class CasePackageListCreateView(APIView):
    def get_permissions(self):
        return [CanCreatePackages()] if self.request.method == "POST" else [CanViewPackages()]

    @extend_schema(tags=TAGS, responses=PackageSerializer(many=True))
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        from regulatory_cases.models import RegulatoryCase

        if not _may_see_cases(request, tenant):
            raise NotFound("Case not found.")
        case = RegulatoryCase.objects.filter(public_id=public_id, tenant=tenant).first()
        if case is None:
            raise NotFound("Case not found.")

        packages = (
            SubmissionPackage.objects.filter(tenant=tenant, regulatory_case=case)
            .select_related("regulatory_case", "created_by", "frozen_by", "source_package")
            .order_by("-created_at", "-id")
        )
        paginator = _Pagination()
        page = paginator.paginate_queryset(packages, request)
        counts = _entry_counts([p.pk for p in page])
        rows = [
            _package_payload(p, entry_count=counts.get(p.pk, 0), may_see_cases=True) for p in page
        ]
        return paginator.get_paginated_response(PackageSerializer(rows, many=True).data)

    @extend_schema(tags=TAGS, request=PackageCreateSerializer, responses=PackageSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        payload = PackageCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            package = services.create_package(
                case_public_id=public_id,
                tenant=tenant,
                actor=request.user,
                **payload.validated_data,
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageSerializer(
                _package_payload(
                    package, entry_count=0, may_see_cases=_may_see_cases(request, tenant)
                )
            ).data,
            status=http_status.HTTP_201_CREATED,
        )


def _entry_counts(package_ids) -> dict:
    """Active entry counts for a page of packages, in one grouped query."""
    from django.db.models import Count

    if not package_ids:
        return {}
    return {
        row["package_id"]: row["n"]
        for row in SubmissionPackageEntry.objects.filter(
            package_id__in=package_ids, removed_at__isnull=True
        )
        .values("package_id")
        .annotate(n=Count("id"))
    }


class PackageDetailView(APIView):
    def get_permissions(self):
        return [CanEditPackages()] if self.request.method == "PATCH" else [CanViewPackages()]

    @extend_schema(tags=TAGS, responses=PackageDetailSerializer)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        may_docs = _may_see_documents(request, tenant)
        entries = list(services.active_entries(package))
        data = _package_payload(
            package,
            entry_count=len(entries),
            may_see_cases=_may_see_cases(request, tenant),
            permissions=_permissions_block(request, tenant),
        )
        data["entries"] = [_entry_payload(e, may_see_documents=may_docs) for e in entries]
        return Response(PackageDetailSerializer(data).data)

    @extend_schema(tags=TAGS, request=PackageUpdateSerializer, responses=PackageSerializer)
    def patch(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        payload = PackageUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        if not payload.validated_data:
            raise ValidationError({"detail": "No changes supplied."})
        try:
            package = services.update_package(
                package=package, tenant=tenant, actor=request.user, **payload.validated_data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageSerializer(
                _package_payload(
                    package,
                    entry_count=services.active_entries(package).count(),
                    may_see_cases=_may_see_cases(request, tenant),
                )
            ).data
        )


class PackageEntryListCreateView(APIView):
    permission_classes = [CanManageEntries]

    @extend_schema(
        tags=TAGS, request=PackageEntryCreateSerializer, responses=PackageEntrySerializer
    )
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        payload = PackageEntryCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            entry = services.add_entry(
                package=package, tenant=tenant, actor=request.user, **payload.validated_data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageEntrySerializer(
                _entry_payload(entry, may_see_documents=_may_see_documents(request, tenant))
            ).data,
            status=http_status.HTTP_201_CREATED,
        )


class PackageEntryRemoveView(APIView):
    permission_classes = [CanManageEntries]

    @extend_schema(tags=TAGS, request=None, responses=PackageEntrySerializer)
    def post(self, request, public_id, entry_public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        entry = _get_entry_or_404(entry_public_id, package, tenant)
        try:
            entry = services.remove_entry(entry=entry, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageEntrySerializer(
                _entry_payload(entry, may_see_documents=_may_see_documents(request, tenant))
            ).data
        )


class PackageEntryReorderView(APIView):
    permission_classes = [CanManageEntries]

    @extend_schema(
        tags=TAGS, request=PackageEntryReorderSerializer, responses=PackageEntrySerializer
    )
    def post(self, request, public_id, entry_public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        entry = _get_entry_or_404(entry_public_id, package, tenant)
        payload = PackageEntryReorderSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            entry = services.reorder_entry(
                entry=entry, tenant=tenant, actor=request.user, **payload.validated_data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageEntrySerializer(
                _entry_payload(entry, may_see_documents=_may_see_documents(request, tenant))
            ).data
        )


class _TransitionView(APIView):
    service = None
    permission_classes = [CanReviewPackages]

    @extend_schema(tags=TAGS, request=None, responses=PackageSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        try:
            package = type(self).service(package=package, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageSerializer(
                _package_payload(
                    package,
                    entry_count=services.active_entries(package).count(),
                    may_see_cases=_may_see_cases(request, tenant),
                )
            ).data
        )


class PackageSubmitForReviewView(_TransitionView):
    service = staticmethod(services.submit_for_review)
    permission_classes = [CanReviewPackages]


class PackageReturnToDraftView(_TransitionView):
    service = staticmethod(services.return_to_draft)
    permission_classes = [CanReviewPackages]


class PackageCancelView(_TransitionView):
    service = staticmethod(services.cancel_package)
    permission_classes = [CanCancelPackages]


class PackageFreezeView(_TransitionView):
    service = staticmethod(services.freeze_package)
    permission_classes = [CanFreezePackages]


class PackageCloneView(APIView):
    permission_classes = [CanCreatePackages]

    @extend_schema(tags=TAGS, request=PackageCloneSerializer, responses=PackageSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        payload = PackageCloneSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            clone = services.clone_package(
                package=package, tenant=tenant, actor=request.user, **payload.validated_data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            PackageSerializer(
                _package_payload(
                    clone,
                    entry_count=services.active_entries(clone).count(),
                    may_see_cases=_may_see_cases(request, tenant),
                )
            ).data,
            status=http_status.HTTP_201_CREATED,
        )


class PackageValidateView(APIView):
    """**Internal package integrity only.**

    Deliberately not named `regulatory-validate` or `submission-validate`: this
    endpoint knows whether the package can be exported, and nothing about
    whether it should be.
    """

    permission_classes = [CanViewPackages]

    @extend_schema(tags=TAGS, responses=PackageIntegritySerializer)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)
        result = services.validate_package(package=package, tenant=tenant)
        return Response(PackageIntegritySerializer(result).data)


class PackageManifestView(APIView):
    """The frozen manifest, which is **document-bearing information**.

    TWO GATES: `submission_packages.view` (by the permission class) and
    `documents.view` (here). The manifest names every cited document, its exact
    version, its SHA-256 and its size -- precisely the fields the package detail
    endpoint returns as `null` to a caller without document permission. Serving
    it under package permission alone would make this endpoint a way around the
    projection the rest of the milestone maintains.

    The stored snapshot is never altered to accommodate a caller. A redacted
    manifest would be a second, differently-hashed document claiming to be the
    manifest, and the checksum is the whole point.
    """

    permission_classes = [CanViewPackages]

    @extend_schema(
        tags=TAGS,
        responses={
            200: PackageManifestSerializer,
            403: OpenApiResponse(
                description=(
                    "The caller may view the package but not its documents. The "
                    "manifest names exact document versions and checksums, so it "
                    "requires `documents.view` as well."
                )
            ),
        },
    )
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)

        if not _may_see_documents(request, tenant):
            # Checked after the 404 lookup, so a cross-tenant package stays
            # indistinguishable from a missing one rather than answering 403 and
            # confirming it exists.
            raise PermissionDenied(
                "Reading a package manifest requires permission to view its documents."
            )

        snapshot = getattr(package, "snapshot", None)
        if snapshot is None:
            raise NotFound("This package has no frozen manifest.")
        return Response(
            PackageManifestSerializer(
                {
                    "manifest_schema_version": snapshot.manifest_schema_version,
                    "manifest_checksum": snapshot.manifest_checksum,
                    "entry_count": snapshot.entry_count,
                    "total_bytes": snapshot.total_bytes,
                    "frozen_at": snapshot.frozen_at,
                    "manifest": snapshot.manifest,
                }
            ).data
        )


class PackageExportView(APIView):
    """Stream the whole frozen package as one internal ZIP.

    TWO GATES: `submission_packages.export` (by the permission class) and
    `documents.view` (here). The document gate is checked **for the package as a
    whole**, and a caller who cannot retrieve documents is refused the entire
    export rather than handed a shorter archive. A ZIP silently missing files
    looks complete to whoever receives it, which makes a partial export worse
    than no export.
    """

    permission_classes = [CanExportPackages]

    @extend_schema(
        tags=TAGS,
        responses={
            # Declared BINARY so the schema says this is a file download rather
            # than JSON. Without the response type the content block comes back
            # empty and a generated client tries to parse a ZIP as a document.
            (200, "application/zip"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description=(
                    "Internal package export archive (ZIP). Not an agency submission format."
                ),
            )
        },
    )
    def get(self, request, public_id):
        from .export import ExportError, write_package_zip

        tenant = _tenant_or_403()
        package = _get_package_or_404(public_id, tenant)

        if not _may_see_documents(request, tenant):
            # Not a partial export. See the class docstring.
            raise PermissionDenied("Exporting a package requires permission to view its documents.")
        if package.status != PackageStatus.FROZEN:
            return Response(
                {"detail": "Only a frozen package can be exported."},
                status=http_status.HTTP_409_CONFLICT,
            )
        snapshot = getattr(package, "snapshot", None)
        if snapshot is None:
            return Response(
                {"detail": "This package has no frozen manifest."},
                status=http_status.HTTP_409_CONFLICT,
            )

        entries = list(services.active_entries(package))
        # A temporary file rather than an in-memory buffer: a package is many
        # documents, and holding all of them in RAM to serve one download is how
        # a large export takes the process down. Deleted when the response
        # closes.
        handle = tempfile.NamedTemporaryFile(suffix=".zip")
        try:
            counts = write_package_zip(snapshot=snapshot, entries=entries, destination=handle)
        except ExportError as exc:
            handle.close()
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        except Exception:
            handle.close()
            raise

        handle.seek(0)
        emit(
            event_type=PackageEvent.EXPORTED,
            resource_id=package.public_id,
            actor=request.user,
            tenant_id=tenant.pk,
            payload={
                "action": "exported",
                "package_public_id": str(package.public_id),
                "snapshot_public_id": str(snapshot.public_id),
                "manifest_checksum": snapshot.manifest_checksum,
                "entry_count": counts["entry_count"],
                "total_bytes": counts["total_bytes"],
                "export_format": "zip",
            },
        )
        response = FileResponse(handle, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="package-{package.public_id}.zip"'
        return response
