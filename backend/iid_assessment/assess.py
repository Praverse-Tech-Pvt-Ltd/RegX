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
from .matching import find_iid_candidates


@dataclass
class AssessmentPreview:
    match_status: str
    candidates: list
    selected_record: dict | None
    calculations: dict
    decision_status: str
    decision_note: str
    escalation_required: bool


def run_preview(
    *,
    ingredient_public_id,
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
    match = find_iid_candidates(
        ingredient_public_id=resolved_ingredient_public_id,
        controlled_route_id=route.id if route else None,
        controlled_dosage_form_id=dosage_form.id if dosage_form else None,
        active_release_id=release.id if release else None,
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

    if selected is not None:
        conversion = unit_conversion.convert(
            proposed_quantity_per_unit,
            proposed_quantity_unit,
            selected.potency_unit,
            density_g_per_ml=density_g_per_ml,
        )
        calculations["unit_conversion"] = asdict(conversion)
        if conversion.ok:
            converted_proposed_quantity = conversion.converted_value
        else:
            unit_conversion_ok = False
            if conversion.reason_code == unit_conversion.ConversionReasonCode.DENSITY_REQUIRED:
                density_or_basis_required = True

        pct_ww = calculate_percentage_w_w(
            quantity_per_unit_grams=(
                unit_conversion.convert(
                    proposed_quantity_per_unit, proposed_quantity_unit, "gram"
                ).converted_value
            ),
            total_dosage_unit_weight_grams=(
                unit_conversion.convert(
                    total_dosage_unit_weight, total_dosage_unit_weight_unit, "gram"
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

            if selected.maximum_daily_exposure is not None and daily_exposure_result.ok:
                mde_conversion = unit_conversion.convert(
                    daily_exposure_result.value,
                    proposed_quantity_unit,
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
    )

    return AssessmentPreview(
        match_status=match.status,
        candidates=candidates_data,
        selected_record=(asdict(selected) if selected else None),
        calculations={k: _decimal_safe(v) for k, v in calculations.items()},
        decision_status=decision.status,
        decision_note=decision.note,
        escalation_required=decision.escalation_required,
    )


def _decimal_safe(value):
    if isinstance(value, dict):
        return {k: _decimal_safe(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return str(value)
    return value
