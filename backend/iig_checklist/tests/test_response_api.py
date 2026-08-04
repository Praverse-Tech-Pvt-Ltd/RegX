"""API tests for ChecklistResponse endpoints -- Milestone 4D-2."""

import pytest
from django.urls import reverse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(tenant, user, code="PROD-RESP-01"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name=f"Product {code}",
        active_ingredient="Synthetic Resp Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _make_fv(product, user):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()
    return fv


def _make_active_cv(tenant_definition, user):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        status="active",
        created_by=user,
    )


def _make_question(cv, user, answer_type="yes_no", code="Q-1", required=False, **extra):
    from iig_checklist.models import ChecklistQuestion, ChecklistSection

    section, _ = ChecklistSection.objects.get_or_create(
        checklist_version=cv,
        code="SEC-1",
        defaults={
            "title": "Section 1",
            "display_order": 1,
            "criticality": "low",
        },
    )
    fields = {
        "section": section,
        "code": code,
        "question_text": "Question text",
        "display_order": ChecklistQuestion.objects.filter(section=section).count() + 1,
        "answer_type": answer_type,
        "data_source_classification": extra.pop("data_source_classification", "user_required"),
        "criticality": "low",
        "required": required,
    }
    fields.update(extra)
    return ChecklistQuestion.objects.create(**fields)


def _make_execution_with_responses(tenant, cv, fv, user):
    """Create execution; responses are created by create_execution service."""
    # Grant permission inline by inserting a membership.
    from authorization.models import MembershipRole, Role
    from iig_checklist.services import create_execution
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(tenant=tenant, name="doer", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    return create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=user,
    )


# ---------------------------------------------------------------------------
# Response list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResponseList:
    def test_list_responses_returns_200(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        _make_question(cv, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)
        ex = _make_execution_with_responses(tenant_a, cv, fv, user_a)

        url = reverse("iig_checklist:execution-response-list", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.get(url)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    def test_cross_tenant_response_list_returns_404(
        self,
        api_client_doer,
        tenant_a,
        tenant_b,
        tenant_definition,
        user_a,
        doer_membership,
    ):
        from iig_checklist.models import ChecklistDefinition, ChecklistVersion

        other_user = _make_other_user("resp-other@example.com")
        other_def = ChecklistDefinition.objects.create(
            code="IIG-B-RESP",
            title="B",
            scope_type="tenant",
            tenant=tenant_b,
            created_by=other_user,
        )
        other_cv = ChecklistVersion.objects.create(
            definition=other_def,
            version_number=1,
            status="active",
            created_by=other_user,
        )
        _make_question(other_cv, other_user)
        product = _make_product(tenant_b, other_user, code="PROD-B-1")
        fv = _make_fv(product, other_user)
        ex = _make_execution_with_responses(tenant_b, other_cv, fv, other_user)

        url = reverse("iig_checklist:execution-response-list", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.get(url)
        assert resp.status_code == 404


def _make_other_user(email):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email=email, password="TestPass1234!", full_name="Other User")


# ---------------------------------------------------------------------------
# Response update (PATCH)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResponseUpdate:
    def _setup(self, tenant, tenant_definition, user, answer_type="yes_no"):
        cv = _make_active_cv(tenant_definition, user)
        _make_question(cv, user, answer_type=answer_type)
        product = _make_product(tenant, user)
        fv = _make_fv(product, user)
        ex = _make_execution_with_responses(tenant, cv, fv, user)
        response = ex.responses.first()
        return ex, response

    def test_patch_raw_value_accepted(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        ex, response = self._setup(tenant_a, tenant_definition, user_a)
        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={"public_id": ex.public_id, "response_public_id": response.public_id},
        )
        resp = api_client_doer.patch(url, {"raw_value": {"value": True}}, format="json")
        assert resp.status_code == 200

    def test_patch_version_rejected(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        ex, response = self._setup(tenant_a, tenant_definition, user_a)
        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={"public_id": ex.public_id, "response_public_id": response.public_id},
        )
        resp = api_client_doer.patch(url, {"version": 99}, format="json")
        # version is read-only -- either ignored or 400
        if resp.status_code == 200:
            assert resp.data.get("version") != 99

    def test_patch_reviewer_conclusion_answer_type_rejected(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        _make_question(cv, user_a, answer_type="reviewer_conclusion")
        product = _make_product(tenant_a, user_a, code="PROD-RC-03")
        fv = _make_fv(product, user_a)
        ex = _make_execution_with_responses(tenant_a, cv, fv, user_a)
        response = ex.responses.first()

        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={"public_id": ex.public_id, "response_public_id": response.public_id},
        )
        resp = api_client_doer.patch(
            url, {"raw_value": {"value": "conclusion text"}}, format="json"
        )
        assert resp.status_code == 400

    def test_patch_not_applicable(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        ex, response = self._setup(tenant_a, tenant_definition, user_a)
        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={"public_id": ex.public_id, "response_public_id": response.public_id},
        )
        resp = api_client_doer.patch(
            url,
            {"is_not_applicable": True, "not_applicable_reason": "Not relevant"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["is_not_applicable"] is True

    def test_response_immutable_when_not_in_draft(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        ex, response = self._setup(tenant_a, tenant_definition, user_a)
        ex.status = "submitted_for_review"
        ex.save()

        url = reverse(
            "iig_checklist:execution-response-update",
            kwargs={"public_id": ex.public_id, "response_public_id": response.public_id},
        )
        resp = api_client_doer.patch(url, {"raw_value": {"value": False}}, format="json")
        assert resp.status_code in (400, 422, 409)
