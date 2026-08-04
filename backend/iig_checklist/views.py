"""IIG checklist definition-governance API views.

UUID-only identifiers; permission enforcement on every endpoint; a
missing/forbidden record returns a generic 404; every lifecycle action
goes through the single authoritative transition service
(transitions.py) inside select_for_update()+transaction.atomic(), never
a generic status PATCH.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import TenantScopeMissing, current_tenant

from .audit import IigChecklistEvent, emit
from .codes import CodeValidationError
from .enums import ChecklistVersionStatus
from .execution_transitions import IllegalExecutionTransition
from .models import (
    ApplicabilityRule,
    ChecklistDefinition,
    ChecklistExecution,
    ChecklistQuestion,
    ChecklistResponse,
    ChecklistSection,
    ChecklistVersion,
)
from .permissions import (
    PERM_APPROVE_EXECUTION,
    PERM_CANCEL_EXECUTION,
    PERM_CREATE_DEFINITION,
    PERM_DELETE_DRAFT,
    PERM_EDIT_DRAFT,
    PERM_EDIT_EXECUTION,
    PERM_REVIEW_EXECUTION,
    PERM_SUBMIT_EXECUTION,
    PERM_SUPERSEDE_EXECUTION,
    PERM_VIEW_EXECUTION,
    CanActivateChecklist,
    CanApproveChecklist,
    CanCloneChecklist,
    CanCreateChecklistDefinition,
    CanCreateExecution,
    CanDeleteChecklistDraft,
    CanEditChecklistDraft,
    CanRetireChecklist,
    CanReviewChecklist,
    CanSubmitChecklistReview,
    CanViewChecklistDefinition,
    can_create_definition_for_scope,
    can_mutate_definition_scope,
    has_iig_checklist_permission,
)
from .serializers import (
    ApplicabilityRuleSerializer,
    ApproveSerializer,
    ChecklistDefinitionSerializer,
    ChecklistExecutionCreateSerializer,
    ChecklistExecutionSerializer,
    ChecklistQuestionSerializer,
    ChecklistResponseSerializer,
    ChecklistResponseUpdateSerializer,
    ChecklistSectionSerializer,
    ChecklistVersionSerializer,
    CloneDefinitionSerializer,
    EmptyActionSerializer,
    ReturnSerializer,
    ReviewerConclusionSerializer,
    VersionActionSerializer,
)
from .services import (
    ChecklistVersionNotActive,
    CloneRequest,
    CloneSourceNotEligible,
    DuplicateCodeError,
    ExecutionAlreadyActive,
    FormulationVersionNotApproved,
    FormulationVersionTenantMismatch,
    IncompleteExecution,
    InvalidQuantityUnitConfig,
    MissingReturnReason,
    ReviewerConclusionCorrectionReasonRequired,
    ReviewerConclusionEmpty,
    ReviewerConclusionInvalidPayload,
    ReviewerConclusionInvalidState,
    ReviewerConclusionPayloadTooLarge,
    ReviewerConclusionPermissionDenied,
    ReviewerConclusionRequired,
    ReviewerConclusionStaleVersion,
    ReviewerConclusionTooLong,
    ReviewerConclusionWrongAnswerType,
    SelfApprovalForbidden,
    VersionAllocationConflict,
    clone_definition,
    create_execution,
    create_next_version,
    enter_reviewer_conclusion,
    transition_execution,
)
from .transitions import IllegalVersionTransition, VersionAction, validate_version_transition

_ACTION_EVENT_MAP = {
    VersionAction.SUBMIT_REVIEW: IigChecklistEvent.VERSION_SUBMITTED,
    VersionAction.APPROVE: IigChecklistEvent.VERSION_APPROVED,
    VersionAction.RETURN: IigChecklistEvent.VERSION_RETURNED,
    VersionAction.REJECT: IigChecklistEvent.VERSION_REJECTED,
    VersionAction.ACTIVATE: IigChecklistEvent.VERSION_ACTIVATED,
    VersionAction.SUPERSEDE: IigChecklistEvent.VERSION_SUPERSEDED,
    VersionAction.RETIRE: IigChecklistEvent.VERSION_RETIRED,
}


class _Pagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _require_tenant():
    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("Tenant context required.") from exc


def _get_definition_or_404(public_id, tenant):
    try:
        return ChecklistDefinition.objects.visible_to(tenant).get(public_id=public_id)
    except ChecklistDefinition.DoesNotExist as exc:
        raise NotFound("Checklist definition not found.") from exc


def _get_version_or_404(public_id, tenant):
    try:
        return (
            ChecklistVersion.objects.visible_to(tenant)
            .select_related("definition")
            .get(public_id=public_id)
        )
    except ChecklistVersion.DoesNotExist as exc:
        raise NotFound("Checklist version not found.") from exc


def _get_section_or_404(public_id, tenant):
    try:
        return (
            ChecklistSection.objects.visible_to(tenant)
            .select_related("checklist_version__definition")
            .get(public_id=public_id)
        )
    except ChecklistSection.DoesNotExist as exc:
        raise NotFound("Checklist section not found.") from exc


def _get_question_or_404(public_id, tenant):
    try:
        return (
            ChecklistQuestion.objects.visible_to(tenant)
            .select_related("section__checklist_version__definition")
            .get(public_id=public_id)
        )
    except ChecklistQuestion.DoesNotExist as exc:
        raise NotFound("Checklist question not found.") from exc


def _raise_django_validation_as_drf(exc: DjangoValidationError):
    detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
    raise ValidationError(detail) from exc


def _authorize_mutation(request, tenant, definition, required_codename):
    """Object-scope mutation gate -- must be called after resolving the
    target object's owning ChecklistDefinition and before any write or
    audit emission. See permissions.py::can_mutate_definition_scope()
    for what this actually checks; visibility (visible_to()) is never
    sufficient authorization to mutate on its own."""
    if not can_mutate_definition_scope(
        actor=request.user,
        definition=definition,
        tenant=tenant,
        required_permission=required_codename,
    ):
        if definition.scope_type == "platform_master":
            raise PermissionDenied(
                "Mutating platform-master content requires a separate, explicit "
                "platform-level authorization -- ordinary permission does not imply it."
            )
        raise PermissionDenied("You do not have permission to modify this checklist content.")


# --------------------------------------------------------------------------
# Definitions
# --------------------------------------------------------------------------


class ChecklistDefinitionListCreateView(APIView):
    pagination_class = _Pagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateChecklistDefinition()]
        return [CanViewChecklistDefinition()]

    def get(self, request):
        tenant = _require_tenant()
        queryset = ChecklistDefinition.objects.visible_to(tenant)
        scope_type = request.query_params.get("scope_type")
        if scope_type:
            queryset = queryset.filter(scope_type=scope_type)
        code = request.query_params.get("code")
        if code:
            queryset = queryset.filter(code__icontains=code)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(ChecklistDefinitionSerializer(page, many=True).data)

    def post(self, request):
        tenant = _require_tenant()
        serializer = ChecklistDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scope_type = serializer.validated_data["scope_type"]
        definition_tenant = tenant if scope_type == "tenant" else None

        # Centralized platform-master authorization check -- must run
        # before anything is created, and before the transaction even
        # opens, so a denied request never creates a definition/version
        # and never emits a success audit event. Same rule the clone
        # endpoint uses (see ChecklistDefinitionCloneView.post).
        if not can_create_definition_for_scope(actor=request.user, scope_type=scope_type):
            raise PermissionDenied(
                "Creating platform-master content requires a separate, explicit "
                "platform-level authorization -- ordinary create-definition "
                "permission does not imply it."
            )

        with transaction.atomic():
            try:
                definition = ChecklistDefinition(
                    code=serializer.validated_data["code"],
                    title=serializer.validated_data["title"],
                    description=serializer.validated_data.get("description", ""),
                    scope_type=scope_type,
                    tenant=definition_tenant,
                    created_by=request.user,
                )
                definition.full_clean()
                definition.save()
            except DjangoValidationError as exc:
                _raise_django_validation_as_drf(exc)
            except IntegrityError as exc:
                raise ValidationError(
                    {"error_code": "DUPLICATE_CODE", "detail": "Code already exists in this scope."}
                ) from exc

            emit(
                event_type=IigChecklistEvent.DEFINITION_CREATED,
                resource_id=str(definition.public_id),
                actor_id=request.user.id,
                actor_email=getattr(request.user, "email", ""),
                tenant_id=getattr(definition_tenant, "id", None),
                payload={"code": definition.code, "scope_type": scope_type},
            )
        return Response(
            ChecklistDefinitionSerializer(definition).data, status=status.HTTP_201_CREATED
        )


class ChecklistDefinitionDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "DELETE":
            return [CanDeleteChecklistDraft()]
        return [CanViewChecklistDefinition()]

    def get(self, request, public_id):
        tenant = _require_tenant()
        definition = _get_definition_or_404(public_id, tenant)
        return Response(ChecklistDefinitionSerializer(definition).data)

    def delete(self, request, public_id):
        """Narrow, permissioned exception only -- see spec §8b. Everything
        else is retired, never hard-deleted."""
        tenant = _require_tenant()
        with transaction.atomic():
            definition = (
                ChecklistDefinition.objects.visible_to(tenant)
                .select_for_update()
                .get(public_id=public_id)
            )
            _authorize_mutation(request, tenant, definition, PERM_DELETE_DRAFT)
            versions = list(definition.versions.all())
            if len(versions) != 1:
                raise ValidationError("Only a definition with exactly one version may be deleted.")
            version = versions[0]
            if version.status != ChecklistVersionStatus.DRAFT or version.submitted_at is not None:
                raise ValidationError(
                    "Only a definition whose single version has never been "
                    "submitted for review may be deleted."
                )

            # Audit is emitted before the cascade delete -- AuditEvent
            # stores denormalized JSON/string metadata, never a live FK
            # into the deleted row, so the event survives intact.
            emit(
                event_type=IigChecklistEvent.DEFINITION_DELETED,
                resource_id=str(definition.public_id),
                actor_id=request.user.id,
                actor_email=getattr(request.user, "email", ""),
                tenant_id=getattr(definition.tenant, "id", None),
                payload={"code": definition.code, "scope_type": definition.scope_type},
            )
            # ChecklistVersion.definition is on_delete=PROTECT (governed
            # versions must never be silently cascaded away) -- the single
            # eligible version must be removed explicitly before the
            # definition, since every condition above already proved it
            # safe to delete (never submitted, still draft).
            version.delete()
            definition.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChecklistDefinitionCloneView(APIView):
    required_permission = CanCloneChecklist

    def get_permissions(self):
        return [self.required_permission()]

    def post(self, request, public_id):
        tenant = _require_tenant()
        definition = _get_definition_or_404(public_id, tenant)
        serializer = CloneDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_version = _get_version_or_404(data["source_version_public_id"], tenant)
        if source_version.definition_id != definition.id:
            raise NotFound("Source version does not belong to this definition.")

        target_scope_type = data["target_scope_type"]
        target_tenant = None
        if target_scope_type == "tenant":
            from tenancy.models import Tenant

            try:
                target_tenant = Tenant.objects.get(public_id=data["target_tenant_public_id"])
            except Tenant.DoesNotExist as exc:
                raise NotFound("Target tenant not found.") from exc
            if target_tenant.id != tenant.id:
                # Cross-tenant cloning requires a separate, explicit
                # platform-level grant this permission alone does not
                # imply -- see spec §8a.
                raise PermissionDenied(
                    "Cloning into a different tenant requires a separate authorization."
                )
        else:
            # target_scope_type == "platform_master" -- same centralized
            # authorization rule as the direct-create endpoint. Cloning
            # is not a separate way to acquire platform authority: an
            # ordinary CanCloneChecklist grant never implies it,
            # regardless of who owns the source content.
            if not can_create_definition_for_scope(
                actor=request.user, scope_type=target_scope_type
            ):
                raise PermissionDenied(
                    "Cloning into platform-master scope requires a separate, "
                    "explicit platform-level authorization -- ordinary clone "
                    "permission does not imply it."
                )

        try:
            result = clone_definition(
                CloneRequest(
                    source_version=source_version,
                    target_scope_type=target_scope_type,
                    target_tenant=target_tenant,
                    new_code=data["new_code"],
                    new_title=data["new_title"],
                    actor=request.user,
                    clone_sections=data["clone_sections"],
                    clone_questions=data["clone_questions"],
                    clone_applicability_rules=data["clone_applicability_rules"],
                    reason=data.get("reason", ""),
                )
            )
        except CloneSourceNotEligible as exc:
            raise ValidationError(str(exc)) from exc
        except DuplicateCodeError as exc:
            raise ValidationError({"error_code": "DUPLICATE_CODE", "detail": str(exc)}) from exc
        except CodeValidationError as exc:
            raise ValidationError({"error_code": exc.error_code, "detail": str(exc)}) from exc

        return Response(
            {
                "public_id": str(result.definition.public_id),
                "code": result.definition.code,
                "title": result.definition.title,
                "scope_type": result.definition.scope_type,
                "tenant_public_id": (
                    str(result.definition.tenant.public_id) if result.definition.tenant_id else None
                ),
                "current_version": {
                    "public_id": str(result.version.public_id),
                    "version_number": result.version.version_number,
                    "status": result.version.status,
                    "cloned_from_version_public_id": str(source_version.public_id),
                },
            },
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


class ChecklistVersionCreateView(APIView):
    required_permission = CanCreateChecklistDefinition
    pagination_class = _Pagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [CanViewChecklistDefinition()]
        return [self.required_permission()]

    def get(self, request, public_id):
        tenant = _require_tenant()
        definition = _get_definition_or_404(public_id, tenant)
        queryset = definition.versions.order_by("-version_number")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(ChecklistVersionSerializer(page, many=True).data)

    def post(self, request, public_id):
        tenant = _require_tenant()
        definition = _get_definition_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, definition, PERM_CREATE_DEFINITION)
        try:
            version = create_next_version(definition=definition, actor=request.user)
        except VersionAllocationConflict as exc:
            raise ValidationError(
                {"error_code": "VERSION_ALLOCATION_CONFLICT", "detail": str(exc)}
            ) from exc
        return Response(ChecklistVersionSerializer(version).data, status=status.HTTP_201_CREATED)


class ChecklistVersionDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [CanEditChecklistDraft()]
        return [CanViewChecklistDefinition()]

    def get(self, request, public_id):
        tenant = _require_tenant()
        version = _get_version_or_404(public_id, tenant)
        data = ChecklistVersionSerializer(version).data
        data["sections"] = [
            {
                **ChecklistSectionSerializer(section).data,
                "questions": [ChecklistQuestionSerializer(q).data for q in section.questions.all()],
            }
            for section in version.sections.all()
        ]
        return Response(data)

    def patch(self, request, public_id):
        tenant = _require_tenant()
        with transaction.atomic():
            version = (
                ChecklistVersion.objects.visible_to(tenant)
                .select_related("definition")
                .select_for_update()
                .get(public_id=public_id)
            )
            _authorize_mutation(request, tenant, version.definition, PERM_EDIT_DRAFT)
            if not version.is_editable():
                raise ValidationError(
                    {
                        "error_code": "VERSION_NO_LONGER_EDITABLE",
                        "detail": f"Version is {version.status!r}, no longer editable.",
                    }
                )
            for field in ("effective_date", "expiry_date", "regulatory_basis", "change_summary"):
                if field in request.data:
                    setattr(version, field, request.data[field])
            try:
                version.full_clean()
                version.save()
            except DjangoValidationError as exc:
                _raise_django_validation_as_drf(exc)
        return Response(ChecklistVersionSerializer(version).data)


class _ChecklistVersionActionViewBase(APIView):
    """Shared action plumbing for submit-review/approve/return/reject/
    activate/supersede/retire -- structurally identical in shape to
    fda_data's _MappingActionViewBase. Every transition is validated
    against validate_version_transition() before any mutation; an
    illegal transition returns a structured 400 with the row untouched
    and no audit event emitted."""

    action: str = ""
    self_approval_forbidden: bool = False
    required_permission = CanReviewChecklist

    def get_permissions(self):
        return [self.required_permission()]

    def post(self, request, public_id):
        tenant = _require_tenant()
        serializer = VersionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        with transaction.atomic():
            try:
                version = (
                    ChecklistVersion.objects.visible_to(tenant)
                    .select_related("definition")
                    .select_for_update()
                    .get(public_id=public_id)
                )
            except ChecklistVersion.DoesNotExist as exc:
                raise NotFound("Checklist version not found.") from exc

            _authorize_mutation(
                request, tenant, version.definition, self.required_permission.required_codename
            )

            previous_status = version.status
            try:
                target_status = validate_version_transition(version.status, self.action)
            except IllegalVersionTransition as exc:
                raise ValidationError(str(exc)) from exc

            if self.action == VersionAction.ACTIVATE and not version.effective_date:
                raise ValidationError("effective_date is required before activation.")

            if self.action == VersionAction.ACTIVATE:
                other_active = (
                    ChecklistVersion.objects.select_for_update()
                    .filter(
                        definition_id=version.definition_id,
                        status=ChecklistVersionStatus.ACTIVE,
                    )
                    .exclude(pk=version.pk)
                )
                for prior_active in other_active:
                    prior_active.status = ChecklistVersionStatus.SUPERSEDED
                    prior_active.save(update_fields=["status", "updated_at"])
                    emit(
                        event_type=IigChecklistEvent.VERSION_SUPERSEDED,
                        resource_id=str(prior_active.public_id),
                        actor_id=request.user.id,
                        actor_email=getattr(request.user, "email", ""),
                        tenant_id=getattr(version.definition.tenant, "id", None),
                        payload={"superseded_by": str(version.public_id)},
                    )

            if self.self_approval_forbidden and version.submitted_by_id == request.user.id:
                raise ValidationError("A user cannot approve a version they submitted for review.")

            now = timezone.now()
            if self.action == VersionAction.SUBMIT_REVIEW:
                version.submitted_by = request.user
                version.submitted_at = now
            elif self.action == VersionAction.APPROVE:
                version.approved_by = request.user
                version.approved_at = now
            elif self.action == VersionAction.RETURN:
                version.returned_by = request.user
                version.returned_at = now
                if reason:
                    version.return_reason = reason
            elif self.action == VersionAction.REJECT:
                version.rejected_by = request.user
                version.rejected_at = now
            elif self.action == VersionAction.ACTIVATE:
                version.activated_by = request.user
                version.activated_at = now
            elif self.action == VersionAction.RETIRE:
                version.retired_by = request.user
                version.retired_at = now

            version.status = target_status
            try:
                version.full_clean()
                version.save()
            except DjangoValidationError as exc:
                _raise_django_validation_as_drf(exc)

            emit(
                event_type=_ACTION_EVENT_MAP[self.action],
                resource_id=str(version.public_id),
                actor_id=request.user.id,
                actor_email=getattr(request.user, "email", ""),
                tenant_id=getattr(version.definition.tenant, "id", None),
                payload={"previous_status": previous_status, "new_status": target_status},
            )
        return Response(ChecklistVersionSerializer(version).data)


class ChecklistVersionSubmitReviewView(_ChecklistVersionActionViewBase):
    action = VersionAction.SUBMIT_REVIEW
    required_permission = CanSubmitChecklistReview


class ChecklistVersionApproveView(_ChecklistVersionActionViewBase):
    action = VersionAction.APPROVE
    required_permission = CanApproveChecklist
    self_approval_forbidden = True


class ChecklistVersionReturnView(_ChecklistVersionActionViewBase):
    action = VersionAction.RETURN
    required_permission = CanReviewChecklist


class ChecklistVersionRejectView(_ChecklistVersionActionViewBase):
    action = VersionAction.REJECT
    required_permission = CanReviewChecklist


class ChecklistVersionActivateView(_ChecklistVersionActionViewBase):
    action = VersionAction.ACTIVATE
    required_permission = CanActivateChecklist


class ChecklistVersionSupersedeView(_ChecklistVersionActionViewBase):
    action = VersionAction.SUPERSEDE
    required_permission = CanActivateChecklist


class ChecklistVersionRetireView(_ChecklistVersionActionViewBase):
    action = VersionAction.RETIRE
    required_permission = CanRetireChecklist


# --------------------------------------------------------------------------
# Sections / questions / applicability rules
# --------------------------------------------------------------------------


def _require_editable(version: ChecklistVersion):
    if not version.is_editable():
        raise ValidationError(
            {
                "error_code": "VERSION_NO_LONGER_EDITABLE",
                "detail": f"Version is {version.status!r}, not editable.",
            }
        )


class ChecklistSectionListCreateView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        if self.request.method == "GET":
            return [CanViewChecklistDefinition()]
        return [self.required_permission()]

    def get(self, request, public_id):
        tenant = _require_tenant()
        version = _get_version_or_404(public_id, tenant)
        return Response(ChecklistSectionSerializer(version.sections.all(), many=True).data)

    def post(self, request, public_id):
        tenant = _require_tenant()
        version = _get_version_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, version.definition, PERM_EDIT_DRAFT)
        _require_editable(version)
        serializer = ChecklistSectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            section = ChecklistSection(checklist_version=version, **serializer.validated_data)
            section.full_clean()
            section.save()
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        emit(
            event_type=IigChecklistEvent.SECTION_CREATED,
            resource_id=str(section.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(version.definition.tenant, "id", None),
            payload={"checklist_version_public_id": str(version.public_id)},
        )
        return Response(ChecklistSectionSerializer(section).data, status=status.HTTP_201_CREATED)


class ChecklistSectionDetailView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        return [self.required_permission()]

    def patch(self, request, public_id):
        tenant = _require_tenant()
        section = _get_section_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, section.checklist_version.definition, PERM_EDIT_DRAFT)
        _require_editable(section.checklist_version)
        for field in ("title", "description", "display_order", "criticality"):
            if field in request.data:
                setattr(section, field, request.data[field])
        try:
            section.full_clean()
            section.save()
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        emit(
            event_type=IigChecklistEvent.SECTION_UPDATED,
            resource_id=str(section.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(section.checklist_version.definition.tenant, "id", None),
            payload={},
        )
        return Response(ChecklistSectionSerializer(section).data)

    def delete(self, request, public_id):
        tenant = _require_tenant()
        section = _get_section_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, section.checklist_version.definition, PERM_EDIT_DRAFT)
        _require_editable(section.checklist_version)
        section_public_id = str(section.public_id)
        section.delete()
        emit(
            event_type=IigChecklistEvent.SECTION_DELETED,
            resource_id=section_public_id,
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChecklistQuestionListCreateView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        return [self.required_permission()]

    def post(self, request, public_id):
        tenant = _require_tenant()
        section = _get_section_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, section.checklist_version.definition, PERM_EDIT_DRAFT)
        _require_editable(section.checklist_version)
        serializer = ChecklistQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            question = ChecklistQuestion(section=section, **serializer.validated_data)
            question.full_clean()
            question.save()
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        emit(
            event_type=IigChecklistEvent.QUESTION_CREATED,
            resource_id=str(question.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(section.checklist_version.definition.tenant, "id", None),
            payload={"section_public_id": str(section.public_id)},
        )
        return Response(ChecklistQuestionSerializer(question).data, status=status.HTTP_201_CREATED)


class ChecklistQuestionDetailView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        return [self.required_permission()]

    def patch(self, request, public_id):
        tenant = _require_tenant()
        question = _get_question_or_404(public_id, tenant)
        _authorize_mutation(
            request, tenant, question.section.checklist_version.definition, PERM_EDIT_DRAFT
        )
        _require_editable(question.section.checklist_version)
        editable_fields = [
            "question_text",
            "help_text",
            "display_order",
            "answer_type",
            "data_source_classification",
            "required",
            "allowed_units",
            "evidence_requirement",
            "calculation_binding_identifier",
            "prefill_source",
            "reviewer_confirmation_required",
            "escalation_rule_identifier",
            "criticality",
            "regulatory_reference",
            "default_value_binding",
            "validation_rule",
        ]
        for field in editable_fields:
            if field in request.data:
                setattr(question, field, request.data[field])
        try:
            question.full_clean()
            question.save()
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        emit(
            event_type=IigChecklistEvent.QUESTION_UPDATED,
            resource_id=str(question.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(question.section.checklist_version.definition.tenant, "id", None),
            payload={},
        )
        return Response(ChecklistQuestionSerializer(question).data)

    def delete(self, request, public_id):
        tenant = _require_tenant()
        question = _get_question_or_404(public_id, tenant)
        _authorize_mutation(
            request, tenant, question.section.checklist_version.definition, PERM_EDIT_DRAFT
        )
        _require_editable(question.section.checklist_version)
        question_public_id = str(question.public_id)
        question.delete()
        emit(
            event_type=IigChecklistEvent.QUESTION_DELETED,
            resource_id=question_public_id,
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApplicabilityRuleListCreateView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        if self.request.method == "GET":
            return [CanViewChecklistDefinition()]
        return [self.required_permission()]

    def get(self, request, public_id):
        tenant = _require_tenant()
        version = _get_version_or_404(public_id, tenant)
        return Response(
            ApplicabilityRuleSerializer(version.applicability_rules.all(), many=True).data
        )

    def post(self, request, public_id):
        tenant = _require_tenant()
        version = _get_version_or_404(public_id, tenant)
        _authorize_mutation(request, tenant, version.definition, PERM_EDIT_DRAFT)
        _require_editable(version)
        serializer = ApplicabilityRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = ApplicabilityRule(
                checklist_version=version, created_by=request.user, **serializer.validated_data
            )
            rule.full_clean()
            rule.save()
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        emit(
            event_type=IigChecklistEvent.APPLICABILITY_RULE_CREATED,
            resource_id=str(rule.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(version.definition.tenant, "id", None),
            payload={"checklist_version_public_id": str(version.public_id)},
        )
        return Response(ApplicabilityRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class ApplicabilityRuleValidateView(APIView):
    required_permission = CanEditChecklistDraft

    def get_permissions(self):
        return [self.required_permission()]

    def post(self, request):
        """Validate a condition_json payload without persisting it --
        used by the frontend rule editor for live feedback."""
        from .applicability import ApplicabilityRuleValidationError, validate_condition_json
        from .field_registry import FIELD_REGISTRY_VERSION, is_known_registry_version

        condition_json = request.data.get("condition_json")
        registry_version = request.data.get("field_registry_version", FIELD_REGISTRY_VERSION)
        if not is_known_registry_version(registry_version):
            raise ValidationError(
                {
                    "error_code": "UNSUPPORTED_FIELD_REGISTRY_VERSION",
                    "detail": "Unknown registry version.",
                }
            )
        try:
            validate_condition_json(condition_json, registry_version)
        except ApplicabilityRuleValidationError as exc:
            raise ValidationError({"error_code": exc.error_code, "detail": str(exc)}) from exc

        emit(
            event_type=IigChecklistEvent.APPLICABILITY_RULE_VALIDATED,
            resource_id="",
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            payload={"field_registry_version": registry_version},
        )
        return Response({"valid": True})


# ---------------------------------------------------------------------------
# Milestone 4D-2 -- Execution and Response views
# ---------------------------------------------------------------------------


def _get_execution_or_404(public_id, tenant):
    try:
        return (
            ChecklistExecution.objects.visible_to(tenant)
            .select_related(
                "checklist_version",
                "formulation_version",
                "created_by",
                "submitted_by",
                "returned_by",
                "approved_by",
                "rejected_by",
                "cancelled_by",
            )
            .get(public_id=public_id)
        )
    except ChecklistExecution.DoesNotExist as exc:
        raise NotFound() from exc


class ChecklistExecutionListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateExecution()]
        # GET: inline has_iig_checklist_permission check inside get() handles
        # authorization; no class-level gate needed.
        return []

    def get(self, request):
        tenant = _require_tenant()
        if not has_iig_checklist_permission(request.user, tenant, "iig_checklist.view_execution"):
            raise PermissionDenied()
        qs = (
            ChecklistExecution.objects.visible_to(tenant)
            .select_related(
                "checklist_version",
                "formulation_version",
                "created_by",
                "submitted_by",
                "returned_by",
                "approved_by",
                "rejected_by",
                "cancelled_by",
            )
            .order_by("-created_at")
        )
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ChecklistExecutionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        tenant = _require_tenant()
        serializer = ChecklistExecutionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)
        try:
            execution = create_execution(
                tenant=tenant,
                checklist_version_public_id=serializer.validated_data[
                    "checklist_version_public_id"
                ],
                formulation_version_public_id=serializer.validated_data[
                    "formulation_version_public_id"
                ],
                actor=request.user,
            )
        except ExecutionAlreadyActive:
            return Response(
                {
                    "error_code": "execution_already_active",
                    "detail": "An active execution already exists for this combination.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ChecklistVersionNotActive:
            return Response(
                {
                    "error_code": "checklist_version_not_active",
                    "detail": "Checklist version is not active.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FormulationVersionTenantMismatch:
            return Response(
                {
                    "error_code": "formulation_version_tenant_mismatch",
                    "detail": "Formulation version does not belong to this tenant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FormulationVersionNotApproved:
            return Response(
                {
                    "error_code": "formulation_version_not_approved",
                    "detail": "Formulation version is not approved.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidQuantityUnitConfig as exc:
            return Response(
                {
                    "error_code": "execution_invalid_quantity_unit_config",
                    "detail": (
                        f"Question {exc} has answer_type quantity_with_unit but allowed_units is"
                        " empty. Contact the checklist administrator to correct the definition"
                        " version before creating an execution."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ChecklistExecutionSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )


class ChecklistExecutionDetailView(APIView):
    def get(self, request, public_id):
        tenant = _require_tenant()
        # visible_to() scopes to the request tenant — cross-tenant IDs are 404.
        execution = _get_execution_or_404(public_id, tenant)
        if not has_iig_checklist_permission(request.user, tenant, PERM_VIEW_EXECUTION):
            raise PermissionDenied()
        return Response(ChecklistExecutionSerializer(execution).data)


class _ChecklistExecutionActionViewBase(APIView):
    action: str = ""
    serializer_class = EmptyActionSerializer
    permission_codename: str = ""

    def post(self, request, public_id):
        tenant = _require_tenant()
        # Object lookup first — cross-tenant IDs return 404 via visible_to().
        execution = _get_execution_or_404(public_id, tenant)
        if self.permission_codename and not has_iig_checklist_permission(
            request.user, tenant, self.permission_codename
        ):
            raise PermissionDenied()

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)

        kwargs = dict(serializer.validated_data)

        try:
            updated = transition_execution(
                execution=execution,
                action=self.action,
                actor=request.user,
                tenant=tenant,
                **kwargs,
            )
        except IllegalExecutionTransition as exc:
            return Response(
                {"error_code": "illegal_execution_transition", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IncompleteExecution as exc:
            return Response(
                {"error_code": "incomplete_execution", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MissingReturnReason:
            return Response(
                {"error_code": "missing_return_reason", "detail": "return_reason is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionRequired:
            return Response(
                {
                    "error_code": "reviewer_conclusion_required",
                    "detail": "reviewer_conclusion_note is required to approve.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SelfApprovalForbidden:
            return Response(
                {
                    "error_code": "self_approval_forbidden",
                    "detail": "You cannot approve an execution you submitted.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(ChecklistExecutionSerializer(updated).data)


class ChecklistExecutionSubmitView(_ChecklistExecutionActionViewBase):
    action = "submit_review"
    permission_codename = PERM_SUBMIT_EXECUTION


class ChecklistExecutionApproveView(_ChecklistExecutionActionViewBase):
    action = "approve"
    serializer_class = ApproveSerializer
    permission_codename = PERM_APPROVE_EXECUTION


class ChecklistExecutionReturnView(_ChecklistExecutionActionViewBase):
    action = "return"
    serializer_class = ReturnSerializer
    permission_codename = PERM_REVIEW_EXECUTION


class ChecklistExecutionRejectView(_ChecklistExecutionActionViewBase):
    action = "reject"
    permission_codename = PERM_APPROVE_EXECUTION


class ChecklistExecutionCancelView(_ChecklistExecutionActionViewBase):
    action = "cancel"
    permission_codename = PERM_CANCEL_EXECUTION


class ChecklistExecutionSupersedeView(_ChecklistExecutionActionViewBase):
    action = "supersede"
    permission_codename = PERM_SUPERSEDE_EXECUTION


class ChecklistResponseListView(APIView):
    def get(self, request, public_id):
        tenant = _require_tenant()
        # Object lookup first — cross-tenant IDs return 404 via visible_to().
        execution = _get_execution_or_404(public_id, tenant)
        if not has_iig_checklist_permission(request.user, tenant, PERM_VIEW_EXECUTION):
            raise PermissionDenied()
        responses = (
            ChecklistResponse.objects.filter(
                execution=execution,
            )
            .select_related("question", "entered_by", "confirmed_by")
            .order_by("created_at")
        )
        paginator = _Pagination()
        page = paginator.paginate_queryset(responses, request)
        return paginator.get_paginated_response(ChecklistResponseSerializer(page, many=True).data)


class ChecklistResponseUpdateView(APIView):
    def patch(self, request, public_id, response_public_id):
        from django.utils import timezone

        from .audit import IigChecklistEvent, emit
        from .enums import AnswerType

        tenant = _require_tenant()
        # Object lookup first — cross-tenant IDs return 404 via visible_to().
        execution = _get_execution_or_404(public_id, tenant)
        if not has_iig_checklist_permission(request.user, tenant, PERM_EDIT_EXECUTION):
            raise PermissionDenied()

        if execution.status not in {"draft", "returned"}:
            return Response(
                {
                    "error_code": "response_immutable",
                    "detail": "Responses cannot be modified outside draft or returned status.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            response = ChecklistResponse.objects.select_related("question").get(
                public_id=response_public_id,
                execution=execution,
            )
        except ChecklistResponse.DoesNotExist:
            raise NotFound() from None

        if response.question.answer_type == AnswerType.REVIEWER_CONCLUSION:
            return Response(
                {
                    "error_code": "reviewer_conclusion_wrong_answer_type",
                    "detail": (
                        "Use the /reviewer-conclusion/ endpoint for reviewer_conclusion questions."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ChecklistResponseUpdateSerializer(
            data=request.data,
            context={"question": response.question, "execution": execution, "tenant": tenant},
        )
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)

        prior_entered_by = response.entered_by_id

        data = serializer.validated_data
        for field in ("raw_value", "is_not_applicable", "not_applicable_reason", "override_reason"):
            if field in data:
                setattr(response, field, data[field])
        response.entered_by = request.user
        response.entered_at = timezone.now()

        try:
            response.full_clean()
            response.save()
        except DjangoValidationError as exc:
            raise ValidationError(
                {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
            ) from exc

        event_type = (
            IigChecklistEvent.RESPONSE_UPDATED
            if prior_entered_by
            else IigChecklistEvent.RESPONSE_ENTERED
        )

        def _audit():
            emit(
                event_type=event_type,
                resource_id=str(response.public_id),
                actor_id=request.user.id,
                actor_email=getattr(request.user, "email", ""),
                tenant_id=getattr(tenant, "id", None),
                payload={
                    "execution_public_id": str(execution.public_id),
                    "response_public_id": str(response.public_id),
                    "question_public_id": str(response.question.public_id),
                    "data_source_type_snapshot": response.data_source_type_snapshot,
                },
            )

        transaction.on_commit(_audit)
        return Response(ChecklistResponseSerializer(response).data)


class ChecklistReviewerConclusionView(APIView):
    # No class-level permission check — enter_reviewer_conclusion() uses
    # visible_to(tenant) first, so cross-tenant IDs return 404 before any
    # permission gate fires, and the service enforces PERM_REVIEW_EXECUTION
    # for in-tenant callers.

    def post(self, request, public_id, response_public_id):
        tenant = _require_tenant()
        serializer = ReviewerConclusionSerializer(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)

        try:
            response = enter_reviewer_conclusion(
                tenant=tenant,
                execution_public_id=public_id,
                response_public_id=response_public_id,
                actor=request.user,
                raw_value=serializer.validated_data["raw_value"],
                expected_version=serializer.validated_data["expected_version"],
                correction_reason=serializer.validated_data.get("correction_reason", ""),
            )
        except ReviewerConclusionInvalidState:
            return Response(
                {
                    "error_code": "reviewer_conclusion_invalid_state",
                    "detail": "Execution must be in submitted_for_review status.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ReviewerConclusionPermissionDenied:
            raise PermissionDenied() from None
        except ReviewerConclusionWrongAnswerType:
            return Response(
                {
                    "error_code": "reviewer_conclusion_wrong_answer_type",
                    "detail": "Question is not a reviewer_conclusion type.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionEmpty:
            return Response(
                {
                    "error_code": "reviewer_conclusion_empty",
                    "detail": "Reviewer conclusion must not be empty.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionTooLong:
            return Response(
                {
                    "error_code": "reviewer_conclusion_too_long",
                    "detail": "Reviewer conclusion exceeds 4000 characters.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionPayloadTooLarge:
            return Response(
                {
                    "error_code": "reviewer_conclusion_payload_too_large",
                    "detail": "Payload exceeds byte limit.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionStaleVersion:
            return Response(
                {
                    "error_code": "reviewer_conclusion_stale_version",
                    "detail": "expected_version does not match current version. Reload and retry.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ReviewerConclusionCorrectionReasonRequired:
            return Response(
                {
                    "error_code": "reviewer_conclusion_correction_reason_required",
                    "detail": (
                        "correction_reason is required when amending"
                        " an existing reviewer conclusion."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ReviewerConclusionInvalidPayload:
            return Response(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "Invalid raw_value structure.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ChecklistResponseSerializer(response).data)
