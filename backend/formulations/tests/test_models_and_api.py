"""
Formulations model, immutability, and tenant-isolation tests. Every test
that plants a violation is noted.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from formulations.models import (
    ComponentType,
    DosingRegimen,
    FormulationComponent,
    FormulationStatus,
    FormulationVersion,
    ProductDevelopmentRecord,
)

BASE = "/api/regx/v1"


@pytest.mark.django_db
class TestProductDevelopmentRecord:
    def test_product_code_unique_per_tenant(self, tenant_a):
        ProductDevelopmentRecord.objects.create(
            tenant=tenant_a, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ProductDevelopmentRecord.objects.create(
                tenant=tenant_a,
                product_code="PROD-1",
                proposed_product_name="B",
                active_ingredient="Y",
            )

    def test_same_code_allowed_across_tenants(self, tenant_a, tenant_b):
        ProductDevelopmentRecord.objects.create(
            tenant=tenant_a, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )
        ProductDevelopmentRecord.objects.create(
            tenant=tenant_b, product_code="PROD-1", proposed_product_name="B", active_ingredient="Y"
        )

    def test_no_reference_product_selected_by_default(self, tenant_a):
        # PLANTED VIOLATION (detected): a product must never appear to
        # have a reference product auto-selected.
        product = ProductDevelopmentRecord.objects.create(
            tenant=tenant_a, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )
        assert not product.has_selected_reference_product
        assert product.selected_ob_product_public_id is None


@pytest.mark.django_db
class TestFormulationVersion:
    def _product(self, tenant):
        return ProductDevelopmentRecord.objects.create(
            tenant=tenant, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )

    def test_total_weight_must_be_positive(self, tenant_a):
        # PLANTED VIOLATION (detected): zero total dosage-unit weight
        # must be rejected at the DB level.
        product = self._product(tenant_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            FormulationVersion.objects.create(
                product=product,
                version_number=1,
                total_dosage_unit_weight=Decimal("0"),
                total_dosage_unit_weight_unit="milligram",
            )

    def test_version_number_unique_per_product(self, tenant_a):
        product = self._product(tenant_a)
        FormulationVersion.objects.create(
            product=product,
            version_number=1,
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            FormulationVersion.objects.create(
                product=product,
                version_number=1,
                total_dosage_unit_weight=Decimal("600"),
                total_dosage_unit_weight_unit="milligram",
            )

    def test_approved_version_is_immutable(self, tenant_a):
        # PLANTED VIOLATION (detected): editing an approved formulation
        # version must be rejected.
        product = self._product(tenant_a)
        version = FormulationVersion.objects.create(
            product=product,
            version_number=1,
            status=FormulationStatus.APPROVED,
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        version.total_dosage_unit_weight = Decimal("999")
        with pytest.raises(ValidationError):
            version.full_clean()

    def test_quantities_are_decimal_not_float(self, tenant_a):
        product = self._product(tenant_a)
        version = FormulationVersion.objects.create(
            product=product,
            version_number=1,
            total_dosage_unit_weight=Decimal("500.123456"),
            total_dosage_unit_weight_unit="milligram",
        )
        assert isinstance(version.total_dosage_unit_weight, Decimal)
        assert not isinstance(version.total_dosage_unit_weight, float)


@pytest.mark.django_db
class TestFormulationComponent:
    def _version(self, tenant):
        product = ProductDevelopmentRecord.objects.create(
            tenant=tenant, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )
        return FormulationVersion.objects.create(
            product=product,
            version_number=1,
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )

    def test_negative_quantity_rejected(self, tenant_a):
        # PLANTED VIOLATION (detected): a negative excipient quantity
        # must be rejected at the DB level.
        version = self._version(tenant_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            FormulationComponent.objects.create(
                formulation_version=version,
                component_type=ComponentType.INACTIVE,
                ingredient_name="Starch",
                quantity_per_dosage_unit=Decimal("-5"),
                quantity_unit="milligram",
            )

    def test_zero_quantity_rejected(self, tenant_a):
        version = self._version(tenant_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            FormulationComponent.objects.create(
                formulation_version=version,
                component_type=ComponentType.INACTIVE,
                ingredient_name="Starch",
                quantity_per_dosage_unit=Decimal("0"),
                quantity_unit="milligram",
            )


@pytest.mark.django_db
class TestDosingRegimen:
    def test_max_units_per_day_must_be_positive(self, tenant_a):
        product = ProductDevelopmentRecord.objects.create(
            tenant=tenant_a, product_code="PROD-1", proposed_product_name="A", active_ingredient="X"
        )
        version = FormulationVersion.objects.create(
            product=product,
            version_number=1,
            total_dosage_unit_weight=Decimal("500"),
            total_dosage_unit_weight_unit="milligram",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            DosingRegimen.objects.create(
                formulation_version=version,
                units_per_administration=Decimal("1"),
                administrations_per_day=Decimal("0"),
                maximum_units_per_day=Decimal("0"),
            )


@pytest.mark.django_db
class TestTenantIsolationApi:
    def test_cross_tenant_product_access_returns_generic_404(
        self, api_client_a, api_client_b, tenant_a
    ):
        resp = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-X",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]

        # PLANTED VIOLATION (detected): tenant B must never see tenant A's
        # product development record.
        cross_resp = api_client_b.get(f"{BASE}/formulations/products/{public_id}/")
        assert cross_resp.status_code == 404

    def test_duplicate_product_code_returns_structured_400(self, api_client_a):
        # A duplicate product_code within the same tenant hits the DB
        # UniqueConstraint -- must surface as a clean 400, never a raw
        # IntegrityError/500.
        first = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-DUP",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        assert first.status_code == 201
        second = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-DUP",
                "proposed_product_name": "Name 2",
                "active_ingredient": "Y",
            },
            format="json",
        )
        assert second.status_code == 400

    def test_no_numeric_id_in_response(self, api_client_a):
        resp = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-Y",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" not in data
        assert "pk" not in data
        assert "tenant" not in data or not isinstance(data.get("tenant"), int)

    def test_select_reference_product_requires_explicit_call_never_auto(self, api_client_a):
        create_resp = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-Z",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        public_id = create_resp.json()["public_id"]
        detail_resp = api_client_a.get(f"{BASE}/formulations/products/{public_id}/")
        assert detail_resp.json()["selected_ob_product_public_id"] is None

        # Selection is now validated against a real product in the active
        # Orange Book release (test_reference_selection.py). Random UUIDs, which
        # this test used to send, are correctly refused.
        from fda_data.models import (
            FDADataSourceRelease,
            FDAReleaseStatus,
            OrangeBookApplication,
            OrangeBookProduct,
        )

        release = FDADataSourceRelease.objects.create(
            dataset_type="orange_book_products",
            source_name="Orange Book",
            official_source_reference="Test fixture",
            source_checksum_sha256="c" * 64,
            status=FDAReleaseStatus.ACTIVE,
        )
        app = OrangeBookApplication.objects.create(
            release=release, application_type="A", application_number="099999"
        )
        ob_product = OrangeBookProduct.objects.create(
            release=release, application=app, product_number="001", active_ingredient_raw="X"
        )

        select_resp = api_client_a.post(
            f"{BASE}/formulations/products/{public_id}/select-reference/",
            data={
                "application_number": "099999",
                "product_number": "001",
                "product_public_id": str(ob_product.public_id),
                "release_public_id": str(release.public_id),
                "justification": "Only exact route/dosage-form/strength match.",
            },
            format="json",
        )
        assert select_resp.status_code == 200
        assert select_resp.json()["selected_ob_product_public_id"] is not None


@pytest.mark.django_db
class TestFormulationVersionComponentApi:
    def _version_public_id(self, api_client):
        product_resp = api_client.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-COMP-1",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        product_public_id = product_resp.json()["public_id"]
        version_resp = api_client.post(
            f"{BASE}/formulations/products/{product_public_id}/versions/",
            data={"total_dosage_unit_weight": "500", "total_dosage_unit_weight_unit": "milligram"},
            format="json",
        )
        assert version_resp.status_code == 201
        return version_resp.json()["public_id"]

    def test_create_component_via_api(self, api_client_a):
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version_public_id}/components/",
            data={
                "component_type": ComponentType.INACTIVE,
                "ingredient_name": "Synthetic Starch",
                "quantity_per_dosage_unit": "30",
                "quantity_unit": "milligram",
            },
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ingredient_name"] == "Synthetic Starch"
        assert "id" not in body

    def test_create_component_rejects_negative_quantity(self, api_client_a):
        # PLANTED VIOLATION (detected): the API must return a clean,
        # structured 400 for a negative excipient quantity -- never a raw
        # database IntegrityError. Serializer-level validation is the
        # primary defense; the DB check constraint is the backstop.
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version_public_id}/components/",
            data={
                "component_type": ComponentType.INACTIVE,
                "ingredient_name": "Synthetic Starch",
                "quantity_per_dosage_unit": "-5",
                "quantity_unit": "milligram",
            },
            format="json",
        )
        assert resp.status_code == 400

    def test_create_component_rejects_zero_quantity(self, api_client_a):
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version_public_id}/components/",
            data={
                "component_type": ComponentType.INACTIVE,
                "ingredient_name": "Synthetic Starch",
                "quantity_per_dosage_unit": "0",
                "quantity_unit": "milligram",
            },
            format="json",
        )
        assert resp.status_code == 400

    def test_create_version_rejects_zero_total_weight(self, api_client_a):
        product_resp = api_client_a.post(
            f"{BASE}/formulations/products/",
            data={
                "product_code": "PROD-ZERO-WEIGHT",
                "proposed_product_name": "Name",
                "active_ingredient": "X",
            },
            format="json",
        )
        product_public_id = product_resp.json()["public_id"]
        resp = api_client_a.post(
            f"{BASE}/formulations/products/{product_public_id}/versions/",
            data={"total_dosage_unit_weight": "0", "total_dosage_unit_weight_unit": "milligram"},
            format="json",
        )
        assert resp.status_code == 400

    def test_cross_tenant_component_creation_returns_generic_404(self, api_client_a, api_client_b):
        # PLANTED VIOLATION (detected): tenant B must never be able to add
        # a component to tenant A's formulation version.
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_b.post(
            f"{BASE}/formulations/versions/{version_public_id}/components/",
            data={
                "component_type": ComponentType.INACTIVE,
                "ingredient_name": "Synthetic Starch",
                "quantity_per_dosage_unit": "30",
                "quantity_unit": "milligram",
            },
            format="json",
        )
        assert resp.status_code == 404

    def test_create_dosing_regimen_via_api(self, api_client_a):
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version_public_id}/dosing-regimens/",
            data={
                "units_per_administration": "1",
                "administrations_per_day": "4",
                "maximum_units_per_day": "4",
                "basis": "Proposed labeling.",
            },
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["maximum_units_per_day"] == "4.0000"
        assert "id" not in body

    def test_create_dosing_regimen_rejects_zero_max_units(self, api_client_a):
        # PLANTED VIOLATION (detected): a zero maximum-units-per-day must
        # return a clean structured 400, never a raw database
        # IntegrityError -- the DB check constraint is the backstop only.
        version_public_id = self._version_public_id(api_client_a)
        resp = api_client_a.post(
            f"{BASE}/formulations/versions/{version_public_id}/dosing-regimens/",
            data={
                "units_per_administration": "1",
                "administrations_per_day": "0",
                "maximum_units_per_day": "0",
            },
            format="json",
        )
        assert resp.status_code == 400
