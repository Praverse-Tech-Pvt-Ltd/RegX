"""Upgrade plan API.

Public IDs only; internal PKs are never exposed. Cross-tenant is 404, never 403 --
a 403 would confirm the row exists. Every endpoint re-checks permission; the
`permissions` block in a response is advisory, for hiding controls the caller
cannot use.

**Generate is not apply. Accept is not apply. Ready is not apply.** Nothing
touches a dossier until a caller with `dossier_upgrades.apply` AND
`submission_dossiers.manage_sections` posts to `apply/`.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import current_tenant

from . import services
from .models import (
    DossierUpgradeApplication,
    DossierUpgradePlan,
    DossierUpgradePlanItem,
    ItemStatus,
)
from .permissions import (
    PERM_APPLY,
    PERM_CANCEL,
    PERM_GENERATE,
    PERM_REVIEW,
    PERM_VIEW,
    CanApplyUpgrades,
    CanCancelUpgrades,
    CanGenerateUpgrades,
    CanReviewUpgrades,
    CanViewUpgrades,
    has_upgrade_permission,
)
from .serializers import (
    UpgradePlanCreateSerializer,
    UpgradePlanItemSerializer,
    UpgradePlanSerializer,
)

TAGS = ["dossier-upgrades"]

#: Exactly the service exceptions the API knows how to answer. Anything else is
#: a bug and must surface as a 500, not be flattened into a 4xx.
SERVICE_ERRORS = (
    services.InvalidTarget,
    services.UpgradeLocked,
    services.PlanStale,
    services.NothingToApply,
)


def _tenant_or_403():
    from tenancy.context import TenantScopeMissing

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context is required.") from exc


def _handle(exc):
    """400 for an unavailable target the caller can fix; 409 for a state
    conflict -- a stale plan, a terminal dossier, a blocked item -- matching what
    dossiers, cases and blueprints already return."""
    if isinstance(exc, services.InvalidTarget):
        return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)


def _get_dossier_or_404(public_id, tenant):
    from submission_dossiers.models import SubmissionDossier

    try:
        return SubmissionDossier.objects.get(public_id=public_id, tenant=tenant)
    except SubmissionDossier.DoesNotExist as exc:
        raise NotFound("Dossier not found.") from exc


def _get_plan_or_404(public_id, tenant):
    try:
        return DossierUpgradePlan.objects.select_related(
            "dossier", "blueprint", "source_version", "target_version", "created_by"
        ).get(public_id=public_id, tenant=tenant)
    except DossierUpgradePlan.DoesNotExist as exc:
        raise NotFound("Upgrade plan not found.") from exc


def _get_item_or_404(public_id, plan, tenant):
    try:
        return DossierUpgradePlanItem.objects.get(public_id=public_id, plan=plan, tenant=tenant)
    except DossierUpgradePlanItem.DoesNotExist as exc:
        raise NotFound("Plan item not found.") from exc


def _user_ref(user):
    return {"public_id": str(user.public_id), "full_name": user.full_name} if user else None


def _permissions_block(request, tenant) -> dict:
    user = request.user
    return {
        "can_view": has_upgrade_permission(user, tenant, PERM_VIEW),
        "can_generate": has_upgrade_permission(user, tenant, PERM_GENERATE),
        "can_review": has_upgrade_permission(user, tenant, PERM_REVIEW),
        "can_apply": has_upgrade_permission(user, tenant, PERM_APPLY),
        "can_cancel": has_upgrade_permission(user, tenant, PERM_CANCEL),
    }


def _version_ref(version, *, may_see_blueprint):
    """A version reference, projected safely.

    The version number and status are facts about the dossier's own history and
    are always shown. The blueprint NAME is tenant-authored free text, added only
    for a caller who independently holds `dossier_blueprints.view` -- an upgrade
    permission is not a key to the blueprint library.
    """
    if version is None:
        return None
    data = {
        "public_id": str(version.public_id),
        "version_number": version.version_number,
        "status": version.status,
    }
    if may_see_blueprint:
        data["name"] = version.blueprint.name
    else:
        data["restricted"] = True
    return data


def _item_payload(item):
    data = UpgradePlanItemSerializer(item).data
    data["dossier_section_public_id"] = (
        str(item.dossier_section.public_id) if item.dossier_section_id else None
    )
    data["target_section_public_id"] = (
        str(item.target_section.public_id) if item.target_section_id else None
    )
    return data


def _plan_payload(plan, *, items=None, stale=None, may_see_blueprint=False):
    counts = {"accepted": 0, "rejected": 0, "blocked": 0}
    rows = list(items) if items is not None else list(plan.items.all())
    for item in rows:
        if item.status == ItemStatus.ACCEPTED:
            counts["accepted"] += 1
        elif item.status == ItemStatus.REJECTED:
            counts["rejected"] += 1
        elif item.status == ItemStatus.BLOCKED:
            counts["blocked"] += 1

    data = UpgradePlanSerializer(plan).data
    data["created_by"] = _user_ref(plan.created_by)
    data["dossier_public_id"] = str(plan.dossier.public_id)
    data["source_version"] = _version_ref(plan.source_version, may_see_blueprint=may_see_blueprint)
    data["target_version"] = _version_ref(plan.target_version, may_see_blueprint=may_see_blueprint)
    data["accepted_items"] = counts["accepted"]
    data["rejected_items"] = counts["rejected"]
    data["blocked_items"] = counts["blocked"]
    data["is_stale"] = services.is_stale(plan) if stale is None else stale
    return data


def _may_see_blueprint(request, tenant) -> bool:
    from dossier_blueprints.permissions import PERM_VIEW as BLUEPRINT_VIEW
    from dossier_blueprints.permissions import has_blueprint_permission

    return has_blueprint_permission(request.user, tenant, BLUEPRINT_VIEW)


# ---------------------------------------------------------------------------
# Plans on a dossier
# ---------------------------------------------------------------------------
class DossierUpgradePlanListCreateView(APIView):
    def get_permissions(self):
        return [CanGenerateUpgrades()] if self.request.method == "POST" else [CanViewUpgrades()]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        dossier = _get_dossier_or_404(public_id, tenant)
        may_see = _may_see_blueprint(request, tenant)

        plans = (
            DossierUpgradePlan.objects.filter(dossier=dossier, tenant=tenant)
            .select_related(
                "created_by", "dossier", "source_version__blueprint", "target_version__blueprint"
            )
            .prefetch_related("items")
            .order_by("-created_at", "-id")
        )
        # Every plan in this list belongs to the SAME dossier, so its structural
        # fingerprint is computed once and compared per plan. Letting
        # `_plan_payload` call `is_stale()` itself cost one extra query per plan
        # -- a clean N+1 that the query-cost test caught at 100 plans.
        from .fingerprint import fingerprint_for_dossier

        current_fingerprint = fingerprint_for_dossier(dossier)
        # `items` is prefetched, so the per-plan counts cost no extra query.
        results = [
            _plan_payload(
                p,
                items=p.items.all(),
                stale=p.dossier_fingerprint != current_fingerprint,
                may_see_blueprint=may_see,
            )
            for p in plans
        ]

        blueprint, current = services.current_version_for(dossier)
        targets = (
            services.available_targets(dossier=dossier, tenant=tenant).select_related("blueprint")
            if blueprint
            else []
        )
        return Response(
            {
                "results": results,
                "current_version": _version_ref(current, may_see_blueprint=may_see),
                "available_targets": [_version_ref(v, may_see_blueprint=may_see) for v in targets],
                "permissions": _permissions_block(request, tenant),
            }
        )

    @extend_schema(tags=TAGS, request=UpgradePlanCreateSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        dossier = _get_dossier_or_404(public_id, tenant)
        s = UpgradePlanCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            plan = services.generate_plan(
                dossier=dossier,
                tenant=tenant,
                actor=request.user,
                target_version_public_id=s.validated_data["target_blueprint_version_public_id"],
                notes=s.validated_data.get("notes", ""),
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            _plan_payload(plan, stale=False, may_see_blueprint=_may_see_blueprint(request, tenant)),
            status=http_status.HTTP_201_CREATED,
        )


class DossierUpgradeHistoryView(APIView):
    """A dossier's applied upgrades, oldest first. Append-only history."""

    permission_classes = [CanViewUpgrades]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        dossier = _get_dossier_or_404(public_id, tenant)
        rows = (
            DossierUpgradeApplication.objects.filter(dossier=dossier, tenant=tenant)
            .select_related("plan", "applied_by")
            .order_by("created_at", "id")
        )
        return Response(
            {
                "results": [
                    {
                        "public_id": str(r.public_id),
                        "plan_public_id": str(r.plan.public_id),
                        "source_version_number": r.source_version_number,
                        "target_version_number": r.target_version_number,
                        "sections_added": r.sections_added,
                        "sections_retired": r.sections_retired,
                        "sections_updated": r.sections_updated,
                        "applied_at": r.created_at,
                        "applied_by": _user_ref(r.applied_by),
                    }
                    for r in rows
                ]
            }
        )


