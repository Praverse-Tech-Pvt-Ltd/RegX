"""Governed ``AssessmentSnapshot`` creation -- the one callable domain service.

Before this module, ``AssessmentSnapshot`` rows were created only inside
``iid_assessment.views.SnapshotView.post``, bound to a DRF request, serializer,
``request.user`` and HTTP response. Nothing outside the API could create a
governed snapshot, which is why Milestone 4D-3's calculation execution had to
accept a caller-supplied snapshot object and stay internal-only.

``create_assessment_snapshot()`` is now the single authoritative path. The view
is a thin adapter over it and no second creation path exists.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-SNO-006      a new immutable snapshot for every governed event; never
                      reused, deduplicated or updated
  - M4D3-SNO-007      the created object is carried in memory, not re-queried
  - M4D3-SNO-008      no re-query by tenant, component or release; ``.first()``
                      and creation-order selection are prohibited
  - M4D3-SNO-010      tenant, subject component and release are checked before use
  - M4D3-SNO-011      no client-supplied snapshot UUID ever selects a snapshot
  - M4D3-SNO-012      the caller owns the transaction; this service never commits
                      independently
  - M4D3-SRC-001/003  the active release is resolved server-side as the single
                      ``fda_iid`` release with ``status = "active"``
  - M4D3-SRC-004      every ``run_preview()`` argument is derived from the
                      governed formulation objects
  - M4D3-SRC-009      candidate selection stays in the existing matching layer
  - M4D3-SRC-013      nothing here writes to ``fda_data``
  - M4D3-RTE-002/003  a blank controlled term is missing data, never a resolved
                      value

**The governed source of truth is the formulation, not the caller.** Route and
dosage form come from ``FormulationVersion.product``; the proposed quantity and
its unit come from the ``FormulationComponent``; the total dosage-unit weight
comes from the ``FormulationVersion``; substance identity comes from the
component's resolved ingredient. A caller cannot substitute its own potency, MDE
or quantity, so a snapshot always describes the formulation it names.

``maximum_dosage_units_per_day`` is the one value a caller may supply, because
the governed worst-case resolver of M4D3-MDU-001..024 lives in ``iig_checklist``
and the import contract ``iig-checklist-content-is-not-imported-by-governed-domains``
forbids importing it here. When it is not supplied the service falls back to
``FormulationVersion.maximum_dosage_units_per_day``, which is one of that
resolver's own two governed sources -- never to a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

# ---------------------------------------------------------------------------
# Governed rejections
#
# Every one is raised before any write, so the caller's transaction rolls back
# untouched. None carries a database id, a SQL fragment, a foreign tenant's
# identifiers or a raw driver exception.
# ---------------------------------------------------------------------------


class AssessmentSnapshotError(Exception):
    """Base class for governed snapshot-creation rejections."""


class FormulationVersionNotInTenant(AssessmentSnapshotError):
    """The formulation version does not belong to the supplied tenant."""


class ComponentNotInFormulationVersion(AssessmentSnapshotError):
    """The component does not belong to the supplied formulation version."""


class ActiveReleaseUnavailable(AssessmentSnapshotError):
    """No single active FDA IID release exists (M4D3-SRC-001/002)."""


class ReleaseNotEligible(AssessmentSnapshotError):
    """The supplied release is not an ``fda_iid`` release in an eligible state."""


#: Exactly the statuses ``find_iid_candidates()`` will match against
#: (``release__status__in=[APPROVED, ACTIVE]``). Accepting a status the governed
#: matcher rejects would let a caller create a snapshot that can never freeze a
#: precedent -- an empty regulated record that looks like an assessment.
#:
#: A **superseded** release is therefore *not* eligible. Reproducibility does not
#: come from re-deriving against an old release: it comes from the snapshot that
#: was already frozen, which keeps its values forever regardless of later FDA
#: refreshes. M4D3-SRC-009 forbids 4D-3 implementing its own selection, so the
#: matcher's own status filter is the authority here rather than a second rule.
ELIGIBLE_RELEASE_STATUSES: frozenset[str] = frozenset({"active", "approved"})


@dataclass(frozen=True, slots=True)
class AssessmentSnapshotCreationResult:
    """Immutable summary of one governed snapshot creation.

    ``snapshot`` is the exact in-memory object M4D3-SNO-007 requires the caller
    to retain for the rest of its transaction; it is deliberately *not* a
    serialization surface, and every identifier a caller should record is
    already present as a public UUID string beside it.
    """

    snapshot: object
    snapshot_public_id: str
    tenant_public_scope: str
    formulation_version_public_id: str
    formulation_component_public_id: str
    iid_release_public_id: str
    iid_release_status: str
    iid_precedent_record_public_id: str | None
    iid_substance_mapping_public_id: str | None
    match_status: str
    decision_status: str
    escalation_required: bool
    route_resolved: bool
    dosage_form_resolved: bool
    potency_amount: Decimal | None
    potency_unit: str
    mde: Decimal | None
    mde_unit: str

    @property
    def has_iid_reference(self) -> bool:
        """True when the snapshot froze a usable IID precedent."""
        return self.iid_precedent_record_public_id is not None


# ---------------------------------------------------------------------------
# Release resolution (M4D3-SRC-001/003)
# ---------------------------------------------------------------------------


def resolve_active_iid_release():
    """The single active FDA IID release, resolved server-side.

    ``unique_active_release_per_dataset_type`` is a partial unique constraint on
    ``(dataset_type)`` where ``status = 'active'``, so at most one row can
    match. Every match is still collected and anything other than exactly one
    fails closed -- there is no ``.first()``, no ordering and no "latest"
    selection, so a schema regression could never silently pick a row.
    """
    from fda_data.models import FDADatasetType, FDADataSourceRelease, FDAReleaseStatus

    releases = list(
        FDADataSourceRelease.objects.filter(
            dataset_type=FDADatasetType.FDA_IID, status=FDAReleaseStatus.ACTIVE
        )
    )
    if len(releases) != 1:
        raise ActiveReleaseUnavailable()
    return releases[0]


def _validate_release(release):
    from fda_data.models import FDADatasetType

    if release.dataset_type != FDADatasetType.FDA_IID:
        raise ReleaseNotEligible()
    if release.status not in ELIGIBLE_RELEASE_STATUSES:
        raise ReleaseNotEligible()
    return release


# ---------------------------------------------------------------------------
# Governed argument derivation (M4D3-SRC-004)
# ---------------------------------------------------------------------------


def _controlled_term(raw) -> tuple[str, bool]:
    """M4D3-RTE-002/003 -- a blank controlled term is missing data.

    Returns the stripped code and whether it can be treated as resolved. A
    blank code is still handed to ``run_preview()`` because the argument is
    required, but it matches no ``ControlledRoute``/``ControlledDosageForm`` row,
    so it can never be *treated* as a resolved value.
    """
    code = (raw or "").strip()
    return code, bool(code)


def _preview_arguments(formulation_version, component, release, maximum_dosage_units_per_day):
    """Every ``run_preview()`` argument, derived from governed rows only."""
    product = formulation_version.product
    route_code, route_resolved = _controlled_term(product.route)
    dosage_form_code, dosage_form_resolved = _controlled_term(product.dosage_form)

    arguments = {
        "ingredient_public_id": component.resolved_ingredient_public_id,
        "substance_name": (component.ingredient_name or "").strip(),
        "substance_unii": (component.resolved_unii or "").strip(),
        "route_code": route_code,
        "dosage_form_code": dosage_form_code,
        "active_release_public_id": release.public_id,
        "proposed_quantity_per_unit": component.quantity_per_dosage_unit,
        "proposed_quantity_unit": component.quantity_unit,
        "total_dosage_unit_weight": formulation_version.total_dosage_unit_weight,
        "total_dosage_unit_weight_unit": formulation_version.total_dosage_unit_weight_unit,
        "maximum_dosage_units_per_day": (
            formulation_version.maximum_dosage_units_per_day
            if maximum_dosage_units_per_day is None
            else maximum_dosage_units_per_day
        ),
    }
    # A component whose ingredient identity is already governed does not need
    # the free-text synonym path at all (M4D3-SRC-004); leaving both populated
    # would let a name silently compete with a resolved identity.
    if arguments["ingredient_public_id"] is not None:
        arguments["substance_name"] = ""
        arguments["substance_unii"] = ""
    return MappingProxyType(arguments), route_resolved, dosage_form_resolved


# ---------------------------------------------------------------------------
# The governed service
# ---------------------------------------------------------------------------


def create_assessment_snapshot(
    *,
    tenant,
    formulation_version,
    formulation_component,
    actor,
    selected_release=None,
    selected_precedent_record_public_id=None,
    maximum_dosage_units_per_day=None,
) -> AssessmentSnapshotCreationResult:
    """Create exactly one immutable ``AssessmentSnapshot`` and return it.

    The caller owns the transaction (M4D3-SNO-012): this service opens none of
    its own, commits nothing independently, and schedules its audit through the
    caller's ``on_commit``, so any later failure discards the snapshot with the
    rest of the operation.

    ``selected_release`` is resolved server-side from M4D3-SRC-001 when omitted.
    A server-side caller that has already resolved an exact release -- a
    reproducibility check pinned to a superseded release, for instance -- may
    pass that exact object. **No client-supplied identifier ever reaches this
    parameter**: the API adapter resolves the active release itself
    (M4D3-SRC-003, M4D3-SNO-011).

    Every call creates a new row. There is no reuse, no deduplication, no
    ``.first()``, no "latest" lookup and no update path (M4D3-SNO-006/008).
    """
    from django.db import transaction as db_transaction

    from .assess import run_preview
    from .audit_events import IidAssessmentEvent, emit
    from .models import AssessmentSnapshot

    # -- Ownership, before anything else ---------------------------------
    if formulation_version.product.tenant_id != getattr(tenant, "id", None):
        raise FormulationVersionNotInTenant()
    if formulation_component.formulation_version_id != formulation_version.pk:
        raise ComponentNotInFormulationVersion()

    release = (
        resolve_active_iid_release()
        if selected_release is None
        else _validate_release(selected_release)
    )

    arguments, route_resolved, dosage_form_resolved = _preview_arguments(
        formulation_version, formulation_component, release, maximum_dosage_units_per_day
    )

    # M4D3-SRC-009 -- candidate matching and selection stay in the existing
    # governed layer; this service implements none of its own.
    preview = run_preview(
        **arguments,
        selected_precedent_record_public_id=selected_precedent_record_public_id,
    )
    selected = preview.selected_record or {}

    snapshot = AssessmentSnapshot(
        tenant=tenant,
        formulation_component_public_id=formulation_component.public_id,
        formulation_version_public_id=formulation_version.public_id,
        iid_release_public_id=release.public_id,
        iid_precedent_record_public_id=selected.get("precedent_record_public_id"),
        iid_substance_mapping_public_id=preview.substance_mapping_public_id,
        iid_ingredient_name=selected.get("ingredient_name", "") or "",
        iid_route=selected.get("route", "") or "",
        iid_dosage_form=selected.get("dosage_form", "") or "",
        iid_potency_amount=selected.get("potency_amount"),
        iid_potency_unit=selected.get("potency_unit", "") or "",
        iid_mde=selected.get("maximum_daily_exposure"),
        iid_mde_unit=selected.get("mde_unit", "") or "",
        proposed_quantity_per_unit=arguments["proposed_quantity_per_unit"],
        proposed_quantity_unit=arguments["proposed_quantity_unit"],
        calculation_results=preview.calculations,
        match_status=preview.match_status,
        decision_status=preview.decision_status,
        decision_note=preview.decision_note,
        created_by=actor,
    )
    snapshot.full_clean()
    snapshot.save()

    payload = {
        "snapshot_public_id": str(snapshot.public_id),
        "formulation_version_public_id": str(formulation_version.public_id),
        "formulation_component_public_id": str(formulation_component.public_id),
        "iid_release_public_id": str(release.public_id),
        "iid_release_status": release.status,
        "iid_precedent_record_public_id": (
            str(selected["precedent_record_public_id"])
            if selected.get("precedent_record_public_id")
            else None
        ),
        "match_status": preview.match_status,
        "decision_status": preview.decision_status,
    }
    db_transaction.on_commit(
        lambda: emit(
            event_type=IidAssessmentEvent.SNAPSHOT_CREATED,
            resource_id=str(snapshot.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload=payload,
        )
    )

    return AssessmentSnapshotCreationResult(
        snapshot=snapshot,
        snapshot_public_id=str(snapshot.public_id),
        tenant_public_scope=str(getattr(tenant, "slug", "") or ""),
        formulation_version_public_id=str(formulation_version.public_id),
        formulation_component_public_id=str(formulation_component.public_id),
        iid_release_public_id=str(release.public_id),
        iid_release_status=release.status,
        iid_precedent_record_public_id=payload["iid_precedent_record_public_id"],
        iid_substance_mapping_public_id=(
            str(preview.substance_mapping_public_id)
            if preview.substance_mapping_public_id
            else None
        ),
        match_status=preview.match_status,
        decision_status=preview.decision_status,
        escalation_required=preview.escalation_required,
        route_resolved=route_resolved,
        dosage_form_resolved=dosage_form_resolved,
        potency_amount=snapshot.iid_potency_amount,
        potency_unit=snapshot.iid_potency_unit,
        mde=snapshot.iid_mde,
        mde_unit=snapshot.iid_mde_unit,
    )


__all__ = [
    "ELIGIBLE_RELEASE_STATUSES",
    "ActiveReleaseUnavailable",
    "AssessmentSnapshotCreationResult",
    "AssessmentSnapshotError",
    "ComponentNotInFormulationVersion",
    "FormulationVersionNotInTenant",
    "ReleaseNotEligible",
    "create_assessment_snapshot",
    "resolve_active_iid_release",
]
