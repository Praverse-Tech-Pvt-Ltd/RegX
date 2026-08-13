"""Serializers for the IIG checklist definition-governance API.

UUID-only external identifiers; no `status` field on any plain-edit
serializer (status only changes through the dedicated lifecycle-action
endpoints, see views.py); code fields are normalized before validation.
"""

import json

from rest_framework import serializers

from .codes import CodeValidationError, normalize_code
from .execution_constants import (
    MAX_FREE_TEXT_CHARS,
    MAX_NOT_APPLICABLE_REASON_CHARS,
    MAX_RAW_VALUE_BYTES,
    MAX_RETURN_REASON_CHARS,
    MAX_REVIEWER_CONCLUSION_CHARS,
)
from .models import (
    ApplicabilityRule,
    ChecklistDefinition,
    ChecklistExecution,
    ChecklistQuestion,
    ChecklistResponse,
    ChecklistSection,
    ChecklistVersion,
)


def _normalize_code_field(value):
    try:
        return normalize_code(value)
    except CodeValidationError as exc:
        raise serializers.ValidationError(
            {"error_code": exc.error_code, "detail": str(exc)}
        ) from exc


class ChecklistDefinitionSerializer(serializers.ModelSerializer):
    tenant_public_id = serializers.UUIDField(source="tenant.public_id", read_only=True)

    class Meta:
        model = ChecklistDefinition
        fields = [
            "public_id",
            "code",
            "title",
            "description",
            "scope_type",
            "tenant_public_id",
        ]
        read_only_fields = ["public_id"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistVersionSerializer(serializers.ModelSerializer):
    definition_public_id = serializers.UUIDField(source="definition.public_id", read_only=True)
    scope_type = serializers.CharField(source="definition.scope_type", read_only=True)

    class Meta:
        model = ChecklistVersion
        fields = [
            "public_id",
            "definition_public_id",
            "scope_type",
            "version_number",
            "status",
            "effective_date",
            "expiry_date",
            "regulatory_basis",
            # `5A-DEC-005` -- writable while the version is a draft, then frozen by
            # ChecklistVersion.clean() like the regulatory basis it qualifies.
            "jurisdiction",
            "change_summary",
            "cloned_from_version_public_id",
        ]
        # status/version_number are never client-writable through this
        # plain serializer -- status only via the action endpoints,
        # version_number only via the create_next_version() service.
        read_only_fields = [
            "public_id",
            "version_number",
            "status",
            "cloned_from_version_public_id",
        ]


class ApplicabilityRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicabilityRule
        fields = [
            "public_id",
            "code",
            "rule_version",
            "condition_json",
            "outcome_if_true",
            "outcome_if_false",
            "reason_code",
            "explanation_template",
            "field_registry_version",
            "status",
        ]
        read_only_fields = ["public_id", "status"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistSectionSerializer(serializers.ModelSerializer):
    applicability_rule_public_id = serializers.UUIDField(
        source="applicability_rule.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChecklistSection
        fields = [
            "public_id",
            "code",
            "title",
            "description",
            "display_order",
            "applicability_rule_public_id",
            "criticality",
        ]
        read_only_fields = ["public_id"]

    def validate_code(self, value):
        return _normalize_code_field(value)


class ChecklistQuestionSerializer(serializers.ModelSerializer):
    #: `5A-DEC-002` -- resolved governed option vocabulary (value + label).
    options = serializers.SerializerMethodField()
    applicability_rule_public_id = serializers.UUIDField(
        source="applicability_rule.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChecklistQuestion
        fields = [
            "public_id",
            "code",
            "question_text",
            "help_text",
            "display_order",
            "answer_type",
            "data_source_classification",
            "applicability_rule_public_id",
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
            "options",
        ]
        read_only_fields = ["public_id", "options"]

    def validate_code(self, value):
        return _normalize_code_field(value)

    def get_options(self, obj):
        """`5A-DEC-002` -- the resolved value/label vocabulary, server-derived.

        Exposed as its own field so a client never has to reach into
        `validation_rule` and never has to guess a label from a code: deriving
        labels in the frontend is exactly what 5A-DEC-002 forbids. Read-only,
        because the authored source of truth remains `validation_rule` and two
        writable representations of one vocabulary could disagree.

        Omitted (`None`) for a question with no closed vocabulary, so "no
        options" stays distinguishable from "an empty option list".
        """
        from .question_options import parse_options

        parsed = parse_options(obj.validation_rule or {})
        if parsed is None:
            return None
        return [{"value": option.value, "label": option.display_label} for option in parsed]


class VersionActionSerializer(serializers.Serializer):
    """Body for submit-review/approve/return/reject/activate/supersede/retire."""

    reason = serializers.CharField(required=False, allow_blank=True)


class CloneDefinitionSerializer(serializers.Serializer):
    source_version_public_id = serializers.UUIDField()
    target_scope_type = serializers.ChoiceField(choices=["platform_master", "tenant"])
    target_tenant_public_id = serializers.UUIDField(required=False, allow_null=True)
    new_code = serializers.CharField()
    new_title = serializers.CharField()
    clone_sections = serializers.BooleanField(default=True)
    clone_questions = serializers.BooleanField(default=True)
    clone_applicability_rules = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["target_scope_type"] == "tenant" and not attrs.get("target_tenant_public_id"):
            raise serializers.ValidationError(
                "target_tenant_public_id is required when target_scope_type is 'tenant'."
            )
        return attrs


# ---------------------------------------------------------------------------
# Milestone 4D-2 -- Execution and Response serializers
# ---------------------------------------------------------------------------


class _ChecklistVersionSummarySerializer(serializers.Serializer):
    public_id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    status = serializers.CharField()


class ChecklistExecutionSerializer(serializers.ModelSerializer):
    checklist_version = _ChecklistVersionSummarySerializer(read_only=True)
    formulation_version_public_id = serializers.UUIDField(
        source="formulation_version.public_id",
        read_only=True,
    )
    created_by_email = serializers.EmailField(
        source="created_by.email",
        read_only=True,
        default=None,
    )
    submitted_by_email = serializers.SerializerMethodField()
    returned_by_email = serializers.SerializerMethodField()
    approved_by_email = serializers.SerializerMethodField()
    rejected_by_email = serializers.SerializerMethodField()
    cancelled_by_email = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistExecution
        fields = [
            "public_id",
            "status",
            "checklist_version",
            "formulation_version_public_id",
            "created_by_email",
            "submitted_by_email",
            "submitted_at",
            "returned_by_email",
            "returned_at",
            "return_reason",
            "approved_by_email",
            "approved_at",
            "rejected_by_email",
            "rejected_at",
            "cancelled_by_email",
            "cancelled_at",
            "reviewer_conclusion_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_submitted_by_email(self, obj):
        return getattr(obj.submitted_by, "email", None)

    def get_returned_by_email(self, obj):
        return getattr(obj.returned_by, "email", None)

    def get_approved_by_email(self, obj):
        return getattr(obj.approved_by, "email", None)

    def get_rejected_by_email(self, obj):
        return getattr(obj.rejected_by, "email", None)

    def get_cancelled_by_email(self, obj):
        return getattr(obj.cancelled_by, "email", None)


class ChecklistExecutionCreateSerializer(serializers.Serializer):
    checklist_version_public_id = serializers.UUIDField()
    formulation_version_public_id = serializers.UUIDField()

    def validate(self, attrs):
        # Reject any unknown fields via strict mass-assignment guard.
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        return attrs


class CalculationOutcomeSummarySerializer(serializers.Serializer):
    """Read-only client projection of a governed ``CalculationOutcome``.

    A SYSTEM_CALCULATED response keeps ``raw_value`` null at all times
    (M4D3-MDL-006) and the writer is forbidden from touching
    ``system_derived_value`` (M4D3-SVC-006), so the outcome row is the only
    place a calculated result exists. Without this projection a client cannot
    render one at all.

    Deliberately an explicit field list rather than a ``ModelSerializer``: the
    outcome row also carries ``inputs``, ``input_provenance``, ``rounding_rule``,
    ``formula_version`` and ``source_assessment_snapshot_public_id``, which are
    regulated provenance and reproducibility evidence, not display data. Naming
    each exposed field means a future column is never published by accident.

    ``NOT_COMPARABLE`` is deliberately **not** a status: the governed
    ``CalculationStatus`` vocabulary is only
    ``data_required``/``calculating``/``complete``/``error``, and a
    not-comparable engine result persists as ``status=error`` with
    ``reason_code="NOT_COMPARABLE"`` (see ENGINE_STATUS_MAPPING). Clients must
    therefore read ``reason_code`` to distinguish it, and this serializer
    reports the stored vocabulary exactly rather than inventing a display state.
    """

    outcome_public_id = serializers.UUIDField(source="public_id", read_only=True)
    status = serializers.CharField(read_only=True)
    value = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    reason_code = serializers.SerializerMethodField()

    def get_value(self, obj):
        """The current value, or null.

        Only a ``complete`` outcome may carry a value — the translation layer
        enforces that at import time — so a non-success outcome renders null
        here because the stored row *is* null, not because this serializer
        blanks it. A previous complete value can never leak into a later
        data_required or error state.

        Rendered with the same plain-notation formatter the writer uses at the
        persistence boundary, so the API and the stored record never disagree on
        how a regulated number reads.
        """
        from .calculation_translation import format_decimal_plain

        return None if obj.value is None else format_decimal_plain(obj.value)

    def get_unit(self, obj):
        # ``unit`` is blank=True, never null; a placeholder holds "". Normalise
        # the empty case to null so a client is not handed a meaningless "".
        return obj.unit or None

    def get_reason_code(self, obj):
        # Closed governed vocabulary (ALLOWED_REASON_CODES), validated at import
        # time — a canonical code, never free text and never exception detail.
        return obj.reason_code or None


class ChecklistResponseSerializer(serializers.ModelSerializer):
    question_public_id = serializers.UUIDField(source="question.public_id", read_only=True)
    entered_by_email = serializers.SerializerMethodField()
    confirmed_by_email = serializers.SerializerMethodField()
    calculation = serializers.SerializerMethodField()
    #: M4D3-PST-009 / `5A-DEC-004` -- derived from persisted state only.
    applicability_outcome = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistResponse
        fields = [
            "public_id",
            "question_public_id",
            "data_source_type_snapshot",
            "raw_value",
            "is_not_applicable",
            "not_applicable_reason",
            "entered_by_email",
            "entered_at",
            "confirmed_by_email",
            "confirmed_at",
            "override_reason",
            "system_derived_value",
            #: `5A-DEC-001` -- read-only governed FDA-derived provenance.
            "source_provenance",
            "version",
            "calculation",
            "applicability_outcome",
        ]
        read_only_fields = fields

    def get_applicability_outcome(self, obj):
        """M4D3-PST-009 -- `applicable` / `not_applicable` / `review_required` /
        `no_rule`, derived from what is stored and nothing else.

        Never recomputed at read time (PST-008), so a submitted or approved
        execution keeps reporting the applicability it was actually assessed
        against even if the product or FDA data behind it later changes.
        """
        from .applicability_runtime import derive_applicability_outcome

        return derive_applicability_outcome(obj)

    def get_entered_by_email(self, obj):
        return getattr(obj.entered_by, "email", None)

    def get_confirmed_by_email(self, obj):
        return getattr(obj.confirmed_by, "email", None)

    def get_calculation(self, obj):
        """The current outcome for this response, or ``None``.

        ``None`` for every response that has no outcome row at all — a manual
        answer never has one, so the key is present and null rather than
        pretending a calculation exists.

        Uses ``.all()`` so a prefetched queryset is reused rather than re-queried
        per row (see ChecklistResponseListView). Exactly one outcome per
        response is a governed invariant, enforced by the writer, which raises
        PlaceholderMissing/PlaceholderAmbiguous otherwise; ordering by
        ``public_id`` matches how the writer and the input resolver select it, so
        the API can never disagree with them about which row is current.
        """
        outcomes = list(obj.calculation_outcomes.all())
        if not outcomes:
            return None
        current = min(outcomes, key=lambda row: str(row.public_id))
        return CalculationOutcomeSummarySerializer(current).data


class ChecklistResponseUpdateSerializer(serializers.Serializer):
    #: M4D3-VER-002 -- required, not additive. M4D3-VER-001 records this as a
    #: controlled breaking API contract change: the ordinary response PATCH did
    #: not previously accept it, and optimistic concurrency is mandatory rather
    #: than opt-in, so there is no value that skips the check.
    #:
    #: Deliberately a passthrough field rather than ``IntegerField``. An
    #: ``IntegerField`` coerces ``1.0``, ``"1"`` and ``"1.0"`` into the integer
    #: 1, which the governed ``validate_expected_version()`` of M4D3-TXN-003
    #: rejects -- so the transport layer would have applied a second, more
    #: permissive structural rule than the domain. The serializer enforces
    #: **presence** only; the submitted value reaches the governed validator
    #: exactly as the client sent it, and structural validity is decided there.
    expected_version = serializers.JSONField(required=False, allow_null=True)
    raw_value = serializers.JSONField(allow_null=True, required=False)
    is_not_applicable = serializers.BooleanField(required=False)
    not_applicable_reason = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        max_length=MAX_NOT_APPLICABLE_REASON_CHARS,
        required=False,
    )
    # `override_reason` is deliberately NOT a field here. It is server-controlled
    # on the ordinary update path (M4D3-SVC-006, and `_UPDATABLE_FIELDS` never
    # applied it), so accepting and silently discarding it let a client believe
    # it had recorded a governed reason when nothing was written. 4D-4 §AC.5
    # keeps both override columns off this path entirely: the dedicated override
    # action (`4D4-DEC-007`) is their only writer, and naming either field here
    # now fails as `unknown_field` rather than being ignored.

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        # Reject client-supplied version.
        if "version" in self.initial_data:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": "version is not client-writable."}
            )

        # M4D3-VER-004 -- an omitted expected_version is rejected with its own
        # governed code and no write. Declared ``required=False`` only so this
        # contract is reported instead of DRF's generic "This field is
        # required."; it is mandatory in every other sense. Silent overwrite of
        # a concurrently changed response is prohibited.
        #
        # This is a **presence** check only. A key that is present but holds a
        # structurally invalid value -- ``null``, ``1.0``, ``"1"``, ``0`` --
        # passes here untouched and is refused by the governed
        # ``validate_expected_version()`` in the service, so the two concerns
        # stay separated and only one structural rule exists.
        if "expected_version" not in attrs:
            raise serializers.ValidationError(
                {
                    "error_code": "expected_version_required",
                    "detail": "expected_version is required on a governed response update.",
                }
            )

        question = self.context.get("question")
        raw_value = attrs.get("raw_value")
        is_not_applicable = attrs.get("is_not_applicable")

        if question is not None and "raw_value" in attrs:
            from .response_validation import InvalidRawValueShape, validate_raw_value_shape

            try:
                validate_raw_value_shape(
                    question.answer_type,
                    raw_value,
                    question=question,
                    execution=self.context.get("execution"),
                    tenant=self.context.get("tenant"),
                )
            except InvalidRawValueShape as exc:
                raise serializers.ValidationError(
                    {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
                ) from exc

        if (
            question is not None
            and is_not_applicable
            and question.answer_type
            in {"calculated_value", "calculated_status", "approval_metadata"}
        ):
            raise serializers.ValidationError(
                {
                    "error_code": "invalid_raw_value_shape",
                    "detail": f"{question.answer_type} does not support is_not_applicable.",
                }
            )
        return attrs

    def validate_raw_value(self, value):
        if value is None:
            return value
        size = len(json.dumps(value).encode("utf-8"))
        if size > MAX_RAW_VALUE_BYTES:
            raise serializers.ValidationError(
                {"error_code": "payload_too_large", "detail": "raw_value exceeds byte limit."}
            )
        return value


class ChecklistResponseOverrideSerializer(serializers.Serializer):
    """Transport shape for the dedicated override action (`4D4-DEC-007`).

    Deliberately a separate serializer rather than a mode of the ordinary update
    serializer: the override path accepts a different field set, and §AC.5 keeps
    the two override columns off the ordinary PATCH entirely.
    """

    #: Same passthrough treatment as the ordinary update path -- presence is
    #: checked here, structural validity by the shared governed validator in the
    #: service, so `1.0` / `"1"` / `"1.0"` are not silently coerced to 1.
    expected_version = serializers.JSONField(required=False, allow_null=True)
    #: `allow_null=True` so a null value reaches the service and is refused there
    #: with the governed `override_clear_not_supported` code (§AC.4) rather than
    #: DRF's generic "may not be null" -- an attempted clear gets a governed
    #: answer, not a transport-layer one.
    raw_value = serializers.JSONField(required=False, allow_null=True)
    #: §12 L718 -- mandatory, and enforced in the *service* so a direct domain
    #: call is bound by it too. Blank and whitespace-only both pass the transport
    #: layer untouched and are refused there with one governed code.
    #:
    #: `trim_whitespace=False` is load-bearing: DRF trims by default, which would
    #: turn `"   "` into `""` and trip `allow_blank`, answering a governed
    #: requirement with a transport-layer message. Leaving the value intact keeps
    #: every form of "no reason" on the same path.
    override_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False,
        max_length=MAX_FREE_TEXT_CHARS,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        # §AC.5 -- the preserved original is server-owned. Naming it is an
        # attempt to author it, refused whatever value it carries.
        for server_owned in ("system_derived_value", "version"):
            if server_owned in self.initial_data:
                raise serializers.ValidationError(
                    {
                        "error_code": "unknown_field",
                        "detail": f"{server_owned} is not client-writable.",
                    }
                )
        if "expected_version" not in attrs:
            raise serializers.ValidationError(
                {
                    "error_code": "expected_version_required",
                    "detail": "expected_version is required on a governed override.",
                }
            )
        if "raw_value" not in attrs:
            raise serializers.ValidationError(
                {
                    "error_code": "override_value_required",
                    "detail": "raw_value is required on a governed override.",
                }
            )
        if attrs.get("override_reason") is None:
            raise serializers.ValidationError(
                {
                    "error_code": "override_reason_required",
                    "detail": "override_reason is required on a governed override.",
                }
            )

        question = self.context.get("question")
        raw_value = attrs.get("raw_value")
        if question is not None and raw_value is not None:
            from .response_validation import InvalidRawValueShape, validate_raw_value_shape

            try:
                validate_raw_value_shape(
                    question.answer_type,
                    raw_value,
                    question=question,
                    execution=self.context.get("execution"),
                    tenant=self.context.get("tenant"),
                )
            except InvalidRawValueShape as exc:
                raise serializers.ValidationError(
                    {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
                ) from exc
        return attrs

    def validate_raw_value(self, value):
        if value is None:
            return value
        size = len(json.dumps(value).encode("utf-8"))
        if size > MAX_RAW_VALUE_BYTES:
            raise serializers.ValidationError(
                {"error_code": "payload_too_large", "detail": "raw_value exceeds byte limit."}
            )
        return value


class ReviewerConclusionSerializer(serializers.Serializer):
    raw_value = serializers.JSONField()
    #: `4D4-DEC-013` (APPROVED 2026-08-12) closes the coercion divergence
    #: `MILESTONE_4D_4_DISCOVERY.md` §H recorded as OPEN.
    #:
    #: This was `IntegerField(min_value=1)`, which coerces `1.0`, `"1"` and
    #: `"1.0"` into the integer 1 -- so the transport layer applied a *more
    #: permissive* structural rule than the domain, and reviewer conclusion ran a
    #: third concurrency contract while the response-update and override paths
    #: shared one. Now a passthrough: presence is checked here, structural
    #: validity is decided by the governed `validate_expected_version()` in the
    #: service, exactly as on the other two governed write paths.
    expected_version = serializers.JSONField(required=False, allow_null=True)
    correction_reason = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
        max_length=MAX_REVIEWER_CONCLUSION_CHARS,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        # Presence only -- `4D4-DEC-013`. A key that is present but structurally
        # invalid (`null`, `1.0`, `"1"`, `0`) passes here untouched and is refused
        # by the governed validator in the service, so one structural rule exists
        # rather than two.
        if "expected_version" not in attrs:
            raise serializers.ValidationError(
                {
                    "error_code": "expected_version_required",
                    "detail": "expected_version is required on a governed reviewer conclusion.",
                }
            )
        raw_value = attrs.get("raw_value")
        if not isinstance(raw_value, dict):
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value must be an object.",
                }
            )
        if set(raw_value.keys()) != {"value"}:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value must contain only a 'value' key.",
                }
            )
        value_str = raw_value.get("value")
        if not isinstance(value_str, str):
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_invalid_payload",
                    "detail": "raw_value.value must be a string.",
                }
            )
        if not value_str.strip():
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_empty",
                    "detail": "Reviewer conclusion must not be empty.",
                }
            )
        if len(value_str) > MAX_REVIEWER_CONCLUSION_CHARS:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_too_long",
                    "detail": (
                        f"Reviewer conclusion exceeds {MAX_REVIEWER_CONCLUSION_CHARS} characters."
                    ),
                }
            )
        payload_size = len(json.dumps(raw_value).encode("utf-8"))
        if payload_size > MAX_RAW_VALUE_BYTES:
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_payload_too_large",
                    "detail": "Payload exceeds byte limit.",
                }
            )
        return attrs


class ReturnSerializer(serializers.Serializer):
    return_reason = serializers.CharField(max_length=MAX_RETURN_REASON_CHARS)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        if not attrs.get("return_reason", "").strip():
            raise serializers.ValidationError(
                {"error_code": "missing_return_reason", "detail": "return_reason is required."}
            )
        return attrs


class ApproveSerializer(serializers.Serializer):
    reviewer_conclusion_note = serializers.CharField(max_length=MAX_REVIEWER_CONCLUSION_CHARS)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        if not attrs.get("reviewer_conclusion_note", "").strip():
            raise serializers.ValidationError(
                {
                    "error_code": "reviewer_conclusion_required",
                    "detail": "reviewer_conclusion_note is required.",
                }
            )
        return attrs


class EmptyActionSerializer(serializers.Serializer):
    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"error_code": "unknown_field", "detail": f"Unknown fields: {unknown}"}
            )
        return attrs
