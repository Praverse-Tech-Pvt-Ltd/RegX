"""QA-01 (docs/qa/QA_CODEX_REPORT.md): IIG definition authoring dropped the execution scope.

POST iig-checklists/definitions/ with execution_scope=formulation_version or
formulation_component answered 201 with execution_scope "" (the serializer accepts
the field; the view built the model without it). An execution on such a definition
then failed with 400 execution_scope_unclassified. Through the real API.
"""

from __future__ import annotations

import datetime

import pytest

pytestmark = pytest.mark.django_db
DEFS = "/api/regx/v1/iig-checklists/definitions/"
EXECUTIONS = "/api/regx/v1/iig-checklists/executions/"
F = "/api/regx/v1/formulations"


def _create(client, code, scope):
    return client.post(
        DEFS,
        {"code": code, "title": f"QA-01 {code}", "scope_type": "tenant", "execution_scope": scope},
        format="json",
    )


@pytest.mark.parametrize("scope", ["formulation_version", "formulation_component"])
def test_the_scope_sent_at_creation_is_saved(api_client_doer, scope):
    from iig_checklist.models import ChecklistDefinition

    resp = _create(api_client_doer, f"QA01-{scope[:14].upper()}", scope)
    assert resp.status_code == 201, resp.json()
    assert resp.json()["execution_scope"] == scope
    assert (
        ChecklistDefinition.objects.get(public_id=resp.json()["public_id"]).execution_scope == scope
    )


def test_an_unknown_scope_is_refused(api_client_doer):
    resp = _create(api_client_doer, "QA01-BAD", "whole_company")
    assert resp.status_code == 400
    assert "execution_scope" in str(resp.json())


def test_no_scope_is_still_allowed_and_stays_unclassified(api_client_doer):
    resp = api_client_doer.post(
        DEFS, {"code": "QA01-NONE", "title": "QA-01 none", "scope_type": "tenant"}, format="json"
    )
    assert resp.status_code == 201, resp.json()
    assert resp.json()["execution_scope"] == ""


def test_an_execution_starts_on_a_definition_authored_through_the_api(
    api_client_doer, api_client_vp, user_a
):
    from iig_checklist.models import ChecklistDefinition, ChecklistVersion

    created = _create(api_client_doer, "QA01-EXEC", "formulation_version").json()
    definition = ChecklistDefinition.objects.get(public_id=created["public_id"])
    # The version lifecycle is covered elsewhere; an active version is enough here.
    version = ChecklistVersion.objects.create(
        definition=definition,
        version_number=1,
        status="active",
        effective_date=datetime.date(2026, 1, 1),
        created_by=user_a,
    )
    product = api_client_doer.post(
        f"{F}/products/",
        {"product_code": "QA01-P", "proposed_product_name": "P", "active_ingredient": "X"},
        format="json",
    ).json()
    fv = api_client_doer.post(
        f"{F}/products/{product['public_id']}/versions/",
        {"total_dosage_unit_weight": "200", "total_dosage_unit_weight_unit": "mg"},
        format="json",
    ).json()["public_id"]
    api_client_doer.post(
        f"{F}/versions/{fv}/components/",
        {
            "component_type": "inactive",
            "ingredient_name": "E",
            "quantity_per_dosage_unit": "5",
            "quantity_unit": "mg",
        },
        format="json",
    )
    assert (
        api_client_doer.post(f"{F}/versions/{fv}/submit-review/", {}, format="json").status_code
        == 200
    )
    assert (
        api_client_vp.post(
            f"{F}/versions/{fv}/approve/",
            {"note": "Internal approval for the test."},
            format="json",
        ).status_code
        == 200
    )
    resp = api_client_doer.post(
        EXECUTIONS,
        {
            "checklist_version_public_id": str(version.public_id),
            "formulation_version_public_id": fv,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.json()
