"""
Orchestration service tying together matching, unit conversion,
calculation, and decision -- the sequence an API view calls.

Never selects the "most favourable" candidate automatically: a caller
must supply selected_precedent_record_public_id once matching returns
MULTIPLE_EXACT_MATCHES, or the preview stops at REVIEW_REQUIRED.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal

from fda_data.models import ControlledDosageForm, ControlledRoute

from . import unit_conversion
from .calculations import (
    calculate_daily_exposure,
    calculate_difference_from_mde,
    calculate_difference_from_potency,
    calculate_percentage_of_mde,
    calculate_percentage_of_potency,
    calculate_percentage_w_w,
)
from .decisions import decide
from .matching import MatchResult, MatchStatus, find_iid_candidates


@dataclass
class AssessmentPreview:
    match_status: str
    candidates: list
    selected_record: dict | None
    calculations: dict
    decision_status: str
    decision_note: str
    escalation_required: bool
    substance_mapping_public_id: str | None = None
    substance_resolution_status: str | None = None


def run_preview(
    *,
    ingredient_public_id=None,
    route_code: str,
    dosage_form_code: str,
    active_release_public_id,
    proposed_quantity_per_unit,
    proposed_quantity_unit: str,
    total_dosage_unit_weight,
    total_dosage_unit_weight_unit: str,
    maximum_dosage_units_per_day=None,
    density_g_per_ml=None,
    selected_precedent_record_public_id=None,
    substance_name: str = "",
    substance_unii: str = "",
    substance_cas: str = "",
    proposed_quantity_expression=None,
) -> AssessmentPreview:
    route = ControlledRoute.objects.filter(code=route_code, lifecycle="active").first()
    dosage_form = ControlledDosageForm.objects.filter(
        code=dosage_form_code, lifecycle="active"
    ).first()
    from fda_data.models import FDADataSourceRelease

    release = FDADataSourceRelease.objects.filter(public_id=active_release_public_id).first()

    resolved_ingredient_public_id = (
        str(ingredient_public_id) if ingredient_public_id is not None else None
    )

    # Substance/UNII synonym governance: when the caller supplies a raw
    # substance identity instead of an already-resolved ingredient, the
    # ingredient identity is confirmed *only* by an exact approved
    # SubstanceSynonymMapping (or exact canonical IIDIngredient). A
    # proposed/rejected/returned/ambiguous synonym can never silently
    # become the confirmed identity -- it fails closed to REVIEW_REQUIRED
    # or INGREDIENT_AMBIGUOUS. String equality alone never overrides an
    # unresolved identity state.
    selected_substance_mapping_public_id = None
    substance_resolution = None
    if resolved_ingredient_public_id is None and (
        substance_name or substance_unii or substance_cas
    ):
        from fda_data.substance_matching import (
            SubstanceMatchStatus,
            resolve_substance_identity,
        )

        substance_resolution = resolve_substance_identity(
            normalized_name=substance_name,
            unii=substance_unii,
            cas_number=substance_cas,
        )
        if substance_resolution.status == SubstanceMatchStatus.EXACT_MATCH:
            confirmed = substance_resolution.candidates[0]
            resolved_ingredient_public_id = confirmed.ingredient_public_id
            selected_substance_mapping_public_id = confirmed.mapping_public_id

    match = find_iid_candidates(
        ingredient_public_id=resolved_ingredient_public_id,
        controlled_route_id=route.id if route else None,
        controlled_dosage_form_id=dosage_form.id if dosage_form else None,
        active_release_id=release.id if release else None,
    )

    # Governance override: a substance identity that was attempted but not
    # confirmed as an exact approved match is escalated to REVIEW_REQUIRED
    # (pending or multiple conflicting approved mappings) rather than being
    # reported as mere ambiguous free-text input. A rejected identity stays
    # INGREDIENT_AMBIGUOUS. Either way the IID lookup ran with a null
    # ingredient, so there are no candidates and no calculation happens.
    if substance_resolution is not None:
        from fda_data.substance_matching import SubstanceMatchStatus

        if substance_resolution.status in (
            SubstanceMatchStatus.MULTIPLE_CANDIDATES,
            SubstanceMatchStatus.REVIEW_REQUIRED,
        ):
            match = MatchResult(
                status=MatchStatus.REVIEW_REQUIRED,
                candidates=[],
                reason_code=substance_resolution.reason_code,
            )
        elif substance_resolution.status == SubstanceMatchStatus.INGREDIENT_AMBIGUOUS:
            match = MatchResult(
                status=MatchStatus.INGREDIENT_AMBIGUOUS,
                candidates=[],
                reason_code=substance_resolution.reason_code,
            )

    candidates_data = [asdict(c) for c in match.candidates]

    selected = None
    if selected_precedent_record_public_id:
        selected = next(
            (
                c
                for c in match.candidates
                if c.precedent_record_public_id == str(selected_precedent_record_public_id)
            ),
            None,
        )
    elif len(match.candidates) == 1:
        selected = match.candidates[0]

    calculations: dict = {}
    unit_conversion_ok = True
    density_or_basis_required = False
    converted_proposed_quantity = None
    converted_daily_exposure = None
    mde_available = False

    cannot_compare_reason = None
    if selected is not None:
        # One comparison path (controlled units, increment 3): the potency is
        # compared only through the unit's meaning, same family and same basis.
        # Without a stated meaning a formulation amount is per dosage unit, as
        # before. With one (increment 4), it is read with that meaning, so a
        # per-volume or percentage amount can meet an IID limit of the same
        # family and basis -- and nothing else.
        from fda_data.models import IIDPrecedentRecord

        from .comparison import (
            active_unit_list_release_public_id,
            compare,
            conversion_key,
            per_dose_unit_quantity,
            stated_quantity,
        )

        def unit_key(unit):
            # "mg", "g", "mcg", "ml" -> the converter's names, exactly as the
            # comparison reads them; anything else is passed on unchanged and
            # the converter refuses it as before.
            return conversion_key(unit) or unit

        record = IIDPrecedentRecord.objects.select_related(
            "release", "potency_expression__numerator_unit", "potency_expression__denominator_unit"
        ).get(public_id=selected.precedent_record_public_id)
        proposed = (
            stated_quantity(proposed_quantity_per_unit, proposed_quantity_expression)
            if proposed_quantity_expression is not None
            else per_dose_unit_quantity(proposed_quantity_per_unit, proposed_quantity_unit)
        )
        per_dose_amount = proposed.basis == "per_dose_unit"
        # The unit the per-dose calculations convert from: with a stated meaning,
        # that meaning's own unit key (e.g. "milligram" for "mg"); otherwise the
        # unit as entered, as before.
        calc_unit = (
            proposed.unit
            if proposed_quantity_expression is not None and proposed.unit
            else unit_key(proposed_quantity_unit)
        )
        comparison = compare(
            proposed,
            record,
            unit_list_release_public_id=active_unit_list_release_public_id(),
        )
        calculations["potency_comparison"] = comparison.as_dict()
        calculations["unit_conversion"] = asdict(
            unit_conversion.ConversionResult(
                ok=comparison.comparable,
                original_value=proposed_quantity_per_unit,
                original_unit=proposed_quantity_unit,
                converted_value=Decimal(comparison.proposed_value)
                if comparison.comparable
                else None,
                converted_unit=selected.potency_unit if comparison.comparable else None,
                reason_code=comparison.reason_code,
            )
        )
        if comparison.comparable:
            converted_proposed_quantity = Decimal(comparison.proposed_value)
        else:
            unit_conversion_ok = False
            cannot_compare_reason = comparison.reason_code

        if not per_dose_amount:
            # % w/w and daily exposure read the amount as per dosage unit. An
            # amount per stated volume or a percentage is not that, so both are
            # refused with a reason rather than computed on the wrong basis.
            calculations["percentage_w_w"] = asdict(
                _not_per_dose_unit("percentage_w_w", proposed_quantity_per_unit)
            )
            calculations["daily_exposure"] = asdict(
                _not_per_dose_unit("daily_exposure", proposed_quantity_per_unit)
            )
            pct_ww = daily_exposure_result = None
        else:
            pct_ww = calculate_percentage_w_w(
                quantity_per_unit_grams=(
                    unit_conversion.convert(
                        proposed_quantity_per_unit, calc_unit, "gram"
                    ).converted_value
                ),
                total_dosage_unit_weight_grams=(
                    unit_conversion.convert(
                        total_dosage_unit_weight, unit_key(total_dosage_unit_weight_unit), "gram"
                    ).converted_value
                ),
            )
            calculations["percentage_w_w"] = asdict(pct_ww)

            daily_exposure_result = calculate_daily_exposure(
                quantity_per_dosage_unit=proposed_quantity_per_unit,
                maximum_dosage_units_per_day=maximum_dosage_units_per_day,
            )
            calculations["daily_exposure"] = asdict(daily_exposure_result)

        if unit_conversion_ok:
            pct_potency = calculate_percentage_of_potency(
                converted_proposed_quantity=converted_proposed_quantity,
                selected_iid_potency_amount=selected.potency_amount,
            )
            calculations["percentage_of_iid_potency"] = asdict(pct_potency)
            diff_potency = calculate_difference_from_potency(
                selected_iid_potency_amount=selected.potency_amount,
                converted_proposed_quantity=converted_proposed_quantity,
            )
            calculations["difference_from_iid_potency"] = asdict(diff_potency)

            if (
                selected.maximum_daily_exposure is not None
                and daily_exposure_result is not None
                and daily_exposure_result.ok
            ):
                mde_conversion = unit_conversion.convert(
                    daily_exposure_result.value,
                    calc_unit,
                    selected.mde_unit,
                    density_g_per_ml=density_g_per_ml,
                )
                calculations["mde_unit_conversion"] = asdict(mde_conversion)
                if mde_conversion.ok:
                    converted_daily_exposure = mde_conversion.converted_value
                    mde_available = True
                    pct_mde = calculate_percentage_of_mde(
                        converted_proposed_daily_exposure=converted_daily_exposure,
                        selected_iid_mde=selected.maximum_daily_exposure,
                    )
                    calculations["percentage_of_iid_mde"] = asdict(pct_mde)
                    diff_mde = calculate_difference_from_mde(
                        selected_iid_mde=selected.maximum_daily_exposure,
                        converted_proposed_daily_exposure=converted_daily_exposure,
                    )
                    calculations["difference_from_iid_mde"] = asdict(diff_mde)

    decision = decide(
        match_status=match.status,
        unit_conversion_ok=unit_conversion_ok,
        proposed_amount_per_unit=converted_proposed_quantity,
        selected_potency_amount=selected.potency_amount if selected else None,
        proposed_daily_exposure=converted_daily_exposure,
        selected_mde=selected.maximum_daily_exposure if selected else None,
        mde_available=mde_available,
        multiple_candidates=(match.status == "MULTIPLE_EXACT_MATCHES"),
        source_release_superseded=(release.status == "superseded" if release else False),
        density_or_basis_required=density_or_basis_required,
        cannot_compare_reason=cannot_compare_reason,
    )

    return AssessmentPreview(
        match_status=match.status,
        candidates=candidates_data,
        selected_record=(asdict(selected) if selected else None),
        calculations={k: _decimal_safe(v) for k, v in calculations.items()},
        decision_status=decision.status,
        decision_note=decision.note,
        escalation_required=decision.escalation_required,
        substance_mapping_public_id=selected_substance_mapping_public_id,
        substance_resolution_status=(substance_resolution.status if substance_resolution else None),
    )


def _decimal_safe(value):
    if isinstance(value, dict):
        return {k: _decimal_safe(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return str(value)
    return value


def _not_per_dose_unit(formula_id: str, amount):
    """A per-dose-unit calculation refused because the stated amount is not per
    dosage unit (per stated volume, or a percentage). Never computed."""
    from datetime import UTC, datetime

    from .calculations import FORMULA_VERSION, CalculationResult, CalculationStatus

    return CalculationResult(
        formula_identifier=formula_id,
        formula_version=FORMULA_VERSION,
        status=CalculationStatus.BASIS_UNCLEAR,
        reason_code="NOT_PER_DOSE_UNIT",
        inputs={"proposed_quantity": str(amount)},
        generated_at=datetime.now(tz=UTC).isoformat(),
    )
