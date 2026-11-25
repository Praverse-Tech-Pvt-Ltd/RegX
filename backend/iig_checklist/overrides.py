"""Milestone 4D-4 -- governed response overrides (deviations).

Specification: ``MILESTONE_4D_DISCOVERY.md`` §12 (deviations and overrides) and
``MILESTONE_4D_4_DISCOVERY.md`` §AC, which records the approved contract
(``4D4-DEC-004`` history code, ``4D4-DEC-010`` overridability by classification,
``4D4-DEC-011`` override authority), together with the already-approved
``4D4-DEC-002`` (shared ``validate_expected_version()``), ``4D4-DEC-003``
(editable states only) and ``4D4-DEC-007`` (dedicated action endpoint).

What an override *is*, and what it must never become
----------------------------------------------------

An override is a **governed exception to a system- or default-derived value**:
a reviewer asserts, with a recorded reason, that the value the system produced
is not the value that belongs in the regulatory record. §AC.1 is deliberate
about the boundary. An override must never become

* a generic edit shortcut -- ``USER_REQUIRED`` answers are edited through the
  ordinary governed response-update path and are not an override case at all;
* a way to hand-edit a calculated number -- disagreeing with a
  ``SYSTEM_CALCULATED`` result is resolved by correcting the *input* and letting
  the cascade recompute, never by overwriting the result (§12 L732);
* a way to rewrite an evidence-derived fact, which must be corrected through its
  own evidence/source workflow;
* a way to bypass reviewer conclusion, which has its own governed
  amendment workflow.

Every non-overridable classification therefore keeps a correction path. Nothing
becomes uncorrectable -- only uncorrectable *by override*.

No new storage
--------------

§AC.5 approves no new field, so this module implements the whole contract on
state the model already carries: ``raw_value`` holds the authoritative value,
``system_derived_value`` preserves the original, ``override_reason`` records why,
``version`` increments. No migration is implied.

**The active-override marker is a non-empty ``override_reason``, not a non-null
``system_derived_value``.** That distinction matters: an ``FDA_DERIVED_DEFAULT``
response whose default was never populated has ``raw_value = None``, so the
first override legitimately preserves ``None`` into ``system_derived_value``.
Keying "is an override already active?" off that column would then read the
second override as a first one and overwrite the preserved original with the
*previous override* -- exactly the corruption §AC.5 forbids. ``override_reason``
is only ever written here, so its emptiness is an honest marker.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "OverrideClearNotSupported",
    "OverrideError",
    "OverrideInvalidExpectedVersion",
    "OverrideInvalidPayload",
    "OverrideInvalidState",
    "OverrideNotOverridable",
    "OverridePermissionDenied",
    "OverrideReasonRequired",
    "OverrideResult",
    "OverrideStaleVersion",
    "override_checklist_response",
]


class OverrideError(Exception):
    """Base class for governed override rejections, raised before commit."""


class OverridePermissionDenied(OverrideError):
    """The actor lacks ``PERM_OVERRIDE_EXECUTION`` (``4D4-DEC-011``)."""


class OverrideInvalidState(OverrideError):
    """The execution is not in an editable state (``4D4-DEC-003``)."""


class OverrideNotOverridable(OverrideError):
    """The response's classification may not be overridden (``4D4-DEC-010``)."""


class OverrideReasonRequired(OverrideError):
    """§12 L718 -- ``override_reason`` is mandatory and may not be blank."""


class OverrideClearNotSupported(OverrideError):
    """§AC.4 -- clearing an override is not a governed transition."""


class OverrideInvalidExpectedVersion(OverrideError):
    """``expected_version`` is structurally invalid (shared validator)."""


class OverrideStaleVersion(OverrideError):
    """``expected_version`` did not match the locked row."""


