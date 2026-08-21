"""Submission dossier API.

DRF APIViews following `regulatory_cases`: explicit permission classes per
method, tenant from `current_tenant()`, public IDs only, and domain exceptions
mapped to status codes here rather than leaking out of the service layer.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from . import readiness as readiness_engine
from . import services
from .models import (
    BlockerStatus,
    DossierSection,
    DossierSectionBlocker,
    SubmissionDossier,
)
from .permissions import (
    PERM_CANCEL,
    PERM_COMPLETE,
    PERM_CREATE,
    PERM_EDIT,
    PERM_MANAGE_BLOCKERS,
    PERM_MANAGE_LINKS,
    PERM_MANAGE_SECTIONS,
    CanCancelDossiers,
    CanCompleteDossiers,
    CanCreateDossiers,
    CanEditDossiers,
    CanManageBlockers,
    CanManageSectionLinks,
    CanManageSections,
    CanViewDossiers,
    has_dossier_permission,
)
from .projection import module_counts, project_links
from .serializers import (
    BlockerCreateSerializer,
    BlockerSerializer,
    DossierCreateSerializer,
    DossierSerializer,
    DossierStatusChangeSerializer,
    DossierUpdateSerializer,
    ReorderSerializer,
    SectionCreateSerializer,
    SectionLinkRequestSerializer,
    SectionSerializer,
    SectionUpdateSerializer,
)

KINDS = ("document", "workflow", "checklist")


def _tenant(request):
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _get_case_or_404(public_id, tenant):
    from regulatory_cases.models import RegulatoryCase

    try:
        return RegulatoryCase.objects.get(public_id=public_id, tenant=tenant)
    except RegulatoryCase.DoesNotExist as exc:
        raise NotFound("Case not found.") from exc


def _get_dossier_or_404(public_id, tenant):
    """Cross-tenant is 404, not 403 -- a 403 would confirm it exists."""
    try:
        return SubmissionDossier.objects.select_related(
            "owner", "created_by", "regulatory_case"
        ).get(public_id=public_id, tenant=tenant)
    except SubmissionDossier.DoesNotExist as exc:
        raise NotFound("Dossier not found.") from exc


def _get_section_or_404(public_id, tenant):
    try:
        return DossierSection.objects.select_related("owner", "dossier", "parent").get(
            public_id=public_id, tenant=tenant
        )
    except DossierSection.DoesNotExist as exc:
        raise NotFound("Section not found.") from exc


def _resolve_owner(owner_public_id, tenant):
    """Owner must be an active member of this tenant.

    Same single message as an unknown user: otherwise a caller could enumerate
    which user UUIDs belong to other tenants by comparing the two errors.
    """
    if owner_public_id is None:
        return None
    from tenancy.models import TenantMembership

    m = (
        TenantMembership.objects.select_related("user")
        .filter(tenant=tenant, user__public_id=owner_public_id, is_active=True)
        .first()
    )
    if m is None:
        raise services.InvalidTarget("That user cannot be assigned as owner.")
    return m.user


def _permissions_block(request, tenant) -> dict:
    """Advisory only -- every endpoint re-checks."""
    return {
        "can_create": has_dossier_permission(request.user, tenant, PERM_CREATE),
        "can_edit": has_dossier_permission(request.user, tenant, PERM_EDIT),
        "can_manage_sections": has_dossier_permission(request.user, tenant, PERM_MANAGE_SECTIONS),
        "can_manage_links": has_dossier_permission(request.user, tenant, PERM_MANAGE_LINKS),
        "can_manage_blockers": has_dossier_permission(request.user, tenant, PERM_MANAGE_BLOCKERS),
        "can_complete": has_dossier_permission(request.user, tenant, PERM_COMPLETE),
        "can_cancel": has_dossier_permission(request.user, tenant, PERM_CANCEL),
    }


def _conflict(exc, extra=None):
    body = {"detail": str(exc)}
    if extra:
        body.update(extra)
    return Response(body, status=http_status.HTTP_409_CONFLICT)


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------
class CaseDossierListCreateView(APIView):
    def get_permissions(self):
        return [CanCreateDossiers()] if self.request.method == "POST" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, case_public_id):
        tenant = _tenant(request)
        case = _get_case_or_404(case_public_id, tenant)
        qs = SubmissionDossier.objects.filter(tenant=tenant, regulatory_case=case).select_related(
            "owner", "created_by", "regulatory_case"
        )
        return Response(
            {
                "results": DossierSerializer(qs, many=True).data,
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=["submission-dossiers"], request=DossierCreateSerializer)
    def post(self, request, case_public_id):
        tenant = _tenant(request)
        case = _get_case_or_404(case_public_id, tenant)
        s = DossierCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        payload = dict(s.validated_data)
        try:
            payload["owner"] = _resolve_owner(payload.pop("owner_public_id", None), tenant)
        except services.InvalidTarget as exc:
            return Response({"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        dossier = services.create_dossier(case=case, tenant=tenant, actor=request.user, **payload)
        return Response(DossierSerializer(dossier).data, status=http_status.HTTP_201_CREATED)


class DossierDetailView(APIView):
    def get_permissions(self):
        return [CanEditDossiers()] if self.request.method == "PATCH" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)

        # One flat query. The client builds the tree from parent_public_id --
        # recursive serialisation would be an N+1 per node.
        sections = list(
            DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
            .select_related("owner", "parent")
            .order_by("sequence", "id")
        )
        pairs = [(s.required, s.readiness) for s in sections]
        open_blockers = DossierSectionBlocker.objects.filter(
            section__dossier=dossier, section__retired_at__isnull=True, status=BlockerStatus.OPEN
        ).count()

        return Response(
            {
                "dossier": DossierSerializer(dossier).data,
                "sections": SectionSerializer(sections, many=True).data,
                "summary": readiness_engine.summarise(pairs, open_blockers),
                "module_counts": module_counts([s.pk for s in sections], request.user, tenant),
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=["submission-dossiers"], request=DossierUpdateSerializer)
    def patch(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)
        s = DossierUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        payload = dict(s.validated_data)
        if "owner_public_id" in payload:
            try:
                payload["owner"] = _resolve_owner(payload.pop("owner_public_id"), tenant)
            except services.InvalidTarget as exc:
                return Response(
                    {"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
                )
        try:
            updated = services.update_dossier(
                dossier=dossier, tenant=tenant, actor=request.user, **payload
            )
        except services.DossierLocked as exc:
            return _conflict(exc, {"current_status": dossier.status})
        return Response(DossierSerializer(updated).data)


class DossierCompleteView(APIView):
    """Completion records that internal work stopped. It is NOT an agency
    submission and NOT an approval."""

    permission_classes = [CanCompleteDossiers]

    @extend_schema(tags=["submission-dossiers"], request=DossierStatusChangeSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)
        s = DossierStatusChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            updated = services.complete_dossier(
                dossier=dossier,
                tenant=tenant,
                actor=request.user,
                reason=s.validated_data.get("reason", ""),
            )
        except services.NotReady as exc:
            # Safe reason CODE only -- never the identity of a section or
            # resource the caller may not be entitled to see.
            return _conflict(
                Exception("Required sections are not internally ready."),
                {"reason_code": str(exc)},
            )
        except services.DossierLocked as exc:
            return _conflict(exc, {"current_status": dossier.status})
        return Response(DossierSerializer(updated).data)


class DossierCancelView(APIView):
    permission_classes = [CanCancelDossiers]

    @extend_schema(tags=["submission-dossiers"], request=DossierStatusChangeSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)
        s = DossierStatusChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            updated = services.cancel_dossier(
                dossier=dossier,
                tenant=tenant,
                actor=request.user,
                reason=s.validated_data.get("reason", ""),
            )
        except services.DossierLocked as exc:
            return _conflict(exc, {"current_status": dossier.status})
        return Response(DossierSerializer(updated).data)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
class DossierSectionListCreateView(APIView):
    def get_permissions(self):
        return [CanManageSections()] if self.request.method == "POST" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)
        sections = (
            DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
            .select_related("owner", "parent")
            .order_by("sequence", "id")
        )
        return Response(SectionSerializer(sections, many=True).data)

    @extend_schema(tags=["submission-dossiers"], request=SectionCreateSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        dossier = _get_dossier_or_404(public_id, tenant)
        s = SectionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        payload = dict(s.validated_data)

        parent = None
        parent_id = payload.pop("parent_public_id", None)
        if parent_id:
            parent = DossierSection.objects.filter(
                public_id=parent_id, tenant=tenant, dossier=dossier
            ).first()
            if parent is None:
                # Same message whether absent, retired or in another dossier.
                return Response(
                    {"parent_public_id": "Parent section is not available."},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
        try:
            payload["owner"] = _resolve_owner(payload.pop("owner_public_id", None), tenant)
        except services.InvalidTarget as exc:
            return Response({"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        try:
            section = services.create_section(
                dossier=dossier, tenant=tenant, actor=request.user, parent=parent, **payload
            )
        except services.DossierLocked as exc:
            return _conflict(exc, {"current_status": dossier.status})
        except services.InvalidHierarchy as exc:
            return Response({"parent_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        except services.DuplicateLink as exc:
            return _conflict(exc)
        return Response(SectionSerializer(section).data, status=http_status.HTTP_201_CREATED)


class SectionDetailView(APIView):
    def get_permissions(self):
        return [CanManageSections()] if self.request.method == "PATCH" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)

        children = (
            DossierSection.objects.filter(parent=section, retired_at__isnull=True)
            .select_related("owner")
            .order_by("sequence", "id")
        )
        links = {k: services.active_links(kind=k, section=section) for k in KINDS}
        blockers = DossierSectionBlocker.objects.filter(section=section).select_related(
            "created_by", "resolved_by", "section"
        )

        return Response(
            {
                "section": SectionSerializer(section).data,
                # Direct children only. An unbounded recursive tree per section
                # detail is the N+1 shape this deliberately avoids.
                "children": SectionSerializer(children, many=True).data,
                "documents": project_links("document", links["document"], request.user, tenant),
                "workflows": project_links("workflow", links["workflow"], request.user, tenant),
                "checklists": project_links("checklist", links["checklist"], request.user, tenant),
                "blockers": BlockerSerializer(blockers, many=True).data,
                "module_counts": module_counts([section.pk], request.user, tenant),
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=["submission-dossiers"], request=SectionUpdateSerializer)
    def patch(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        s = SectionUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        payload = dict(s.validated_data)

        kwargs = {}
        if "parent_public_id" in payload:
            pid = payload.pop("parent_public_id")
            parent = None
            if pid:
                parent = DossierSection.objects.filter(
                    public_id=pid, tenant=tenant, dossier=section.dossier
                ).first()
                if parent is None:
                    return Response(
                        {"parent_public_id": "Parent section is not available."},
                        status=http_status.HTTP_400_BAD_REQUEST,
                    )
            kwargs["parent"] = parent

        if "owner_public_id" in payload:
            try:
                payload["owner"] = _resolve_owner(payload.pop("owner_public_id"), tenant)
            except services.InvalidTarget as exc:
                return Response(
                    {"owner_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
                )

        try:
            updated = services.update_section(
                section=section, tenant=tenant, actor=request.user, **kwargs, **payload
            )
        except services.DossierLocked as exc:
            return _conflict(exc)
        except services.InvalidHierarchy as exc:
            return Response({"parent_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        except services.DuplicateLink as exc:
            return _conflict(exc)
        return Response(SectionSerializer(updated).data)


class SectionReorderView(APIView):
    permission_classes = [CanManageSections]

    @extend_schema(tags=["submission-dossiers"], request=ReorderSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        s = ReorderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            updated = services.reorder_section(
                section=section,
                tenant=tenant,
                actor=request.user,
                sequence=s.validated_data["sequence"],
            )
        except services.DossierLocked as exc:
            return _conflict(exc)
        except services.InvalidTarget as exc:
            raise NotFound(str(exc)) from exc
        return Response(SectionSerializer(updated).data)


class SectionRetireView(APIView):
    permission_classes = [CanManageSections]

    @extend_schema(tags=["submission-dossiers"])
    def post(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        try:
            updated = services.retire_section(section=section, tenant=tenant, actor=request.user)
        except services.DossierLocked as exc:
            return _conflict(exc)
        except services.InvalidHierarchy as exc:
            return _conflict(exc)
        return Response(SectionSerializer(updated).data)


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------
class SectionBlockerListCreateView(APIView):
    def get_permissions(self):
        return [CanManageBlockers()] if self.request.method == "POST" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        rows = DossierSectionBlocker.objects.filter(section=section).select_related(
            "created_by", "resolved_by", "section"
        )
        return Response(BlockerSerializer(rows, many=True).data)

    @extend_schema(tags=["submission-dossiers"], request=BlockerCreateSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        s = BlockerCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            blocker = services.create_blocker(
                section=section, tenant=tenant, actor=request.user, **s.validated_data
            )
        except services.DossierLocked as exc:
            return _conflict(exc)
        return Response(BlockerSerializer(blocker).data, status=http_status.HTTP_201_CREATED)


class BlockerResolveView(APIView):
    permission_classes = [CanManageBlockers]

    @extend_schema(tags=["submission-dossiers"])
    def post(self, request, public_id):
        tenant = _tenant(request)
        try:
            blocker = DossierSectionBlocker.objects.select_related("section__dossier").get(
                public_id=public_id, tenant=tenant
            )
        except DossierSectionBlocker.DoesNotExist as exc:
            raise NotFound("Blocker not found.") from exc
        try:
            resolved = services.resolve_blocker(blocker=blocker, tenant=tenant, actor=request.user)
        except services.DossierLocked as exc:
            return _conflict(exc)
        return Response(BlockerSerializer(resolved).data)


# ---------------------------------------------------------------------------
# Section links
# ---------------------------------------------------------------------------
class SectionLinkListCreateView(APIView):
    kind = ""

    def get_permissions(self):
        return [CanManageSectionLinks()] if self.request.method == "POST" else [CanViewDossiers()]

    @extend_schema(tags=["submission-dossiers"])
    def get(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        rows = services.active_links(kind=self.kind, section=section)
        return Response(project_links(self.kind, rows, request.user, tenant))

    @extend_schema(tags=["submission-dossiers"], request=SectionLinkRequestSerializer)
    def post(self, request, public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        s = SectionLinkRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            link = services.link_target(
                kind=self.kind,
                section=section,
                target_public_id=s.validated_data["target_public_id"],
                actor=request.user,
                tenant=tenant,
                purpose=s.validated_data.get("purpose", ""),
            )
        except services.DossierLocked as exc:
            return _conflict(exc)
        except services.DuplicateLink as exc:
            return _conflict(exc)
        except services.InvalidTarget as exc:
            return Response({"target_public_id": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(
            project_links(self.kind, [link], request.user, tenant)[0],
            status=http_status.HTTP_201_CREATED,
        )


class SectionLinkDetailView(APIView):
    kind = ""
    permission_classes = [CanManageSectionLinks]

    @extend_schema(tags=["submission-dossiers"])
    def delete(self, request, public_id, link_public_id):
        tenant = _tenant(request)
        section = _get_section_or_404(public_id, tenant)
        try:
            services.unlink_target(
                kind=self.kind,
                section=section,
                link_public_id=link_public_id,
                actor=request.user,
                tenant=tenant,
            )
        except services.DossierLocked as exc:
            return _conflict(exc)
        except services.InvalidTarget as exc:
            raise NotFound(str(exc)) from exc
        return Response(status=http_status.HTTP_204_NO_CONTENT)


# Concrete per-kind views: an unknown kind is a URL-resolver 404 rather than
# something a view has to validate.
class SectionDocumentListCreateView(SectionLinkListCreateView):
    kind = "document"


class SectionDocumentDetailView(SectionLinkDetailView):
    kind = "document"


class SectionWorkflowListCreateView(SectionLinkListCreateView):
    kind = "workflow"


class SectionWorkflowDetailView(SectionLinkDetailView):
    kind = "workflow"


class SectionChecklistListCreateView(SectionLinkListCreateView):
    kind = "checklist"


class SectionChecklistDetailView(SectionLinkDetailView):
    kind = "checklist"