# ---------------------------------------------------------------------------
# One plan
# ---------------------------------------------------------------------------
class UpgradePlanDetailView(APIView):
    permission_classes = [CanViewUpgrades]

    @extend_schema(tags=TAGS)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        items = list(
            plan.items.select_related("dossier_section", "target_section").order_by(
                "sequence", "id"
            )
        )
        return Response(
            {
                **_plan_payload(
                    plan, items=items, may_see_blueprint=_may_see_blueprint(request, tenant)
                ),
                "items": [_item_payload(i) for i in items],
                "permissions": _permissions_block(request, tenant),
            }
        )


class UpgradePlanRegenerateView(APIView):
    permission_classes = [CanGenerateUpgrades]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        try:
            plan = services.regenerate_plan(plan=plan, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            _plan_payload(plan, stale=False, may_see_blueprint=_may_see_blueprint(request, tenant))
        )


class UpgradePlanItemReviewView(APIView):
    """Accept or reject one item. Writes nothing to the dossier."""

    permission_classes = [CanReviewUpgrades]
    accept = True

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id, item_public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        item = _get_item_or_404(item_public_id, plan, tenant)
        try:
            item = services.set_item_status(
                item=item, tenant=tenant, actor=request.user, accept=self.accept
            )
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_item_payload(item))


