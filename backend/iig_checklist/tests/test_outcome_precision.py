"""#140 check: a checklist calculation whose exact result has more than 10 decimal places.

#140 stored outcome values without trailing zeros, which fixed 0.1000000000000.
A result that genuinely needs more than 10 places (1/3, or a µg-scale amount) still
does not fit the outcome field (DecimalField, 10 decimal places). Through the real
checklist path (selector PATCH -> cascade) it must not 500, and it must not lose
digits silently: the stored value is rounded half-even to the field's 10 places,
the outcome says so in its rounding rule, and the exact value is kept in the
outcome's provenance.

Formulation: 300 mg unit weight, 1.2345 units/day.
  1 mg        -> % w/w = 0.001 / 0.3 x 100 = 0.3333... (repeating)
  0.000001 mg -> % w/w = 0.000000001 / 0.3 x 100 = 0.00000033333...;
                 daily = 0.000000001 g x 1.2345 = 0.0000000012345 g (13 places)
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from django.urls import reverse

from formulations.testing import create_on_any_version
from iig_checklist import calculation_registry as registry_mod
from iig_checklist.enums import AnswerType, CalculationStatus, Criticality, DataSourceClassification

TEN = Decimal("1e-10")
EXACT = {
    ("1", "mg"): {
        "percentage_w_w": Decimal(1) / Decimal(3) * 1,  # 0.001/0.3*100 = 1/3
        "daily_exposure": Decimal("0.0012345"),
    },
    ("0.000001", "mg"): {
        "percentage_w_w": Decimal("0.000000001") / Decimal("0.3") * 100,
        "daily_exposure": Decimal("0.0000000012345"),
    },
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
def case(db, tenant_a, tenant_definition, user_a, doer_membership):
    from formulations.models import (
        FormulationComponent,
        FormulationVersion,
        ProductDevelopmentRecord,
    )
    from iig_checklist.models import ChecklistResponse, ChecklistSection, ChecklistVersion
    from iig_checklist.services import create_execution

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a,
        product_code="PRECISION",
        proposed_product_name="Precision product",
        active_ingredient="Synthetic",
        dosage_form="tablet",
        route="oral",
        created_by=user_a,
    )
    formulation = FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal("300"),
        total_dosage_unit_weight_unit="mg",
        maximum_dosage_units_per_day=Decimal("1.2345"),
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
        for n, key in enumerate(EXACT, start=1)
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
    )
    calc = {
        "percentage_w_w": _question(
            section, "Q_PCT_WW", answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED, binding="percentage_w_w", order=2,
        ),
        "daily_exposure": _question(
            section, registry_mod.Q_DAILY_EXPOSURE, answer_type=AnswerType.CALCULATED_VALUE,
            classification=DataSourceClassification.SYSTEM_CALCULATED, binding="daily_exposure", order=3,
        ),
    }  # fmt: skip
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


@pytest.mark.django_db
@pytest.mark.parametrize("key", list(EXACT))
def test_more_than_ten_places_is_rounded_openly_not_a_500(api_client_doer, case, key):
    from iig_checklist.models import CalculationOutcome

    resp = _select(api_client_doer, case, case["components"][key])
    assert resp.status_code == 200, resp.content[:300]
    for name, exact in EXACT[key].items():
        outcome = CalculationOutcome.objects.get(response=case["responses"][name])
        assert outcome.status == CalculationStatus.COMPLETE, (
            name,
            outcome.status,
            outcome.reason_code,
        )
        needs_rounding = exact != exact.quantize(TEN, rounding=ROUND_HALF_EVEN)
        assert outcome.value == exact.quantize(TEN, rounding=ROUND_HALF_EVEN), (name, outcome.value)
        if needs_rounding:
            # Never cut silently: the rule says so, and the exact value is kept.
            assert "10 decimal places" in outcome.rounding_rule, outcome.rounding_rule
            assert Decimal(outcome.input_provenance["unrounded_value"]) == exact
        else:
            assert "unrounded_value" not in outcome.input_provenance
