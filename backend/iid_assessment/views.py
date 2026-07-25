"""IID assessment domain API views."""

from rest_framework import status as http_status
from rest_framework.exceptions import NotFound
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


class SnapshotView(APIView):
    """Persists an immutable AssessmentSnapshot from a preview -- the
    frozen record a checklist run or regulatory submission can reference
    reproducibly regardless of later FDA data refreshes."""

    def get_permissions(self):
        return [CanPreviewIidAssessment()]

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = SnapshotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        component_id = data.pop("formulation_component_public_id")
        version_id = data.pop("formulation_version_public_id")
        preview = run_preview(**data)

        selected = preview.selected_record or {}
        snapshot = AssessmentSnapshot.objects.create(
            tenant=tenant,
            formulation_component_public_id=component_id,
            formulation_version_public_id=version_id,
            iid_release_public_id=data.get("active_release_public_id"),
            iid_precedent_record_public_id=selected.get("precedent_record_public_id"),
            iid_substance_mapping_public_id=preview.substance_mapping_public_id,
            iid_ingredient_name=selected.get("ingredient_name", ""),
            iid_route=selected.get("route", ""),
            iid_dosage_form=selected.get("dosage_form", ""),
            iid_potency_amount=selected.get("potency_amount"),
            iid_potency_unit=selected.get("potency_unit", "") or "",
            iid_mde=selected.get("maximum_daily_exposure"),
            iid_mde_unit=selected.get("mde_unit", "") or "",
            proposed_quantity_per_unit=data.get("proposed_quantity_per_unit"),
            proposed_quantity_unit=data.get("proposed_quantity_unit", ""),
            calculation_results=preview.calculations,
            match_status=preview.match_status,
            decision_status=preview.decision_status,
            decision_note=preview.decision_note,
            created_by=request.user,
        )
        emit(
            event_type=IidAssessmentEvent.SNAPSHOT_CREATED,
            resource_id=str(snapshot.public_id),
            tenant_id=tenant.id,
            payload={"decision_status": preview.decision_status},
            actor_id=request.user.id,
            actor_email=request.user.email,
        )
        return Response(
            AssessmentSnapshotSerializer(snapshot).data, status=http_status.HTTP_201_CREATED
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
