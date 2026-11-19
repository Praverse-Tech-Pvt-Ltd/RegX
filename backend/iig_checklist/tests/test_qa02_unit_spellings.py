"""QA-02 (QA_CODEX_REPORT.md): IIG built-in calculations rejected normal unit spellings.

Codex's case: an approved 250 mg formulation, 4 units/day, inactive components
of 25 mg, 0.05 g and 7,500 µg, run through a component-scoped checklist with the
`percentage_w_w` and `daily_exposure` bindings. All six outcomes came back
UNIT_MISMATCH (value null); the same amounts in canonical "gram" gave 6/6
correct numbers. The checklist adapter passed stored spellings ("mg", "g", "µg")
straight to the converter, which knows only canonical names. It now uses the
same alias function as the IID comparison path
(iid_assessment.unit_conversion.canonical_unit).

Hand check (0.250 g unit weight, 4 units/day):
  25 mg    = 0.025 g  -> 0.025 / 0.250 x 100 = 10 % w/w;  0.025 x 4 = 0.100 g/day
  0.05 g   = 0.050 g  -> 0.050 / 0.250 x 100 = 20 % w/w;  0.050 x 4 = 0.200 g/day
  7,500 µg = 0.0075 g -> 0.0075 / 0.250 x 100 = 3 % w/w;  0.0075 x 4 = 0.030 g/day
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from formulations.testing import create_on_any_version
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.enums import AnswerType, CalculationStatus, Criticality, DataSourceClassification
from iig_checklist.unit_adapter import convert_for_calculation

HAND_CHECK = {
    # (amount, unit): (expected % w/w, expected g/day)
    ("25", "mg"): (Decimal("10"), Decimal("0.1")),
    ("0.05", "g"): (Decimal("20"), Decimal("0.2")),
    ("7500", "µg"): (Decimal("3"), Decimal("0.03")),
}


def _question(section, code, *, answer_type, classification, binding="", order=1):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section,
        code=code,
        question_text=f"Q {code}",
        display_order=order,
        answer_type=answer_type,
        data_source_classification=classification,
        calculation_binding_identifier=binding,
        criticality=Criticality.LOW,
    )


@pytest.fixture
def codex_case(db, tenant_a, tenant_definition, user_a, doer_membership):
    """An approved 250 mg / 4-per-day formulation with Codex's three components,
    and an execution with the selector, % w/w and daily-exposure questions."""
    from formulations.models import (
        FormulationComponent,
        FormulationVersion,
        ProductDevelopmentRecord,
    )
    from iig_checklist.models import ChecklistResponse, ChecklistSection, ChecklistVersion
    from iig_checklist.services import create_execution

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a,
        product_code="QA02-CODEX",
        proposed_product_name="QA-02 product",
        active_ingredient="Synthetic Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user_a,
    )
    formulation = FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal("250"),
        total_dosage_unit_weight_unit="mg",
        maximum_dosage_units_per_day=Decimal("4"),
        created_by=user_a,
    )
    components = {
        key: create_on_any_version(
            FormulationComponent,
            formulation_version=formulation,
            component_type="inactive",
            ingredient_name=f"Excipient {n}",
            quantity_per_dosage_unit=Decimal(key[0]),
            quantity_unit=key[1],
            display_order=n,
        )
        for n, key in enumerate(HAND_CHECK, start=1)
    }
    version = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active", created_by=user_a
    )
    section = ChecklistSection.objects.create(
        checklist_version=version,
        code="S1",
        title="S1",
        display_order=1,
        criticality=Criticality.MEDIUM,
    )
    selector_q = _question(
        section,
        registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED,
        order=1,
    )
    calc = {
        key: _question(
            section,
            code,
            answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED,
            binding=key,
            order=n,
        )
        for n, (key, code) in enumerate(
            (("percentage_w_w", "Q_PCT_WW"), ("daily_exposure", registry_mod.Q_DAILY_EXPOSURE)),
            start=2,
        )
    }
    execution = create_execution(
        tenant=tenant_a,
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(formulation.public_id),
        actor=user_a,
    )
    return {
        "execution": execution,
        "components": components,
        "selector": ChecklistResponse.objects.get(execution=execution, question=selector_q),
        "responses": {
            k: ChecklistResponse.objects.get(execution=execution, question=q)
            for k, q in calc.items()
        },
    }


def _select(client, case, component):
    """PATCH the subject-component selector through the API (the cascade trigger)."""
    selector = case["selector"]
    selector.refresh_from_db()
    url = reverse(
        "iig_checklist:execution-response-update",
        kwargs={"public_id": case["execution"].public_id, "response_public_id": selector.public_id},
    )
    return client.patch(
        url,
        {
            "raw_value": {"public_id": str(component.public_id)},
            "expected_version": selector.version,
        },
        format="json",
    )


def _outcome(case, key):
    from iig_checklist.models import CalculationOutcome

    return CalculationOutcome.objects.get(response=case["responses"][key])


@pytest.mark.django_db
class TestCodexCaseThroughTheChecklist:
    @pytest.mark.parametrize("key", list(HAND_CHECK))
    def test_all_six_values_match_the_hand_check(self, api_client_doer, codex_case, key):
        resp = _select(api_client_doer, codex_case, codex_case["components"][key])
        assert resp.status_code == 200, resp.json()
        want_pct, want_day = HAND_CHECK[key]
        pct, day = _outcome(codex_case, "percentage_w_w"), _outcome(codex_case, "daily_exposure")
        assert pct.status == CalculationStatus.COMPLETE and pct.value == want_pct, (
            pct.status,
            pct.reason_code,
            pct.value,
        )
        assert day.status == CalculationStatus.COMPLETE and day.value == want_day, (
            day.status,
            day.reason_code,
            day.value,
        )


class TestAdapterAcceptsTheSpellingsTheComparisonAccepts:
    """The checklist adapter and the IID comparison read the same unit spellings."""

    @pytest.mark.parametrize(
        ("value", "unit", "grams"),
        [
            ("25", "mg", "0.025"),
            ("25", "MG", "0.025"),
            ("25", "milligram", "0.025"),
            ("0.05", "g", "0.05"),
            ("7500", "µg", "0.0075"),  # micro sign
            ("7500", "μg", "0.0075"),  # Greek mu
            ("7500", "mcg", "0.0075"),
            ("7500", "ug", "0.0075"),
            ("0.001", "kg", "1"),
        ],
    )
    def test_mass_spellings_convert_to_gram(self, value, unit, grams):
        outcome = convert_for_calculation(value=Decimal(value), from_unit=unit, to_unit="gram")
        assert outcome.ok, outcome.failure_code
        assert outcome.value == Decimal(grams)

    def test_volume_spellings(self):
        outcome = convert_for_calculation(value=Decimal("5"), from_unit="ml", to_unit="litre")
        assert outcome.ok and outcome.value == Decimal("0.005")

    @pytest.mark.parametrize("unit", ["tablets", "furlongs", "mg/5mL"])
    def test_unknown_units_still_fail_closed(self, unit):
        outcome = convert_for_calculation(value=Decimal("1"), from_unit=unit, to_unit="gram")
        assert not outcome.ok
        assert outcome.failure_code == "INPUT_UNIT_UNSUPPORTED"

    def test_mass_to_volume_still_refused(self):
        outcome = convert_for_calculation(value=Decimal("1"), from_unit="mg", to_unit="millilitre")
        assert not outcome.ok
