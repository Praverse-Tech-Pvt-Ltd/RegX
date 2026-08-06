"""IID assessment domain API views."""

from django.db import transaction
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .assess import run_preview
from .audit_events import IidAssessmentEvent, emit
from .models import AssessmentSnapshot
from .permissions import CanPreviewIidAssessment
from .serializers import (
    AssessmentSnapshotSerializer,
    MatchPreviewRequestSerializer,
    SnapshotRequestSerializer,
)
from .services import (
    AssessmentSnapshotError,
    ReleaseNotEligible,
    create_assessment_snapshot,
)


def _get_tenant(request):
    from rest_framework.exceptions import PermissionDenied

    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("No active tenant context.") from exc


class MatchPreviewView(APIView):
    """Non-persisting preview: matching + unit conversion + calculation +
    decision. Never prefills or defaults the user's proposed quantity from
    an IID value -- IID values are displayed as comparison references
    only, supplied entirely by the request."""

    def get_permissions(self):
        return [CanPreviewIidAssessment()]

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = MatchPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        preview = run_preview(**serializer.validated_data)
        emit(
            event_type=IidAssessmentEvent.MATCH_PREVIEW_GENERATED,
            resource_id="",
            tenant_id=tenant.id,
            payload={
                "match_status": preview.match_status,
                "decision_status": preview.decision_status,
            },
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(
            {
                "match_status": preview.match_status,
                "candidates": preview.candidates,
                "selected_record": preview.selected_record,
                "calculations": preview.calculations,
                "decision_status": preview.decision_status,
                "decision_note": preview.decision_note,
                "escalation_required": preview.escalation_required,
                "substance_mapping_public_id": preview.substance_mapping_public_id,
                "substance_resolution_status": preview.substance_resolution_status,
            }
        )


def _require_formulation_version(tenant, public_id):
    """The caller's formulation version, scoped to their tenant.

    A version that does not exist and a version belonging to another tenant are
    deliberately indistinguishable from outside: both are 404, so the endpoint
    cannot be used to probe for another tenant's identifiers.
    """
    from formulations.models import FormulationVersion

    try:
        return FormulationVersion.objects.select_related("product").get(
            public_id=public_id, product__tenant=tenant
        )
    except FormulationVersion.DoesNotExist as exc:
        raise NotFound("Formulation version not found.") from exc


def _require_component(formulation_version, public_id):
    """The exact component of that exact version -- never matched by name."""
    from formulations.models import FormulationComponent

    try:
        return FormulationComponent.objects.get(
            public_id=public_id, formulation_version=formulation_version
        )
    except FormulationComponent.DoesNotExist as exc:
        raise NotFound("Formulation component not found.") from exc


def _require_release(public_id):
    from fda_data.models import FDADataSourceRelease

    try:
        return FDADataSourceRelease.objects.get(public_id=public_id)
    except FDADataSourceRelease.DoesNotExist as exc:
        raise NotFound("FDA data source release not found.") from exc


class SnapshotView(APIView):
    """Persists an immutable AssessmentSnapshot from a preview -- the
    frozen record a checklist run or regulatory submission can reference
    reproducibly regardless of later FDA data refreshes.

    A thin adapter over ``create_assessment_snapshot()``. The serializer still
    validates transport shape; every domain rule -- tenant ownership, the
    component actually belonging to the named formulation version, release
    eligibility, and deriving the frozen values from the governed formulation
    rather than from request fields -- lives in the service, so the API and the
    checklist execution layer cannot drift apart.
    """

    def get_permissions(self):
        return [CanPreviewIidAssessment()]

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = SnapshotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        formulation_version = _require_formulation_version(
            tenant, data["formulation_version_public_id"]
        )
        component = _require_component(
            formulation_version, data["formulation_component_public_id"]
        )
        # The client names the exact release it is assessing against; the
        # service verifies it is an eligible fda_iid release and never
        # substitutes a newer one. The checklist execution path instead
        # resolves the active release server-side (M4D3-SRC-001/003).
        release = _require_release(data["active_release_public_id"])

        try:
            with transaction.atomic():
                result = create_assessment_snapshot(
                    tenant=tenant,
                    formulation_version=formulation_version,
                    formulation_component=component,
                    actor=request.user,
                    selected_release=release,
                    selected_precedent_record_public_id=data.get(
                        "selected_precedent_record_public_id"
                    ),
                    maximum_dosage_units_per_day=data.get("maximum_dosage_units_per_day"),
                )
        except ReleaseNotEligible as exc:
            raise ValidationError(
                {
                    "error_code": "release_not_eligible",
                    "detail": (
                        "The selected release is not an approved FDA IID release "
                        "available for assessment."
                    ),
                }
            ) from exc
        except AssessmentSnapshotError as exc:
            # Ownership faults reach here only if the objects were resolved
            # above and still disagree; report them the same non-leaking way.
            raise NotFound("Formulation component not found.") from exc

        return Response(
            AssessmentSnapshotSerializer(result.snapshot).data,
            status=http_status.HTTP_201_CREATED,
        )


class SnapshotDetailView(APIView):
    def get_permissions(self):
        return [CanPreviewIidAssessment()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        try:
            snapshot = AssessmentSnapshot.objects.get(tenant=tenant, public_id=public_id)
        except AssessmentSnapshot.DoesNotExist as exc:
            raise NotFound("Assessment snapshot not found.") from exc
        return Response(AssessmentSnapshotSerializer(snapshot).data)