class OverrideInvalidPayload(OverrideError):
    """The submitted override value is malformed for this answer type."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("invalid override payload")


@dataclass(frozen=True, slots=True)
class OverrideResult:
    """One governed override and the cascade it drove."""

    response: object
    cascade: object = None
    #: True when this call created the override, False when it replaced an
    #: active one. Derived from the marker below, and mirrored into the audit
    #: payload so the trail states it rather than leaving it to be inferred.
    created: bool = True


def _override_is_active(response) -> bool:
    """Whether an override is already recorded on this response.

    See the module docstring: ``override_reason`` is the marker, deliberately
    not ``system_derived_value``.
    """
    return bool((response.override_reason or "").strip())


def override_checklist_response(
    *,
    tenant,
    execution_public_id,
    response_public_id,
    actor,
    payload,
) -> OverrideResult:
    """Apply or update a governed override on one response.

    Three phases, matching every other governed checklist service:

    - Phase A -- non-mutating validation. No lock, no write. Tenant-scoped
      lookup **first**, so a cross-tenant id is a 404 through ``visible_to()``
      and never a 403 that would confirm the record exists.
    - Phase B -- one ``transaction.atomic()`` holding the response write, the
      history row and every dependent recalculation.
    - Phase C -- audit inside the Phase B transaction (QA-09, owner decision
      2026-11-23), so a rejected or rolled-back attempt never announces success,
      and no override commits without its audit record.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction as db_transaction
    from django.utils import timezone
    from rest_framework.exceptions import NotFound

    from .audit import IigChecklistEvent, emit
    from .calculation_execution import InvalidExpectedVersion, validate_expected_version
    from .cascade import recalculate_dependents
    from .enums import DataSourceClassification
    from .governed_vocabularies import HISTORY_REASON_ANSWER_OVERRIDDEN
    from .models import ChecklistExecution, ChecklistResponse, ChecklistResponseHistory
    from .permissions import PERM_OVERRIDE_EXECUTION, has_iig_checklist_permission
    from .serializers import ChecklistResponseOverrideSerializer
    from .services import EDITABLE_EXECUTION_STATUSES

    # -- Phase A: non-mutating validation ---------------------------------

    try:
        execution = ChecklistExecution.objects.visible_to(tenant).get(public_id=execution_public_id)
    except ChecklistExecution.DoesNotExist:
        raise NotFound() from None

    if not has_iig_checklist_permission(actor, tenant, PERM_OVERRIDE_EXECUTION):
        raise OverridePermissionDenied()

    if execution.status not in EDITABLE_EXECUTION_STATUSES:
        raise OverrideInvalidState()

    try:
        response = ChecklistResponse.objects.select_related("question").get(
            public_id=response_public_id,
            execution=execution,
        )
    except ChecklistResponse.DoesNotExist:
        raise NotFound() from None

    # `4D4-DEC-010`. Read from the snapshot rather than the live question so a
    # later change to the question's classification cannot retroactively make an
    # already-answered response overridable.
    if response.data_source_type_snapshot != DataSourceClassification.FDA_DERIVED_DEFAULT:
        raise OverrideNotOverridable(response.data_source_type_snapshot)

    serializer = ChecklistResponseOverrideSerializer(
        data=payload,
        context={"question": response.question, "execution": execution, "tenant": tenant},
    )
    if not serializer.is_valid():
        raise OverrideInvalidPayload(serializer.errors)
    data = serializer.validated_data

    # §AC.4 -- clearing is not a governed transition, so a null value is refused
    # with its own code rather than being read as "remove the override". The
    # serializer already rejects a blank reason; this is the value-side half.
    if data.get("raw_value", None) is None:
        raise OverrideClearNotSupported()

    reason = (data.get("override_reason") or "").strip()
    if not reason:
        raise OverrideReasonRequired()

    # `4D4-DEC-002` -- the same structural validator every other governed write
    # uses, applied to the value the client actually submitted. The serializer
    # deliberately does not coerce, so `1.0`, `"1"` and `"1.0"` arrive intact and
    # are refused here rather than silently becoming version 1.
    try:
        expected_version = validate_expected_version(data["expected_version"])
    except InvalidExpectedVersion as exc:
        raise OverrideInvalidExpectedVersion() from exc

    # -- Phase B: every governed write, one transaction --------------------
    with db_transaction.atomic():
        locked_execution = ChecklistExecution.objects.select_for_update().get(pk=execution.pk)
        # Re-read under the lock: the status that governs the write must be
        # committed state, not what the Phase A scan happened to see.
        if locked_execution.status not in EDITABLE_EXECUTION_STATUSES:
            raise OverrideInvalidState()

        locked_response = (
            ChecklistResponse.objects.select_for_update()
            .select_related("question")
            .get(pk=response.pk)
        )

        if locked_response.version != expected_version:
            raise OverrideStaleVersion()

        prior_raw_value = locked_response.raw_value
        prior_is_not_applicable = locked_response.is_not_applicable
        prior_not_applicable_reason = locked_response.not_applicable_reason
        prior_entered_by = locked_response.entered_by
        prior_entered_at = locked_response.entered_at
        prior_version = locked_response.version
        prior_override_reason = locked_response.override_reason

        created = not _override_is_active(locked_response)
        if created:
            # First override: the value being displaced *is* the original
            # system/default-derived value, so it is what gets preserved.
            locked_response.system_derived_value = prior_raw_value
        # Updating an active override deliberately leaves system_derived_value
        # untouched -- §AC.5 requires it to remain the ORIGINAL pre-override
        # value, never the override it is replacing.

        locked_response.raw_value = data["raw_value"]
        locked_response.override_reason = reason
        locked_response.entered_by = actor
        locked_response.entered_at = timezone.now()
        locked_response.version = expected_version + 1

        try:
            locked_response.full_clean()
            locked_response.save()
        except ValidationError as exc:
            raise OverrideInvalidPayload(
                {"error_code": "invalid_raw_value_shape", "detail": str(exc)}
            ) from exc

        # `4D4-DEC-004` -- one governed code for both apply and update. The
        # prior/new columns plus the version pair are what make the two
        # distinguishable on replay, so no second code is minted.
        ChecklistResponseHistory(
            response=locked_response,
            prior_raw_value=prior_raw_value,
            new_raw_value=locked_response.raw_value,
            prior_is_not_applicable=prior_is_not_applicable,
            new_is_not_applicable=locked_response.is_not_applicable,
            prior_not_applicable_reason=prior_not_applicable_reason,
            new_not_applicable_reason=locked_response.not_applicable_reason,
            prior_entered_by=prior_entered_by,
            prior_entered_at=prior_entered_at,
            prior_version=prior_version,
            new_version=locked_response.version,
            correction_reason=HISTORY_REASON_ANSWER_OVERRIDDEN,
            amended_by=actor,
            source_classification_snapshot=locked_response.data_source_type_snapshot,
        ).save()

        # An overridden default can feed calculations, so the cascade is entered
        # for exactly the same reason an ordinary update enters it: it decides
        # for itself whether this question triggers anything, and it runs inside
        # this transaction so a recalculation failure rolls the override back.
        cascade_result = recalculate_dependents(
            tenant=tenant,
            execution=locked_execution,
            changed_response=locked_response,
            actor=actor,
            expected_version=locked_response.version,
        )

        # -- Phase C: audit, inside this transaction (QA-09, owner decision 2026-11-23) --
        def _audit():
            emit(
                event_type=IigChecklistEvent.ANSWER_OVERRIDDEN,
                resource_id=str(locked_response.public_id),
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", ""),
                tenant_id=getattr(tenant, "id", None),
                payload={
                    # §12 L727 -- old/new value, actor and reason, in public
                    # identifiers only. No database primary keys.
                    "execution_public_id": str(locked_execution.public_id),
                    "response_public_id": str(locked_response.public_id),
                    "question_public_id": str(locked_response.question.public_id),
                    "question_code": locked_response.question.code,
                    "data_source_type_snapshot": locked_response.data_source_type_snapshot,
                    "prior_response_version": prior_version,
                    "new_response_version": locked_response.version,
                    "actor_public_id": str(getattr(actor, "public_id", "")) or None,
                    "override_reason": reason,
                    "prior_override_reason": prior_override_reason or None,
                    "prior_value": prior_raw_value,
                    "new_value": locked_response.raw_value,
                    "system_derived_value": locked_response.system_derived_value,
                    "override_created": created,
                    "recalculated_count": cascade_result.recalculated_count,
                },
            )

        _audit()
    return OverrideResult(response=locked_response, cascade=cascade_result, created=created)
