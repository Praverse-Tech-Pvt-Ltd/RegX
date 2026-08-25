"""Blueprint API.

Public IDs only; internal PKs are never exposed. Cross-tenant is 404, never 403 --
a 403 would confirm the row exists. Every endpoint re-checks permission; the
`permissions` block in a response is advisory, for hiding controls the caller
cannot use.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from . import services
from .audit_events import BlueprintEvent
from .models import (
    BlueprintInstantiation,
    BlueprintVersionStatus,
    DossierBlueprint,
    DossierBlueprintSection,
    DossierBlueprintVersion,
)
from .permissions import (
    PERM_ACTIVATE,
    PERM_ARCHIVE,
    PERM_CREATE,
    PERM_CREATE_VERSION,
    PERM_EDIT,
    PERM_INSTANTIATE,
    PERM_MANAGE_SECTIONS,
    PERM_RETIRE,
    PERM_VIEW,
    CanActivateBlueprintVersions,
    CanArchiveBlueprints,
    CanCreateBlueprints,
    CanCreateBlueprintVersions,
    CanEditBlueprints,
    CanInstantiateBlueprints,
    CanManageBlueprintSections,
    CanRetireBlueprintVersions,
    CanViewBlueprints,
    has_blueprint_permission,
)
from .serializers import (
    BlueprintCreateSerializer,
    BlueprintInstantiateResultSerializer,
    BlueprintInstantiateSerializer,
    BlueprintReorderSerializer,
    BlueprintSectionCreateSerializer,
    BlueprintSectionSerializer,
    BlueprintSectionUpdateSerializer,
    BlueprintSerializer,
    BlueprintUpdateSerializer,
    BlueprintVersionCreateSerializer,
    BlueprintVersionSerializer,
)

TAGS = ["dossier-blueprints"]


def _tenant_or_403():
    from tenancy.context import TenantScopeMissing

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _get_blueprint_or_404(public_id, tenant):
    try:
        return DossierBlueprint.objects.select_related("owner", "created_by").get(
            public_id=public_id, tenant=tenant
        )
    except DossierBlueprint.DoesNotExist as exc:
        raise NotFound("Blueprint not found.") from exc


def _get_version_or_404(public_id, tenant):
    try:
        return DossierBlueprintVersion.objects.select_related("blueprint", "created_by").get(
            public_id=public_id, tenant=tenant
        )
    except DossierBlueprintVersion.DoesNotExist as exc:
        raise NotFound("Blueprint version not found.") from exc


def _get_section_or_404(public_id, tenant):
    try:
        return DossierBlueprintSection.objects.select_related("blueprint_version", "parent").get(
            public_id=public_id, tenant=tenant
        )
    except DossierBlueprintSection.DoesNotExist as exc:
        raise NotFound("Blueprint section not found.") from exc


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
    user = request.user
    return {
        "can_create": has_blueprint_permission(user, tenant, PERM_CREATE),
        "can_edit": has_blueprint_permission(user, tenant, PERM_EDIT),
        "can_manage_sections": has_blueprint_permission(user, tenant, PERM_MANAGE_SECTIONS),
        "can_create_version": has_blueprint_permission(user, tenant, PERM_CREATE_VERSION),
        "can_activate": has_blueprint_permission(user, tenant, PERM_ACTIVATE),
        "can_retire": has_blueprint_permission(user, tenant, PERM_RETIRE),
        "can_instantiate": has_blueprint_permission(user, tenant, PERM_INSTANTIATE),
        "can_archive": has_blueprint_permission(user, tenant, PERM_ARCHIVE),
    }


def _user_ref(user):
    return {"public_id": str(user.public_id), "full_name": user.full_name} if user else None


def _blueprint_payload(blueprint, *, active_version=None, version_count=None, usage=None):
    data = BlueprintSerializer(blueprint).data
    data["owner"] = _user_ref(blueprint.owner)
    data["created_by"] = _user_ref(blueprint.created_by)
    data["is_archived"] = blueprint.is_archived
    if active_version is not None or version_count is not None:
        data["current_version_number"] = active_version.version_number if active_version else None
        data["current_version_status"] = active_version.status if active_version else None
        data["current_version_public_id"] = (
            str(active_version.public_id) if active_version else None
        )
        data["version_count"] = version_count
    if usage is not None:
        data["instantiation_count"] = usage
    return data


def _version_payload(version):
    data = BlueprintVersionSerializer(version).data
    data["created_by"] = _user_ref(version.created_by)
    data["blueprint_public_id"] = str(version.blueprint.public_id)
    data["supersedes_public_id"] = (
        str(version.supersedes.public_id) if version.supersedes_id else None
    )
    return data


#: Exactly the service exceptions the API knows how to answer. Anything else is
#: a bug and must reach the error handler as a 500, not be flattened into a 4xx.
SERVICE_ERRORS = (
    services.InvalidTarget,
    services.InvalidHierarchy,
    services.NotActivatable,
    services.BlueprintLocked,
    services.DuplicateValue,
)


def _handle(exc):
    """Map service exceptions to the repository's status-code conventions.

    400 for a bad target or a corrupt hierarchy the caller can fix; 409 for a
    state conflict -- a frozen version, a duplicate, a version that is not yet
    activatable -- matching what dossiers and cases already return.
    """
    if isinstance(exc, services.InvalidTarget | services.InvalidHierarchy):
        return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
class BlueprintListCreateView(APIView):
    def get_permissions(self):
        return [CanCreateBlueprints()] if self.request.method == "POST" else [CanViewBlueprints()]

    @extend_schema(tags=TAGS)
    def get(self, request):
        tenant = _tenant_or_403()
        from django.db.models import Count, Q

        qs = (
            DossierBlueprint.objects.filter(tenant=tenant)
            .select_related("owner", "created_by")
            .prefetch_related("versions")
            .annotate(
                version_count=Count("versions", distinct=True),
                instantiation_count=Count("instantiations", distinct=True),
            )
            .order_by("name", "id")
        )
        if request.query_params.get("include_archived") not in ("true", "1"):
            qs = qs.filter(archived_at__isnull=True)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))

        results = []
        for blueprint in qs:
            # `versions` is prefetched, so picking the active one costs no query.
            active = next(
                (v for v in blueprint.versions.all() if v.status == BlueprintVersionStatus.ACTIVE),
                None,
            )
            results.append(
                _blueprint_payload(
                    blueprint,
                    active_version=active,
                    version_count=blueprint.version_count,
                    usage=blueprint.instantiation_count,
                )
            )
        return Response({"results": results, "permissions": _permissions_block(request, tenant)})

    @extend_schema(tags=TAGS, request=BlueprintCreateSerializer)
    def post(self, request):
        tenant = _tenant_or_403()
        s = BlueprintCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        try:
            owner = _resolve_owner(data.pop("owner_public_id", None), tenant)
            blueprint = services.create_blueprint(
                tenant=tenant, actor=request.user, owner=owner, **data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_blueprint_payload(blueprint), status=http_status.HTTP_201_CREATED)


class BlueprintDetailView(APIView):
    def get_permissions(self):
        return [CanEditBlueprints()] if self.request.method == "PATCH" else [CanViewBlueprints()]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        blueprint = _get_blueprint_or_404(public_id, tenant)
        versions = list(
            DossierBlueprintVersion.objects.filter(blueprint=blueprint)
            .select_related("created_by")
            .order_by("-version_number")
        )
        active = next((v for v in versions if v.status == BlueprintVersionStatus.ACTIVE), None)
        return Response(
            {
                **_blueprint_payload(
                    blueprint,
                    active_version=active,
                    version_count=len(versions),
                    usage=BlueprintInstantiation.objects.filter(blueprint=blueprint).count(),
                ),
                "versions": [_version_payload(v) for v in versions],
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=TAGS, request=BlueprintUpdateSerializer)
    def patch(self, request, public_id):
        tenant = _tenant_or_403()
        blueprint = _get_blueprint_or_404(public_id, tenant)
        s = BlueprintUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        try:
            if "owner_public_id" in data:
                data["owner"] = _resolve_owner(data.pop("owner_public_id"), tenant)
            updated = services.update_blueprint(
                blueprint=blueprint, tenant=tenant, actor=request.user, **data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_blueprint_payload(updated))


class BlueprintArchiveView(APIView):
    permission_classes = [CanArchiveBlueprints]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        blueprint = _get_blueprint_or_404(public_id, tenant)
        try:
            archived = services.archive_blueprint(
                blueprint=blueprint, tenant=tenant, actor=request.user
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_blueprint_payload(archived))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
class BlueprintVersionListCreateView(APIView):
    def get_permissions(self):
        return (
            [CanCreateBlueprintVersions()]
            if self.request.method == "POST"
            else [CanViewBlueprints()]
        )

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        blueprint = _get_blueprint_or_404(public_id, tenant)
        versions = (
            DossierBlueprintVersion.objects.filter(blueprint=blueprint)
            .select_related("created_by", "blueprint", "supersedes")
            .order_by("-version_number")
        )
        return Response(
            {
                "results": [_version_payload(v) for v in versions],
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=TAGS, request=BlueprintVersionCreateSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        blueprint = _get_blueprint_or_404(public_id, tenant)
        s = BlueprintVersionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        source = None
        source_id = s.validated_data.get("source_version_public_id")
        if source_id:
            source = _get_version_or_404(source_id, tenant)
        try:
            version = services.create_version(
                blueprint=blueprint,
                tenant=tenant,
                actor=request.user,
                source_version=source,
                notes=s.validated_data.get("notes", ""),
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_version_payload(version), status=http_status.HTTP_201_CREATED)


class BlueprintVersionDetailView(APIView):
    permission_classes = [CanViewBlueprints]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        sections = list(
            DossierBlueprintSection.objects.filter(
                blueprint_version=version, retired_at__isnull=True
            )
            .select_related("parent")
            .order_by("sequence", "id")
        )
        return Response(
            {
                **_version_payload(version),
                "blueprint": {
                    "public_id": str(version.blueprint.public_id),
                    "name": version.blueprint.name,
                },
                "sections": BlueprintSectionSerializer(sections, many=True).data,
                "section_count": len(sections),
                "instantiation_count": BlueprintInstantiation.objects.filter(
                    blueprint_version=version
                ).count(),
                "is_editable": version.is_draft,
                "permissions": _permissions_block(request, tenant),
            }
        )


class BlueprintVersionActivateView(APIView):
    permission_classes = [CanActivateBlueprintVersions]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        try:
            activated = services.activate_version(
                version=version, tenant=tenant, actor=request.user
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_version_payload(activated))


class BlueprintVersionRetireView(APIView):
    permission_classes = [CanRetireBlueprintVersions]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        try:
            retired = services.retire_version(version=version, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_version_payload(retired))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
class BlueprintSectionListCreateView(APIView):
    def get_permissions(self):
        return (
            [CanManageBlueprintSections()]
            if self.request.method == "POST"
            else [CanViewBlueprints()]
        )

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        sections = (
            DossierBlueprintSection.objects.filter(
                blueprint_version=version, retired_at__isnull=True
            )
            .select_related("parent")
            .order_by("sequence", "id")
        )
        return Response({"results": BlueprintSectionSerializer(sections, many=True).data})

    @extend_schema(tags=TAGS, request=BlueprintSectionCreateSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        s = BlueprintSectionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)

        parent = None
        parent_id = data.pop("parent_public_id", None)
        if parent_id:
            parent = _get_section_or_404(parent_id, tenant)
        try:
            section = services.create_section(
                version=version, tenant=tenant, actor=request.user, parent=parent, **data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            BlueprintSectionSerializer(section).data, status=http_status.HTTP_201_CREATED
        )


class BlueprintSectionDetailView(APIView):
    permission_classes = [CanManageBlueprintSections]

    @extend_schema(tags=TAGS, request=BlueprintSectionUpdateSerializer)
    def patch(self, request, public_id):
        tenant = _tenant_or_403()
        section = _get_section_or_404(public_id, tenant)
        s = BlueprintSectionUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)

        kwargs = {}
        if "parent_public_id" in data:
            raw = data.pop("parent_public_id")
            kwargs["parent"] = _get_section_or_404(raw, tenant) if raw else None
        try:
            updated = services.update_section(
                section=section, tenant=tenant, actor=request.user, **kwargs, **data
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(BlueprintSectionSerializer(updated).data)


class BlueprintSectionReorderView(APIView):
    permission_classes = [CanManageBlueprintSections]

    @extend_schema(tags=TAGS, request=BlueprintReorderSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        section = _get_section_or_404(public_id, tenant)
        s = BlueprintReorderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            moved = services.reorder_section(
                section=section,
                tenant=tenant,
                actor=request.user,
                sequence=s.validated_data["sequence"],
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(BlueprintSectionSerializer(moved).data)


class BlueprintSectionRetireView(APIView):
    permission_classes = [CanManageBlueprintSections]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        section = _get_section_or_404(public_id, tenant)
        try:
            retired = services.retire_section(section=section, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(BlueprintSectionSerializer(retired).data)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------
class BlueprintVersionInstantiateView(APIView):
    """Gate 1 of 3. The other two live in the service and are checked there,
    before the case is resolved, so an unauthorised caller and a nonexistent
    case are indistinguishable."""

    permission_classes = [CanInstantiateBlueprints]

    @extend_schema(
        tags=TAGS,
        request=BlueprintInstantiateSerializer,
        responses=BlueprintInstantiateResultSerializer,
    )
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        version = _get_version_or_404(public_id, tenant)
        s = BlueprintInstantiateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)

        try:
            owner = _resolve_owner(data.pop("owner_public_id", None), tenant)
            instantiation = services.instantiate_version(
                version=version,
                tenant=tenant,
                actor=request.user,
                case_public_id=data["regulatory_case_public_id"],
                title=data["title"],
                owner=owner,
                target_date=data.get("target_date"),
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)

        dossier = instantiation.dossier
        return Response(
            {
                "dossier_public_id": str(dossier.public_id),
                "case_public_id": str(dossier.regulatory_case.public_id),
                "blueprint_public_id": str(instantiation.blueprint.public_id),
                "version_public_id": str(instantiation.blueprint_version.public_id),
                "version_number": instantiation.version_number,
                "section_count": instantiation.section_count,
                "dossier_route": f"/submission-dossiers/{dossier.public_id}",
            },
            status=http_status.HTTP_201_CREATED,
        )


class DossierProvenanceView(APIView):
    """Where a dossier came from, projected safely.

    Requires `submission_dossiers.view` -- it is a fact about the dossier. The
    blueprint's NAME is added only for a caller who also holds
    `dossier_blueprints.view`: a blueprint name is tenant-authored free text and
    dossier permission does not entitle a caller to read the library.
    """

    def get_permissions(self):
        from submission_dossiers.permissions import CanViewDossiers

        return [CanViewDossiers()]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        from submission_dossiers.models import SubmissionDossier

        try:
            dossier = SubmissionDossier.objects.get(public_id=public_id, tenant=tenant)
        except SubmissionDossier.DoesNotExist as exc:
            raise NotFound("Dossier not found.") from exc

        record = (
            BlueprintInstantiation.objects.select_related("blueprint", "blueprint_version")
            .filter(dossier=dossier, tenant=tenant)
            .first()
        )
        if record is None:
            return Response({"instantiated_from_blueprint": False})

        may_see_blueprint = has_blueprint_permission(request.user, tenant, PERM_VIEW)
        payload = {
            "instantiated_from_blueprint": True,
            "instantiation_public_id": str(record.public_id),
            "blueprint_public_id": str(record.blueprint.public_id),
            "version_public_id": str(record.blueprint_version.public_id),
            "version_number": record.version_number,
            "section_count": record.section_count,
            "instantiated_at": record.created_at,
        }
        if may_see_blueprint:
            payload["blueprint_name"] = record.blueprint_name
        else:
            payload["restricted"] = True
        return Response(payload)


__all__ = ["BlueprintEvent"]
