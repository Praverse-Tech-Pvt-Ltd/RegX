"""IIG checklist definition-governance API views.

UUID-only identifiers; permission enforcement on every endpoint; a
missing/forbidden record returns a generic 404; every lifecycle action
goes through the single authoritative transition service
(transitions.py) inside select_for_update()+transaction.atomic(), never
a generic status PATCH.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
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
from .execution_transitions import IllegalExecutionTransition, available_actions
from .models import (
    ApplicabilityRule,
    ChecklistDefinition,
    ChecklistExecution,
    ChecklistQuestion,
    ChecklistResponse,
    ChecklistSection,
    ChecklistVersion,
    GapAnalysis,
)
from .permissions import (
    PERM_APPROVE_EXECUTION,
    PERM_CANCEL_EXECUTION,
    PERM_CREATE_DEFINITION,
    PERM_DELETE_DRAFT,
    PERM_EDIT_DRAFT,
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
    CanGenerateGapAnalysis,
    CanRetireChecklist,
    CanReviewChecklist,
    CanSubmitChecklistReview,
    CanViewChecklistDefinition,
    CanViewExecution,
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
    ChecklistSectionSerializer,
    ChecklistVersionSerializer,
    CloneDefinitionSerializer,
    EmptyActionSerializer,
    GapAnalysisDetailSerializer,
    GapAnalysisSerializer,
    ReturnSerializer,
    ReviewerConclusionSerializer,
    SupersedeSerializer,
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
    InvalidCalculationBinding,
    InvalidQuantityUnitConfig,
    MissingReturnReason,
    MissingSupersedeReason,
    NoEligibleSubjectComponent,
    ReviewerConclusionCorrectionReasonRequired,
    ReviewerConclusionEmpty,
    ReviewerConclusionInvalidExpectedVersion,
    ReviewerConclusionInvalidPayload,
    ReviewerConclusionInvalidState,
    ReviewerConclusionPayloadTooLarge,
    ReviewerConclusionPermissionDenied,
    ReviewerConclusionRequired,
    ReviewerConclusionStaleVersion,
    ReviewerConclusionTooLong,
    ReviewerConclusionWrongAnswerType,
    SelfApprovalForbidden,
    SubjectComponentNotInFormulationVersion,
    SubjectComponentNotPermittedForScope,
    SubjectComponentRequired,
    UnclassifiedChecklistExecutionScope,
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
                    # QA-01: OQ-8's governed classification, validated by the
                    # serializer; it was accepted and then dropped here.
                    execution_scope=serializer.validated_data.get("execution_scope", ""),
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
                payload={
                    "code": definition.code,
                    "scope_type": scope_type,
                    "execution_scope": definition.execution_scope,
                },
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
        # QA-06(a): the request body was ignored, so an effective_date sent here was
        # dropped. The same draft fields a PATCH may set are now saved at creation
        # (validated by the model; a bad value is a 400, never silence).
        fields = {f: request.data[f] for f in VERSION_DRAFT_FIELDS if f in request.data}
        try:
            version = create_next_version(definition=definition, actor=request.user, fields=fields)
        except VersionAllocationConflict as exc:
            raise ValidationError(
                {"error_code": "VERSION_ALLOCATION_CONFLICT", "detail": str(exc)}
            ) from exc
        except DjangoValidationError as exc:
            _raise_django_validation_as_drf(exc)
        return Response(ChecklistVersionSerializer(version).data, status=status.HTTP_201_CREATED)


#: Draft fields a version may carry from creation and change while editable (PATCH).
VERSION_DRAFT_FIELDS = (
    "effective_date",
    "expiry_date",
    "regulatory_basis",
    "jurisdiction",
    "change_summary",
)


def _raise_if_activation_prerequisites_missing(version, action) -> None:
    """What activation needs, checked before submit, approve and activate (QA-06(b)).

    Runs before any lifecycle mutation -- including superseding a prior active
    version -- so a failure leaves everything intact. Milestone 4D-3
    (M4D3-REG-018/019): every calculation-registry binding must resolve against
    the version's own persisted content.
    """
    from .activation_validation import (
        format_activation_errors,
        validate_version_calculation_bindings,
    )

    if not version.effective_date:
        step = {
            VersionAction.SUBMIT_REVIEW: "submitting for review",
            VersionAction.APPROVE: "approval",
            VersionAction.ACTIVATE: "activation",
        }[action]
        raise ValidationError(f"effective_date is required before {step}.")
    binding_findings = validate_version_calculation_bindings(version)
    if binding_findings:
        raise ValidationError(format_activation_errors(binding_findings))


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
            # `5A-DEC-005` -- jurisdiction is editable here for the same reason
            # regulatory_basis is: both describe what the draft will be approved
            # against, and both freeze together when it leaves draft/returned.
            fields_changed = []
            for field in VERSION_DRAFT_FIELDS:
                if field in request.data:
                    setattr(version, field, request.data[field])
                    fields_changed.append(field)
            try:
                version.full_clean()
                version.save()
            except DjangoValidationError as exc:
                _raise_django_validation_as_drf(exc)

            # These fields describe what the version will be approved against,
            # so changing them changes the basis of a later approval. Every
            # other transition on this version is audited; the edit that
            # precedes them was not.
            #
            # After save() and inside the same transaction: a validation
            # failure raises above, so a rejected edit records nothing, and a
            # rollback takes the audit row with it.
            #
            # Field names only -- see audit._PAYLOAD_ALLOW_LISTS for why the
            # values stay out.
            if fields_changed:
                emit(
                    event_type=IigChecklistEvent.VERSION_UPDATED,
                    resource_type="iig_checklist_version",
                    resource_id=str(version.public_id),
                    actor_id=request.user.id,
                    actor_email=getattr(request.user, "email", ""),
                    tenant_id=getattr(version.definition.tenant, "id", None),
                    payload={
                        "version_public_id": str(version.public_id),
                        "definition_public_id": str(version.definition.public_id),
                        "version_number": version.version_number,
                        "status": version.status,
                        "fields_changed": sorted(fields_changed),
                    },
                )
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

            # QA-06(b): the activation prerequisites are checked at submit and
            # approve too, so a version can never be approved and then fail to
            # activate (an approved version can no longer be edited or returned).
            if self.action in (
                VersionAction.SUBMIT_REVIEW,
                VersionAction.APPROVE,
                VersionAction.ACTIVATE,
            ):
                _raise_if_activation_prerequisites_missing(version, self.action)

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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
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
                # OQ-8: absent means "not supplied", which the service refuses
                # when the checklist content is component-specific.
                subject_component_public_id=serializer.validated_data.get(
                    "subject_component_public_id"
                ),
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
        except UnclassifiedChecklistExecutionScope:
            # Distinct from the subject-component errors on purpose: this says we
            # do not know what the checklist regulates, not that the formulation
            # cannot satisfy it.
            return Response(
                {
                    "error_code": "execution_scope_unclassified",
                    "detail": (
                        "This checklist definition has no governed execution scope, "
                        "so an execution cannot be created against it."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except NoEligibleSubjectComponent:
            return Response(
                {
                    "error_code": "subject_component_unavailable",
                    "detail": (
                        "This checklist is component-scoped, but the formulation "
                        "version has no eligible components."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SubjectComponentNotPermittedForScope:
            return Response(
                {
                    "error_code": "subject_component_not_permitted",
                    "detail": (
                        "This checklist is scoped to the formulation version, so a "
                        "subject component must not be supplied."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SubjectComponentRequired:
            return Response(
                {
                    "error_code": "subject_component_required",
                    "detail": (
                        "This checklist version contains component-specific content, "
                        "so a governed subject component must be supplied."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SubjectComponentNotInFormulationVersion:
            # Deliberately does not distinguish "no such component" from
            # "component belongs to another formulation or tenant": the caller
            # learns only that this one is not eligible here.
            return Response(
                {
                    "error_code": "subject_component_not_eligible",
                    "detail": (
                        "The subject component does not belong to this formulation version."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
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
        except InvalidCalculationBinding as exc:
            return Response(
                {
                    "error_code": "execution_invalid_calculation_binding",
                    "detail": (
                        f"Question {exc} is system_calculated but its calculation binding is"
                        " not an approved registry entry, or disagrees with the question's"
                        " answer type or source classification. Contact the checklist"
                        " administrator to correct the definition version before creating an"
                        " execution."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ChecklistExecutionSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )


def _execution_payload(execution, user, tenant) -> dict:
    """The execution as serialized, plus the actions this user may take now."""
    data = dict(ChecklistExecutionSerializer(execution).data)
    data["available_actions"] = available_actions(
        execution, user, lambda codename: has_iig_checklist_permission(user, tenant, codename)
    )
    return data


class ChecklistExecutionDetailView(APIView):
    def get(self, request, public_id):
        tenant = _require_tenant()
        # visible_to() scopes to the request tenant — cross-tenant IDs are 404.
        execution = _get_execution_or_404(public_id, tenant)
        if not has_iig_checklist_permission(request.user, tenant, PERM_VIEW_EXECUTION):
            raise PermissionDenied()
        return Response(_execution_payload(execution, request.user, tenant))


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
        except MissingSupersedeReason:
            return Response(
                {
                    "error_code": "missing_supersede_reason",
                    "detail": "A reason is required to supersede an approved execution.",
                },
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
        return Response(_execution_payload(updated, request.user, tenant))


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
    serializer_class = SupersedeSerializer
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
            # One extra query for every outcome on the page instead of one per
            # response: the serializer reads `calculation_outcomes.all()`, which
            # reuses this prefetch rather than re-querying per row. The current
            # row is chosen in Python by public_id, matching the writer, so no
            # per-row ordered queryset is needed here.
            .prefetch_related("calculation_outcomes")
            .order_by("created_at")
        )
        paginator = _Pagination()
        page = paginator.paginate_queryset(responses, request)
        return paginator.get_paginated_response(ChecklistResponseSerializer(page, many=True).data)


class ChecklistResponseUpdateView(APIView):
    """M4D3-SVC-004 -- a thin adapter over ``update_checklist_response()``.

    It validates nothing itself, mutates no model, emits no audit and holds no
    business rule: it calls the governed service and maps the governed
    exceptions onto the structured HTTP contract of Part 5.
    """

    def patch(self, request, public_id, response_public_id):
        from .services import (
            ResponseUpdateApplicabilityServerControlled,
            ResponseUpdateInvalidExpectedVersion,
            ResponseUpdateInvalidPayload,
            ResponseUpdateInvalidState,
            ResponseUpdatePermissionDenied,
            ResponseUpdateReservedReasonPrefix,
            ResponseUpdateServerControlledValue,
            ResponseUpdateStaleVersion,
            ResponseUpdateWrongAnswerType,
            update_checklist_response,
        )

        tenant = _require_tenant()

        try:
            result = update_checklist_response(
                tenant=tenant,
                execution_public_id=public_id,
                response_public_id=response_public_id,
                actor=request.user,
                payload=request.data,
            )
        except ResponseUpdatePermissionDenied:
            raise PermissionDenied() from None
        except ResponseUpdateInvalidState:
            return Response(
                {
                    "error_code": "response_immutable",
                    "detail": "Responses cannot be modified outside draft or returned status.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ResponseUpdateWrongAnswerType:
            return Response(
                {
                    "error_code": "reviewer_conclusion_wrong_answer_type",
                    "detail": (
                        "Use the /reviewer-conclusion/ endpoint for reviewer_conclusion questions."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ResponseUpdateServerControlledValue:
            # M4D3-SVC-005 -- the stored value is owned by a governed service.
            return Response(
                {
                    "error_code": "server_controlled_value",
                    "detail": (
                        "This response is populated by a governed service and is not "
                        "client-writable."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ResponseUpdateApplicabilityServerControlled:
            # M4D3-APP-009 fixes both the error_code and the status. 403 matches
            # its siblings M4D3-SVC-005 and M4D3-APP-011: the field is
            # server-owned, so this is an authorization objection, not a
            # malformed-payload one.
            return Response(
                {
                    "error_code": "applicability_server_controlled",
                    "detail": (
                        "Applicability for this response is governed by an "
                        "applicability rule and is not client-writable."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ResponseUpdateReservedReasonPrefix:
            # M4D3-APP-011 fixes the error_code and is silent on the status.
            # 403 matches its sibling M4D3-APP-009 and the M4D3-SVC-005
            # server-controlled rejection above: the value is server-owned.
            return Response(
                {
                    "error_code": "reserved_reason_prefix",
                    "detail": (
                        "not_applicable_reason must not begin with the reserved "
                        "REVIEW_REQUIRED: prefix; it is written only by a governed "
                        "server-side determination."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ResponseUpdateInvalidExpectedVersion:
            # M4D3-TXN-003 structural rejection. No clause names an API code for
            # it, so this follows the repository's existing structured-400
            # convention (as `invalid_raw_value_shape` does) rather than
            # inventing external vocabulary M4D3-OUT-005 still defers.
            return Response(
                {
                    "error_code": "invalid_expected_version",
                    "detail": (
                        "expected_version must be an integer of at least 1. Reload and retry."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ResponseUpdateStaleVersion:
            # M4D3-VER-005 -- nothing was written; the client reloads and retries.
            return Response(
                {
                    "error_code": "stale_version",
                    "detail": (
                        "expected_version does not match current version. Reload and retry."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ResponseUpdateInvalidPayload as exc:
            raise ValidationError(exc.errors) from None

        return Response(ChecklistResponseSerializer(result.response).data)


class ChecklistExecutionExportView(APIView):
    """MILESTONE_4D_DISCOVERY.md §17 -- a thin adapter over the export service.

    It selects the rendering format and maps governed refusals onto the
    structured HTTP contract. It assembles no provenance, computes no checksum
    and holds no business rule: all of that lives in ``controlled_export``, so a
    direct domain call is bound by exactly the same guards.
    """

    def get(self, request, public_id):
        from .controlled_export import (
            ExecutionNotExportable,
            ExportAuditFailed,
            ExportPermissionDenied,
            export_execution,
        )

        tenant = _require_tenant()
        # Deliberately NOT named `format`: that is DRF's reserved
        # URL_FORMAT_OVERRIDE parameter, so `?format=csv` is intercepted by
        # content negotiation and 404s on an unknown renderer before this view
        # ever runs. `export_format` is ours and reaches the service intact.
        fmt = request.query_params.get("export_format", "json").lower()
        if fmt not in {"json", "csv"}:
            # §17 ships JSON and CSV only; PDF/Word are deferred beyond 4D.
            return Response(
                {
                    "error_code": "unsupported_export_format",
                    "detail": "export_format must be one of: json, csv.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            artifact, rendered = export_execution(
                tenant=tenant,
                execution_public_id=public_id,
                actor=request.user,
                fmt=fmt,
            )
        except ExportPermissionDenied:
            return Response(
                {
                    "error_code": "export_permission_denied",
                    "detail": "Exporting a checklist execution requires a dedicated permission.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ExecutionNotExportable:
            return Response(
                {
                    "error_code": "execution_not_exportable",
                    "detail": "Only an approved checklist execution can be exported.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ExportAuditFailed:
            # QA-09: no file goes out without its audit record.
            return Response(
                {
                    "error_code": "export_not_recorded",
                    "detail": "The export could not be recorded, so it was not issued. Try again.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        checksum = artifact["checksum"]["value"]
        if fmt == "csv":
            response = HttpResponse(rendered, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = (
                f'attachment; filename="checklist-execution-{public_id}.csv"'
            )
        else:
            response = HttpResponse(rendered, content_type="application/json; charset=utf-8")
        # Surfaced as headers too so a client can verify the artifact it received
        # without re-parsing it.
        response["X-RegX-Export-Checksum"] = checksum
        response["X-RegX-Export-Schema-Version"] = artifact["payload"]["export_schema_version"]
        return response


class ChecklistCapabilitiesView(APIView):
    """`4D4-DEC-012` -- the minimal tenant-scoped capability surface.

    Advisory UI metadata **only**. The governed services remain authoritative:
    this endpoint cannot grant anything, and a client that ignores it still hits
    the same server-side refusal.

    Deliberately **not** `authorization.effective_permissions_view`, for two
    independent reasons. That endpoint reads the database ``Permission`` table,
    whereas ``iig_checklist`` authority lives in the governed ``ROLE_PERMISSIONS``
    mapping, so the override permission would never appear there. More seriously,
    it aggregates across *all* of a user's tenant memberships with no tenant
    scoping -- using it for a tenant-scoped decision would blur authority between
    tenants.

    The response carries **named capability flags**, never raw permission
    codenames, role identifiers or any other authorization internals: the client
    learns what it may do, not how permissions are modelled.
    """

    def get(self, request):
        from .permissions import (
            PERM_OVERRIDE_EXECUTION,
            PERM_REVIEW_EXECUTION,
            has_iig_checklist_permission,
        )

        # Fail-closed through the established convention: no tenant context is a
        # refusal, not an empty-but-successful answer.
        tenant = _require_tenant()
        # Each flag is derived independently from the same authoritative
        # predicate the corresponding governed service enforces with, so a
        # capability can never disagree with the service that owns it. They are
        # deliberately not folded into one "can review" notion: override and
        # reviewer conclusion are separate governed concepts with separate
        # permissions (`4D4-DEC-011`, and `PERM_REVIEW_EXECUTION` from 4D-2).
        return Response(
            {
                "can_override_response": has_iig_checklist_permission(
                    request.user, tenant, PERM_OVERRIDE_EXECUTION
                ),
                # `4D4-DEC-012` approved extension (2026-08-12).
                "can_enter_reviewer_conclusion": has_iig_checklist_permission(
                    request.user, tenant, PERM_REVIEW_EXECUTION
                ),
            }
        )


class ChecklistResponseOverrideView(APIView):
    """`4D4-DEC-007` -- the dedicated governed override action.

    Deliberately not the ordinary response PATCH: §12 requires enforcement "at
    the transition boundary, not just serializer validation", and §AC.5 keeps
    ``system_derived_value`` and ``override_reason`` off the ordinary update
    path entirely.

    A thin adapter. No class-level permission check -- the service performs the
    tenant-scoped lookup first, so a cross-tenant id returns 404 before any
    permission gate fires, and it enforces ``PERM_OVERRIDE_EXECUTION`` for
    in-tenant callers. Every rule lives in the service, so a direct domain call
    is bound by exactly the same guards.
    """

    def post(self, request, public_id, response_public_id):
        from .overrides import (
            OverrideClearNotSupported,
            OverrideInvalidExpectedVersion,
            OverrideInvalidPayload,
            OverrideInvalidState,
            OverrideNotOverridable,
            OverridePermissionDenied,
            OverrideReasonRequired,
            OverrideStaleVersion,
            override_checklist_response,
        )

        tenant = _require_tenant()
        try:
            result = override_checklist_response(
                tenant=tenant,
                execution_public_id=public_id,
                response_public_id=response_public_id,
                actor=request.user,
                payload=request.data,
            )
        except OverridePermissionDenied:
            return Response(
                {
                    "error_code": "override_permission_denied",
                    "detail": "Overriding a governed response requires a dedicated permission.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except OverrideNotOverridable:
            return Response(
                {
                    "error_code": "response_not_overridable",
                    "detail": "Only an FDA-derived default response may be overridden.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except OverrideInvalidState:
            return Response(
                {
                    "error_code": "override_invalid_state",
                    "detail": "Overrides are permitted only while the execution is editable.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except OverrideClearNotSupported:
            return Response(
                {
                    "error_code": "override_clear_not_supported",
                    "detail": "Clearing an override is not a supported governed transition.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OverrideReasonRequired:
            return Response(
                {
                    "error_code": "override_reason_required",
                    "detail": "override_reason is required and may not be blank.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OverrideInvalidExpectedVersion:
            return Response(
                {
                    "error_code": "invalid_expected_version",
                    "detail": "expected_version must be a positive integer.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OverrideStaleVersion:
            return Response(
                {
                    "error_code": "stale_expected_version",
                    "detail": "The response was modified by someone else; re-read and retry.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except OverrideInvalidPayload as exc:
            # `exc.errors` is the serializer's own governed error structure, not
            # exception text -- no internal detail leaks through this path.
            return Response(exc.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ChecklistResponseSerializer(result.response).data,
            status=status.HTTP_200_OK,
        )


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
        except ReviewerConclusionInvalidExpectedVersion:
            # `4D4-DEC-013` -- malformed, not stale. 400 with the same governed
            # code the other two write paths use, so a client sees one contract.
            return Response(
                {
                    "error_code": "invalid_expected_version",
                    "detail": "expected_version must be a positive integer.",
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


# ---------------------------------------------------------------------------
# Gap analysis -- a read-model over an execution's responses.
# ---------------------------------------------------------------------------


class ExecutionGapAnalysisView(APIView):
    """Score one execution: gaps, completeness, and a per-section breakdown.

    Computed on demand rather than stored. The legacy implementation persisted
    each run as an immutable report, which let a score be read long after the
    answers behind it had changed.
    """

    permission_classes = [CanViewExecution]

    def get(self, request, public_id):
        from .gap_analysis import analyse_execution

        tenant = _require_tenant()
        execution = _get_execution_or_404(public_id, tenant)
        result = analyse_execution(execution)

        # Audited on the read path because this is where the analysis happens:
        # the score is computed on demand and never stored, so without this the
        # fact that a score was produced leaves no trace at all.
        #
        # Emitted only after analyse_execution returns. A permission failure
        # raises in _get_execution_or_404 above, so a refused request cannot
        # record a successful generation.
        #
        # Only counts travel. `result` also holds `gaps` (question text and the
        # answer given) and `sections` (section names); the allow-list in
        # audit._PAYLOAD_ALLOW_LISTS drops both, and `section_count` is derived
        # here so the shape of the checklist is recorded without its content.
        emit(
            event_type=IigChecklistEvent.GAP_ANALYSIS_GENERATED,
            resource_type="iig_checklist_execution",
            resource_id=str(execution.public_id),
            actor_id=request.user.id,
            actor_email=getattr(request.user, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={
                "execution_public_id": str(execution.public_id),
                "checklist_version_public_id": str(execution.checklist_version.public_id),
                "total_questions": result.get("total_questions"),
                "answered": result.get("answered"),
                "unanswered": result.get("unanswered"),
                # P7 split review-required out of `unanswered`. Recording it
                # keeps this row consistent with the corrected
                # classification rather than under-reporting by the
                # difference.
                "review_required": result.get("review_required"),
                "not_applicable": result.get("not_applicable"),
                "gap_count": result.get("gap_count"),
                "score_percent": result.get("score_percent"),
                "completeness_percent": result.get("completeness_percent"),
                "section_count": len(result.get("sections") or []),
            },
        )
        return Response(result)


class ExecutionGapAnalysisSnapshotView(APIView):
    """Immutable gap-analysis snapshots for one execution.

    GET lists them, newest first, and reports whether the newest still matches
    the execution's current answers. POST takes one.

    Reading is `view_execution`; taking one is `generate_gap_analysis`, because
    writing a durable record is an act rather than a read. Both are resolved
    against the execution's own tenant, so there is no cross-tenant path.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanGenerateGapAnalysis()]
        return [CanViewExecution()]

    def get(self, request, public_id):
        from .gap_snapshots import analyses_for, current_input_hash

        tenant = _require_tenant()
        execution = _get_execution_or_404(public_id, tenant)
        analyses = list(
            analyses_for(execution, tenant).select_related("checklist_version", "generated_by")
        )
        current = current_input_hash(execution)
        return Response(
            {
                "current_input_hash": current,
                # Whether the newest snapshot still describes today's answers.
                # Cheap because it is a hash comparison, not a recomputed diff.
                "latest_is_current": bool(analyses) and analyses[0].input_hash == current,
                "results": GapAnalysisSerializer(analyses, many=True).data,
            }
        )

    def post(self, request, public_id):
        from .gap_snapshots import generate

        tenant = _require_tenant()
        execution = _get_execution_or_404(public_id, tenant)
        analysis, created = generate(execution=execution, tenant=tenant, actor=request.user)
        analysis = (
            GapAnalysis.objects.select_related("checklist_version", "generated_by")
            .prefetch_related("items__question__section")
            .get(pk=analysis.pk)
        )
        # 201 for a new snapshot, 200 when identical inputs returned the
        # existing one. The caller can tell the difference without guessing.
        return Response(
            GapAnalysisDetailSerializer(analysis).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class GapAnalysisDetailView(APIView):
    """One snapshot, with its items. Read-only: a snapshot is immutable."""

    permission_classes = [CanViewExecution]

    def get(self, request, public_id, analysis_public_id):
        from rest_framework.exceptions import NotFound

        tenant = _require_tenant()
        execution = _get_execution_or_404(public_id, tenant)
        try:
            analysis = (
                GapAnalysis.objects.select_related("checklist_version", "generated_by")
                .prefetch_related("items__question__section")
                .get(public_id=analysis_public_id, tenant=tenant, execution=execution)
            )
        except GapAnalysis.DoesNotExist:
            raise NotFound() from None
        return Response(GapAnalysisDetailSerializer(analysis).data)
