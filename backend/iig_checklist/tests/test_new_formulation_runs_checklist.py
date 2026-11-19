"""QA-01 closed: a formulation created through the API can have the IIG checklist
run on it once it is approved (Option A), and not before. Through the real API."""

from __future__ import annotations

import pytest

from .test_p2_audit_coverage import active_version  # noqa: F401  (pytest fixture)

pytestmark = pytest.mark.django_db
F = "/api/regx/v1/formulations"
EXECUTIONS = "/api/regx/v1/iig-checklists/executions/"


def _new_version(client) -> str:
    product = client.post(
        f"{F}/products/",
        {"product_code": "NEW-QA01", "proposed_product_name": "New", "active_ingredient": "X"},
        format="json",
    ).json()
    vid = client.post(
        f"{F}/products/{product['public_id']}/versions/",
        {"total_dosage_unit_weight": "200", "total_dosage_unit_weight_unit": "mg"},
        format="json",
    ).json()["public_id"]
    client.post(
        f"{F}/versions/{vid}/components/",
        {
            "component_type": "inactive",
            "ingredient_name": "E",
            "quantity_per_dosage_unit": "5",
            "quantity_unit": "mg",
        },
        format="json",
    )
    return vid


def test_the_checklist_runs_only_after_approval(api_client_doer, api_client_vp, active_version):  # noqa: F811
    vid = _new_version(api_client_doer)
    body = {
        "checklist_version_public_id": str(active_version.public_id),
        "formulation_version_public_id": vid,
    }

    refused = api_client_doer.post(EXECUTIONS, body, format="json")
    assert refused.status_code in (400, 409)
    assert "formulation_version_not_approved" in str(refused.json())

    assert (
        api_client_doer.post(f"{F}/versions/{vid}/submit-review/", {}, format="json").status_code
        == 200
    )
    assert (
        api_client_vp.post(
            f"{F}/versions/{vid}/approve/",
            {"note": "Internal approval for the test."},
            format="json",
        ).status_code
        == 200
    )

    created = api_client_doer.post(EXECUTIONS, body, format="json")
    assert created.status_code == 201, created.json()
    assert created.json()["status"] == "draft"
