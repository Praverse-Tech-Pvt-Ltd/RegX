"""QA-09 (formulations): a governed change and its audit record commit together or not at all.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL; each test asserts the change did not persist. On the old code the create
views wrote the row in their own atomic block and emitted after it closed, and the
reference selection had no transaction at all, so every test here failed.

One test per write view: product, version, component (#154's test, xfail removed),
dosing regimen and reference-product selection. (The approval transitions already
emitted inside their transaction; QA-09 found nothing to fix there.)
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from formulations.models import (
    DosingRegimen,
    FormulationComponent,
    FormulationVersion,
    ProductDevelopmentRecord,
)

from .test_reference_selection import _payload, active_product  # noqa: F401
from .test_version_approval import _draft, people  # noqa: F401

F = "/api/regx/v1/formulations"
pytestmark = pytest.mark.django_db(transaction=True)


def test_product_create_rolls_back_without_its_audit(people):  # noqa: F811
    doer = people["doer"][1]
    with audit_writes_fail():
        attempt(
            doer.post,
            f"{F}/products/",
            {"product_code": "QA09-P", "proposed_product_name": "P", "active_ingredient": "X"},
            format="json",
        )
    assert not ProductDevelopmentRecord.objects.filter(product_code="QA09-P").exists()


def test_version_create_rolls_back_without_its_audit(people):  # noqa: F811
    doer = people["doer"][1]
    product, _ = _draft(doer, code="QA09-V", components=0)
    with audit_writes_fail():
        attempt(
            doer.post,
            f"{F}/products/{product['public_id']}/versions/",
            {
                "total_dosage_unit_weight": "250",
                "total_dosage_unit_weight_unit": "mg",
                "maximum_dosage_units_per_day": "4",
            },
            format="json",
        )
    assert FormulationVersion.objects.filter(product__public_id=product["public_id"]).count() == 1


def test_qa09_component_and_its_audit_commit_together(people):  # noqa: F811
    doer = people["doer"][1]
    _, vid = _draft(doer, code="INV-QA09", components=0)
    with audit_writes_fail():
        attempt(
            doer.post,
            f"{F}/versions/{vid}/components/",
            {
                "component_type": "inactive",
                "ingredient_name": "QA09",
                "quantity_per_dosage_unit": "1",
                "quantity_unit": "mg",
            },
            format="json",
        )
    assert not FormulationComponent.objects.filter(ingredient_name="QA09").exists()


def test_dosing_regimen_rolls_back_without_its_audit(people):  # noqa: F811
    doer = people["doer"][1]
    _, vid = _draft(doer, code="QA09-D", components=0)
    with audit_writes_fail():
        attempt(
            doer.post,
            f"{F}/versions/{vid}/dosing-regimens/",
            {
                "units_per_administration": "1",
                "administrations_per_day": "4",
                "maximum_units_per_day": "4",
                "basis": "Proposed labeling.",
            },
            format="json",
        )
    assert not DosingRegimen.objects.filter(formulation_version__public_id=vid).exists()


def test_reference_selection_rolls_back_without_its_audit(people, active_product):  # noqa: F811
    doer = people["doer"][1]
    product, _ = _draft(doer, code="QA09-R", components=0)
    with audit_writes_fail():
        attempt(
            doer.post,
            f"{F}/products/{product['public_id']}/select-reference/",
            _payload(active_product),
            format="json",
        )
    stored = ProductDevelopmentRecord.objects.get(public_id=product["public_id"])
    assert stored.selected_ob_product_public_id is None
    assert stored.selection_timestamp is None
