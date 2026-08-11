"""Fixtures for iid_assessment domain tests. Synthetic data only."""

from decimal import Decimal

import pytest


@pytest.fixture
def tenant_a(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="user-a@example.com", password="TestPass1234!", full_name="User A"
    )


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name=role_name, defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return membership


@pytest.fixture
def doer_membership(db, tenant_a, user_a):
    return _membership_with_role(tenant_a, user_a, "doer")


@pytest.fixture
def api_client_doer(user_a, tenant_a, doer_membership):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_a)
    client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
    return client


@pytest.fixture
def active_iid_setup(db):
    """A fully-approved route/dosage-form/unit + one active IID release
    with one CALCULABLE precedent record for a synthetic ingredient."""
    from fda_data.models import (
        ControlledDosageForm,
        ControlledRoute,
        ControlledUnit,
        DosageFormMapping,
        FDADataSourceRelease,
        FDAReleaseStatus,
        IIDCalculabilityStatus,
        IIDIngredient,
        IIDPrecedentRecord,
        RouteMapping,
    )

    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    RouteMapping.objects.create(
        source_dataset="fda_iid", source_raw_value="ORAL", controlled_route=route, status="approved"
    )
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    DosageFormMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="TABLET",
        controlled_dosage_form=dosage_form,
        status="approved",
    )
    mg_unit = ControlledUnit.objects.create(
        code="milligram", symbol="MG", dimension="mass", active=True
    )

    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="f" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(
        canonical_name="Synthetic Starch", normalized_name="SYNTHETIC STARCH"
    )
    record = IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Synthetic Starch",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("50"),
        potency_unit_raw="MG",
        potency_unit_normalized=mg_unit,
        maximum_daily_exposure=Decimal("200"),
        mde_unit_raw="MG",
        mde_unit_normalized=mg_unit,
        raw_row_checksum="1" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    return {
        "route": route,
        "dosage_form": dosage_form,
        "unit": mg_unit,
        "release": release,
        "ingredient": ingredient,
        "record": record,
    }


@pytest.fixture
def snapshot_formulation(db, tenant_a, user_a, active_iid_setup):
    """A real tenant-owned formulation whose component matches the IID setup.

    ``create_assessment_snapshot()`` derives every frozen value from these rows,
    so a snapshot test needs genuine formulation objects rather than arbitrary
    UUIDs. Route and dosage form match the controlled terms of
    ``active_iid_setup`` and the component carries the resolved ingredient, so
    the preview reaches an exact match.
    """
    from formulations.models import (
        FormulationComponent,
        FormulationVersion,
        ProductDevelopmentRecord,
    )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a,
        product_code="SNAP-PROD-01",
        proposed_product_name="Snapshot Product",
        active_ingredient="Synthetic Starch",
        dosage_form="tablet",
        route="oral",
        created_by=user_a,
    )
    formulation_version = FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight=Decimal("500.000000"),
        total_dosage_unit_weight_unit="milligram",
        maximum_dosage_units_per_day=Decimal("4.0000"),
        created_by=user_a,
    )
    component = FormulationComponent.objects.create(
        formulation_version=formulation_version,
        component_type="inactive",
        ingredient_name="Synthetic Starch",
        resolved_ingredient_public_id=active_iid_setup["ingredient"].public_id,
        quantity_per_dosage_unit=Decimal("30.000000"),
        quantity_unit="milligram",
        display_order=1,
    )
    return {
        "product": product,
        "formulation_version": formulation_version,
        "component": component,
    }