class UpgradePlanItemAcceptView(UpgradePlanItemReviewView):
    accept = True


class UpgradePlanItemRejectView(UpgradePlanItemReviewView):
    accept = False


class UpgradePlanReadyView(APIView):
    permission_classes = [CanReviewUpgrades]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        try:
            plan = services.mark_ready(plan=plan, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_plan_payload(plan, may_see_blueprint=_may_see_blueprint(request, tenant)))


class UpgradePlanApplyView(APIView):
    """Gate 1 of 4. The rest live in the service: the dossier permission is
    checked there before anything is resolved, then the terminal-dossier gate,
    then staleness."""

    permission_classes = [CanApplyUpgrades]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        try:
            application = services.apply_plan(plan=plan, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(
            {
                "public_id": str(application.public_id),
                "plan_public_id": str(plan.public_id),
                "dossier_public_id": str(application.dossier.public_id),
                "source_version_number": application.source_version_number,
                "target_version_number": application.target_version_number,
                "sections_added": application.sections_added,
                "sections_retired": application.sections_retired,
                "sections_updated": application.sections_updated,
                "dossier_route": f"/submission-dossiers/{application.dossier.public_id}",
            },
            status=http_status.HTTP_201_CREATED,
        )


class UpgradePlanCancelView(APIView):
    permission_classes = [CanCancelUpgrades]

    @extend_schema(tags=TAGS, request=None)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        plan = _get_plan_or_404(public_id, tenant)
        try:
            plan = services.cancel_plan(plan=plan, tenant=tenant, actor=request.user)
        except SERVICE_ERRORS as exc:
            return _handle(exc)
        return Response(_plan_payload(plan, may_see_blueprint=_may_see_blueprint(request, tenant)))
