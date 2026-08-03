"""API tests for ChecklistExecution endpoints -- Milestone 4D-2."""

import pytest
from django.urls import reverse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(tenant, user):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-API-01",
        proposed_product_name="API Test Product",
        active_ingredient="Synthetic API Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )


def _make_fv(product, user, status="approved"):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status=status,
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


def _make_execution(tenant, cv, fv, user):
    from iig_checklist.models import ChecklistExecution

    ex = ChecklistExecution(
        tenant=tenant,
        checklist_version=cv,
        formulation_version=fv,
        status="draft",
        created_by=user,
    )
    ex.full_clean()
    ex.save()
    return ex


# ---------------------------------------------------------------------------
# List / Create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExecutionListCreate:
    def test_list_returns_200(self, api_client_doer):
        url = reverse("iig_checklist:execution-list-create")
        response = api_client_doer.get(url)
        assert response.status_code == 200

    def test_list_empty(self, api_client_doer):
        url = reverse("iig_checklist:execution-list-create")
        response = api_client_doer.get(url)
        assert response.data["results"] == []

    def test_create_returns_201(
        self, api_client_doer, tenant_a, tenant_definition, user_a, doer_membership
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)

        url = reverse("iig_checklist:execution-list-create")
        resp = api_client_doer.post(
            url,
            {
                "checklist_version_public_id": str(cv.public_id),
                "formulation_version_public_id": str(fv.public_id),
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "draft"

    def test_create_duplicate_active_returns_409(
        self, api_client_doer, tenant_a, tenant_definition, user_a
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)
        _make_execution(tenant_a, cv, fv, user_a)

        url = reverse("iig_checklist:execution-list-create")
        resp = api_client_doer.post(
            url,
            {
                "checklist_version_public_id": str(cv.public_id),
                "formulation_version_public_id": str(fv.public_id),
            },
            format="json",
        )
        assert resp.status_code == 409

    def test_create_unauthenticated_returns_401(self, client):
        url = reverse("iig_checklist:execution-list-create")
        resp = client.post(url, {}, content_type="application/json")
        assert resp.status_code in (401, 403)

    def test_create_reviewer_cannot_create(
        self, api_client_reviewer, tenant_a, tenant_definition, user_a
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)

        url = reverse("iig_checklist:execution-list-create")
        resp = api_client_reviewer.post(
            url,
            {
                "checklist_version_public_id": str(cv.public_id),
                "formulation_version_public_id": str(fv.public_id),
            },
            format="json",
        )
        assert resp.status_code == 403

    def test_create_response_uses_uuid_not_pk(
        self, api_client_doer, tenant_a, tenant_definition, user_a
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)

        url = reverse("iig_checklist:execution-list-create")
        resp = api_client_doer.post(
            url,
            {
                "checklist_version_public_id": str(cv.public_id),
                "formulation_version_public_id": str(fv.public_id),
            },
            format="json",
        )
        assert resp.status_code == 201
        assert "public_id" in resp.data
        assert "id" not in resp.data


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExecutionDetail:
    def test_get_own_tenant_execution(
        self, api_client_doer, tenant_a, tenant_definition, user_a
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)
        ex = _make_execution(tenant_a, cv, fv, user_a)

        url = reverse("iig_checklist:execution-detail", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.get(url)
        assert resp.status_code == 200
        assert resp.data["public_id"] == str(ex.public_id)

    def test_cross_tenant_returns_404(
        self, api_client_doer, tenant_b, tenant_a, tenant_definition, user_a
    ):
        from tenancy.models import Tenant

        other_user = _make_user_b()
        product = _make_product(tenant_b, other_user)
        fv = _make_fv(product, other_user)

        from iig_checklist.models import ChecklistDefinition, ChecklistVersion

        other_def = ChecklistDefinition.objects.create(
            code="IIG-B-1",
            title="Tenant B Def",
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
        ex = _make_execution(tenant_b, other_cv, fv, other_user)

        url = reverse("iig_checklist:execution-detail", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.get(url)
        assert resp.status_code == 404

    def test_status_not_patchable(
        self, api_client_doer, tenant_a, tenant_definition, user_a
    ):
        cv = _make_active_cv(tenant_definition, user_a)
        product = _make_product(tenant_a, user_a)
        fv = _make_fv(product, user_a)
        ex = _make_execution(tenant_a, cv, fv, user_a)

        url = reverse("iig_checklist:execution-detail", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.patch(url, {"status": "approved"}, format="json")
        # Should be 405 (no PATCH) or 400 (field rejected)
        assert resp.status_code in (405, 400)


def _make_user_b():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="cross-tenant-user@example.com",
        password="TestPass1234!",
        full_name="Cross Tenant",
    )


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExecutionActions:
    def _setup(self, tenant, tenant_definition, user):
        cv = _make_active_cv(tenant_definition, user)
        product = _make_product(tenant, user)
        fv = _make_fv(product, user)
        ex = _make_execution(tenant, cv, fv, user)
        return ex

    def test_submit_review(
        self,
        api_client_doer,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        url = reverse("iig_checklist:execution-submit-review", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.post(url)
        assert resp.status_code == 200
        assert resp.data["status"] == "submitted_for_review"

    def test_cancel(
        self,
        api_client_doer,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        url = reverse("iig_checklist:execution-cancel", kwargs={"public_id": ex.public_id})
        resp = api_client_doer.post(url)
        assert resp.status_code == 200
        assert resp.data["status"] == "cancelled"

    def test_approve_requires_reviewer_conclusion(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
        vp_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        ex.status = "submitted_for_review"
        ex.submitted_by = user_a
        ex.save()

        url = reverse("iig_checklist:execution-approve", kwargs={"public_id": ex.public_id})
        # Missing reviewer_conclusion_note -> should fail
        resp = api_client_vp.post(url, {}, format="json")
        assert resp.status_code in (400, 422)

    def test_approve_with_conclusion(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_user,
        doer_membership,
        vp_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        ex.status = "submitted_for_review"
        ex.submitted_by = user_a
        ex.save()

        url = reverse("iig_checklist:execution-approve", kwargs={"public_id": ex.public_id})
        resp = api_client_vp.post(
            url, {"reviewer_conclusion_note": "Approved."}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "approved"

    def test_return_requires_reason(
        self,
        api_client_reviewer,
        tenant_a,
        tenant_definition,
        user_a,
        reviewer_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        ex.status = "submitted_for_review"
        ex.submitted_by = user_a
        ex.save()

        url = reverse("iig_checklist:execution-return", kwargs={"public_id": ex.public_id})
        resp = api_client_reviewer.post(url, {}, format="json")
        assert resp.status_code in (400, 422)

    def test_reject(
        self,
        api_client_vp,
        tenant_a,
        tenant_definition,
        user_a,
        vp_membership,
    ):
        ex = self._setup(tenant_a, tenant_definition, user_a)
        ex.status = "submitted_for_review"
        ex.submitted_by = user_a
        ex.save()

        url = reverse("iig_checklist:execution-reject", kwargs={"public_id": ex.public_id})
        resp = api_client_vp.post(url)
        assert resp.status_code == 200
        assert resp.data["status"] == "rejected"
