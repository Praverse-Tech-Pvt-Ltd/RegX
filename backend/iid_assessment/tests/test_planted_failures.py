"""
The 15 named planted-failure scenarios from the Milestone 4A-4C spec,
spanning fda_data, formulations, and iid_assessment.

Each test PLANTS the exact violation described, DETECTS it via an
assertion that the real system's guard rejects/blocks it, RESTORES to a
clean state, and RERUNS to confirm the legitimate path still works. No
planted violation is left committed -- every plant happens inside the
test and is rejected before it can persist.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from fda_data import lifecycle
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    RouteMapping,
)
from fda_data.terminology import lookup_route_mapping
from fda_data.tests._meanings import per_dose_unit
from fda_data.views import _csv_safe_cell
from formulations.models import FormulationVersion, ProductDevelopmentRecord
from iid_assessment import unit_conversion
from iid_assessment.calculations import calculate_daily_exposure, calculate_percentage_of_potency
from iid_assessment.decisions import PrecedentDecision
from iid_assessment.matching import MatchStatus, find_iid_candidates
from iid_assessment.models import AssessmentSnapshot

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


_release_checksum_counter = {"n": 0}


def _make_release(status=FDAReleaseStatus.REGISTERED, imported_by=None, checksum=None):
    _release_checksum_counter["n"] += 1
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256=checksum or f"{_release_checksum_counter['n']:064d}",
        status=status,
        imported_by=imported_by,
        original_filename="/var/secret/fda-iid.txt",
        storage_key="platform/0/deadbeef.json",
    )


# ---------------------------------------------------------------------------
# 1. Auto-activate FDA release
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_1_auto_activate_planted_and_blocked():
    # PLANT: attempt to activate a freshly registered release, skipping
    # submit-for-review and approve entirely.
    release = _make_release(status=FDAReleaseStatus.REGISTERED)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.activate(release, actor=None)
    # DETECT: status never moved.
    release.refresh_from_db()
    assert release.status == FDAReleaseStatus.REGISTERED
    # RESTORE/RERUN: only the real submit -> approve -> activate walk works.
    from django.contrib.auth import get_user_model

    User = get_user_model()
    importer = User.objects.create_user(email="importer-1@example.com", password="x", full_name="I")
    approver = User.objects.create_user(email="approver-1@example.com", password="x", full_name="A")
    release2 = _make_release(status=FDAReleaseStatus.REGISTERED, imported_by=importer)
    release2 = lifecycle.submit_for_review(release2, importer)
    release2 = lifecycle.approve(release2, approver)
    release2 = lifecycle.activate(release2, approver)
    assert release2.status == FDAReleaseStatus.ACTIVE


# ---------------------------------------------------------------------------
# 2. Overwrite active release
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_2_overwrite_active_release_planted_and_blocked():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    approver = User.objects.create_user(email="approver-2@example.com", password="x", full_name="A")
    active = _make_release(status=FDAReleaseStatus.APPROVED)
    active = lifecycle.activate(active, approver)
    assert active.status == FDAReleaseStatus.ACTIVE

    # PLANT: attempt to create a second ACTIVE release for the same
    # dataset_type directly at the ORM layer, bypassing lifecycle.activate's
    # supersession logic entirely.
    with pytest.raises(IntegrityError), transaction.atomic():
        FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID rogue",
            official_source_reference="ref2",
            source_checksum_sha256="b" * 64,
            status=FDAReleaseStatus.ACTIVE,
        )
    # DETECT: only one active release for this dataset_type exists.
    assert (
        FDADataSourceRelease.objects.filter(
            dataset_type="fda_iid", status=FDAReleaseStatus.ACTIVE
        ).count()
        == 1
    )
    # RESTORE/RERUN: the legitimate path (approve a new release, then
    # activate it) correctly supersedes the old one instead of colliding.
    approver2 = User.objects.create_user(
        email="approver-2b@example.com", password="x", full_name="B"
    )
    new_release = _make_release(status=FDAReleaseStatus.APPROVED)
    new_release = lifecycle.activate(new_release, approver2)
    active.refresh_from_db()
    assert active.status == FDAReleaseStatus.SUPERSEDED
    assert new_release.status == FDAReleaseStatus.ACTIVE


# ---------------------------------------------------------------------------
# 3. Parse missing potency as zero
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_3_missing_potency_never_coerced_to_zero():
    from fda_data.importer import _determine_calculability

    ingredient = IIDIngredient.objects.create(canonical_name="X", normalized_name="X")
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    # PLANT (as a hypothesis): if a blank potency were coerced to 0, this
    # would return CALCULABLE with potency_amount effectively "0".
    status = _determine_calculability(
        ingredient=ingredient,
        route_normalized=route,
        dosage_form_normalized=dosage_form,
        potency_amount=None,
        potency_expression=None,
        mde_amount=None,
    )
    # DETECT: it doesn't -- missing potency is its own explicit status.
    assert status == IIDCalculabilityStatus.POTENCY_MISSING
    # Also verify the calculation engine independently refuses to treat a
    # missing/zero reference potency as usable.
    blocked = calculate_percentage_of_potency(
        converted_proposed_quantity=Decimal("10"), selected_iid_potency_amount=None
    )
    assert not blocked.ok
    assert blocked.value is None
    # RESTORE/RERUN: a real potency value calculates cleanly.
    ok_result = calculate_percentage_of_potency(
        converted_proposed_quantity=Decimal("10"), selected_iid_potency_amount=Decimal("50")
    )
    assert ok_result.ok
    assert ok_result.value == Decimal("20")


# ---------------------------------------------------------------------------
# 4. Fuzzy-match route
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_4_fuzzy_route_match_never_resolves():
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    RouteMapping.objects.create(
        source_dataset="fda_iid", source_raw_value="ORAL", controlled_route=route, status="approved"
    )
    # PLANT: a near-miss/lowercase/substring variant of the approved raw
    # value -- a fuzzy matcher would resolve this; ours must not.
    assert lookup_route_mapping("fda_iid", "oral") is None  # case-sensitive, no fuzzy fallback
    assert lookup_route_mapping("fda_iid", "ORAL TABLET") is None  # substring, not exact
    assert lookup_route_mapping("fda_iid", "ORA") is None  # prefix, not exact
    # DETECT: only the exact approved raw value resolves.
    assert lookup_route_mapping("fda_iid", "ORAL") == route
    # RESTORE/RERUN: adding an approved mapping for the variant makes it
    # resolve -- proving the fix is an explicit reviewer-approved mapping,
    # never fuzzy inference.
    RouteMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="ORAL TABLET",
        controlled_route=route,
        status="approved",
    )
    assert lookup_route_mapping("fda_iid", "ORAL TABLET") == route


# ---------------------------------------------------------------------------
# 5. Auto-select highest IID potency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_5_highest_potency_never_auto_selected():
    ingredient = IIDIngredient.objects.create(canonical_name="Y", normalized_name="Y")
    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    unit = ControlledUnit.objects.create(
        code="milligram", symbol="MG", dimension="mass", active=True
    )
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="d" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    low = IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Y",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("10"),
        potency_unit_raw="MG",
        potency_expression=per_dose_unit(unit),
        raw_row_checksum="1" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    high = IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Y",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("500"),
        potency_unit_raw="MG",
        potency_expression=per_dose_unit(unit),
        raw_row_checksum="2" * 64,
        calculability_status=IIDCalculabilityStatus.CALCULABLE,
    )
    # PLANT (as a hypothesis): a "pick the best" matcher would silently
    # return `high` as THE match.
    result = find_iid_candidates(
        ingredient_public_id=str(ingredient.public_id),
        controlled_route_id=route.id,
        controlled_dosage_form_id=dosage_form.id,
        active_release_id=release.id,
    )
    # DETECT: neither is auto-selected -- both come back for human choice.
    assert result.status == MatchStatus.MULTIPLE_EXACT_MATCHES
    returned_ids = {c.precedent_record_public_id for c in result.candidates}
    assert returned_ids == {str(low.public_id), str(high.public_id)}
    # RESTORE/RERUN: removing the ambiguity (only one record) resolves to
    # an EXACT_MATCH on the remaining record, still never "the best one".
    high.delete()
    result2 = find_iid_candidates(
        ingredient_public_id=str(ingredient.public_id),
        controlled_route_id=route.id,
        controlled_dosage_form_id=dosage_form.id,
        active_release_id=release.id,
    )
    assert result2.status == MatchStatus.EXACT_MATCH
    assert result2.candidates[0].precedent_record_public_id == str(low.public_id)


# ---------------------------------------------------------------------------
# 6. Convert mass to volume without density
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_6_mass_to_volume_without_density_blocked():
    # PLANT: attempt a mass->volume conversion with no density supplied.
    result = unit_conversion.convert(Decimal("30"), "milligram", "millilitre")
    # DETECT: fails closed, never silently assumes water-like density.
    assert not result.ok
    assert result.reason_code == unit_conversion.ConversionReasonCode.DENSITY_REQUIRED
    assert result.converted_value is None
    # RESTORE/RERUN: supplying an explicit density succeeds. 30mg at a
    # density of 1 g/mL is 0.03 mL (30mg = 0.03g; 0.03g / 1 g_per_mL = 0.03mL).
    result2 = unit_conversion.convert(
        Decimal("30"), "milligram", "millilitre", density_g_per_ml=Decimal("1.0")
    )
    assert result2.ok
    assert result2.converted_value == Decimal("0.03")


# ---------------------------------------------------------------------------
# 7. Use float arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_7_no_float_arithmetic_artifacts():
    # PLANT: the classic float trap -- 0.1 + 0.2 != 0.3 in binary float.
    result_a = unit_conversion.convert(0.1, "gram", "gram")
    result_b = unit_conversion.convert(0.2, "gram", "gram")
    # DETECT: values pass through Decimal(str(...)), so no binary-float
    # artifact (0.1 + 0.2 == 0.30000000000000004 in real float) appears.
    assert result_a.converted_value == Decimal("0.1")
    assert result_b.converted_value == Decimal("0.2")
    assert result_a.converted_value + result_b.converted_value == Decimal("0.3")
    assert isinstance(result_a.converted_value, Decimal)
    assert not isinstance(result_a.converted_value, float)
    # RESTORE/RERUN: the calculation engine likewise returns Decimal, never
    # float, for its result values.
    calc = calculate_percentage_of_potency(
        converted_proposed_quantity=Decimal("0.1") + Decimal("0.2"),
        selected_iid_potency_amount=Decimal("1"),
    )
    assert isinstance(calc.value, Decimal)


# ---------------------------------------------------------------------------
# 8. Calculate without maximum daily units
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_8_calculate_without_max_daily_units_blocked():
    # PLANT: attempt daily-exposure calculation with maximum_dosage_units_per_day
    # missing.
    result = calculate_daily_exposure(
        quantity_per_dosage_unit=Decimal("30"), maximum_dosage_units_per_day=None
    )
    # DETECT: blocked with an explicit status, never a fabricated result
    # (e.g. treating missing max-units as 1 or 0).
    assert not result.ok
    assert result.value is None
    assert result.status == "DATA_REQUIRED"
    # RESTORE/RERUN: supplying the real value calculates cleanly.
    result2 = calculate_daily_exposure(
        quantity_per_dosage_unit=Decimal("30"), maximum_dosage_units_per_day=Decimal("4")
    )
    assert result2.ok
    assert result2.value == Decimal("120")


# ---------------------------------------------------------------------------
# 9. Cross-tenant formulation lookup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_9_cross_tenant_formulation_lookup_blocked(tenant_a):
    from tenancy.models import Tenant

    tenant_b = Tenant.objects.create(name="Tenant Beta Planted", slug="tenant-beta-planted-9")
    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a, product_code="PROD-9", proposed_product_name="A", active_ingredient="X"
    )
    version = FormulationVersion.objects.create(
        product=product,
        version_number=1,
        total_dosage_unit_weight=Decimal("500"),
        total_dosage_unit_weight_unit="milligram",
    )
    # PLANT: attempt to look up tenant A's formulation version scoped to
    # tenant B.
    # DETECT: the tenant-scoped manager raises DoesNotExist -- it never
    # returns another tenant's row.
    with pytest.raises(FormulationVersion.DoesNotExist):
        FormulationVersion.objects.for_tenant(tenant_b).get(public_id=version.public_id)
    # RESTORE/RERUN: the correct tenant's lookup succeeds.
    found = FormulationVersion.objects.for_tenant(tenant_a).get(public_id=version.public_id)
    assert found.pk == version.pk


# ---------------------------------------------------------------------------
# 10. Expose source path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_10_source_path_never_exposed_to_non_raw_viewer(tenant_a, user_a, doer_membership):
    release = _make_release(status=FDAReleaseStatus.REGISTERED)
    client = _client_for(user_a, tenant_a)
    # PLANT (as a hypothesis): the default (non-raw) serializer accidentally
    # includes storage_key/original_filename for a Doer who lacks view_raw.
    resp = client.get(f"{BASE}/fda-data/releases/{release.public_id}/")
    assert resp.status_code == 200
    data = resp.json()
    # DETECT: neither field, nor the raw path string, appears.
    assert "storage_key" not in data
    assert "original_filename" not in data
    assert "/var/secret" not in str(data)
    # RESTORE/RERUN: a holder of view_raw (VP) does see it -- proving the
    # gate is the permission, not that the data was simply never stored.
    from django.contrib.auth import get_user_model

    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    User = get_user_model()
    vp_user = User.objects.create_user(email="vp-10@example.com", password="x", full_name="VP")
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp_user)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    vp_client = _client_for(vp_user, tenant_a)
    resp2 = vp_client.get(f"{BASE}/fda-data/releases/{release.public_id}/")
    assert "original_filename" in resp2.json()


# ---------------------------------------------------------------------------
# 11. Expose numeric ID
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_11_numeric_id_never_exposed(tenant_a, user_a, doer_membership):
    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a, product_code="PROD-11", proposed_product_name="A", active_ingredient="X"
    )
    client = _client_for(user_a, tenant_a)
    # PLANT (as a hypothesis): a serializer accidentally including the
    # model's default BigAutoField pk would surface it as "id".
    resp = client.get(f"{BASE}/formulations/products/{product.public_id}/")
    assert resp.status_code == 200
    data = resp.json()
    # DETECT: it does not -- only the UUID public_id is present.
    assert "id" not in data
    assert "pk" not in data
    assert data["public_id"] == str(product.public_id)


# ---------------------------------------------------------------------------
# 12. Output SAFE status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_12_safe_status_structurally_impossible():
    # PLANT: attempt to construct a decision asserting an unqualified SAFE
    # conclusion.
    with pytest.raises(ValueError):
        PrecedentDecision(status="SAFE", note="This formulation is SAFE.")
    with pytest.raises(ValueError):
        PrecedentDecision(status="PASS_WITH_IID_PRECEDENT", note="FDA APPROVED and cleared.")
    # DETECT: no such object was ever constructed (the ValueError is raised
    # at construction time, so nothing partially-built escapes).
    # RESTORE/RERUN: the only allowed PASS note is the required disclaimer.
    from iid_assessment.decisions import REQUIRED_PRECEDENT_NOTE

    decision = PrecedentDecision(status="PASS_WITH_IID_PRECEDENT", note=REQUIRED_PRECEDENT_NOTE)
    assert decision.status == "PASS_WITH_IID_PRECEDENT"
    assert "not an automatic safety" in decision.note.lower()


# ---------------------------------------------------------------------------
# 13. Let Doer approve release
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_13_doer_cannot_approve_release(tenant_a, user_a, doer_membership):
    release = _make_release(status=FDAReleaseStatus.REGISTERED)
    release = lifecycle.submit_for_review(release, user_a)
    client = _client_for(user_a, tenant_a)
    # PLANT: a Doer (import-only role) attempts to approve the release
    # they just submitted, via the real API.
    resp = client.post(
        f"{BASE}/fda-data/releases/{release.public_id}/approve/", data={}, format="json"
    )
    # DETECT: rejected at the permission layer, not merely by segregation
    # of duties inside lifecycle.approve.
    assert resp.status_code == 403
    release.refresh_from_db()
    assert release.status == FDAReleaseStatus.UNDER_REVIEW
    # RESTORE/RERUN: a different, appropriately-permissioned actor (VP,
    # not the importer) can approve it through the same endpoint.
    from django.contrib.auth import get_user_model

    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    User = get_user_model()
    vp_user = User.objects.create_user(email="vp-13@example.com", password="x", full_name="VP")
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp_user)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    vp_client = _client_for(vp_user, tenant_a)
    resp2 = vp_client.post(
        f"{BASE}/fda-data/releases/{release.public_id}/approve/", data={}, format="json"
    )
    assert resp2.status_code == 200
    release.refresh_from_db()
    assert release.status == FDAReleaseStatus.APPROVED


# ---------------------------------------------------------------------------
# 14. Allow assessment snapshot to change after FDA refresh
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_14_snapshot_immutable_after_fda_refresh(tenant_a):
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="e" * 64,
        status=FDAReleaseStatus.ACTIVE,
    )
    snapshot = AssessmentSnapshot.objects.create(
        tenant=tenant_a,
        formulation_component_public_id="11111111-1111-1111-1111-111111111111",
        formulation_version_public_id="22222222-2222-2222-2222-222222222222",
        iid_release_public_id=release.public_id,
        iid_potency_amount=Decimal("50"),
        iid_potency_unit="milligram",
        match_status="EXACT_MATCH",
        decision_status="PASS_WITH_IID_PRECEDENT",
        decision_note="Within selected FDA IID precedent. This is not an automatic "
        "safety determination or regulatory approval.",
    )
    original_potency = snapshot.iid_potency_amount

    # PLANT: simulate an FDA data refresh -- the underlying release is
    # superseded and a new one carries a different potency value entirely.
    release.status = FDAReleaseStatus.SUPERSEDED
    release.save(update_fields=["status"])

    # Then attempt to retroactively "correct" the already-completed
    # snapshot to reflect the refreshed value.
    snapshot.iid_potency_amount = Decimal("999")
    with pytest.raises(ValidationError):
        snapshot.full_clean()

    # DETECT: the snapshot in the database is untouched by the refresh.
    snapshot.refresh_from_db()
    assert snapshot.iid_potency_amount == original_potency
    assert snapshot.decision_status == "PASS_WITH_IID_PRECEDENT"

    # RESTORE/RERUN: a correction requires an explicit new snapshot, never
    # an edit of the old one.
    new_snapshot = AssessmentSnapshot.objects.create(
        tenant=tenant_a,
        formulation_component_public_id=snapshot.formulation_component_public_id,
        formulation_version_public_id=snapshot.formulation_version_public_id,
        iid_release_public_id=release.public_id,
        iid_potency_amount=Decimal("999"),
        iid_potency_unit="milligram",
        match_status="EXACT_MATCH",
        decision_status="REVIEW_REQUIRED",
        decision_note="Re-assessed after FDA data refresh; reviewer confirmation required.",
    )
    assert new_snapshot.pk != snapshot.pk
    assert new_snapshot.iid_potency_amount == Decimal("999")


# ---------------------------------------------------------------------------
# 15. Export formula-injection value without neutralization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_15_formula_injection_value_neutralized_on_export(tenant_a, user_a):
    from authorization.models import MembershipRole, Role
    from fda_data.models import FdaImportRowResult
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    release = _make_release(status=FDAReleaseStatus.ACTIVE)
    FdaImportRowResult.objects.create(
        release=release,
        row_locator="=cmd|' /C calc'!A1",
        result="imported",
        reason_code="+1;DDE(cmd)",
    )
    client = _client_for(user_a, tenant_a)
    # PLANT: a row containing a formula-injection payload starting with
    # "=" and "+" in its exported cells.
    resp = client.get(f"{BASE}/fda-data/releases/{release.public_id}/reconciliation.csv")
    assert resp.status_code == 200
    body = resp.content.decode()
    # DETECT: the raw active-formula prefix never reaches the CSV; every
    # such cell is prefixed with a neutralizing leading apostrophe.
    assert "\n=cmd" not in body
    assert "'=cmd" in body
    assert "'+1;DDE" in body
    # Also verify the underlying helper directly, at the unit level.
    assert _csv_safe_cell("=SUM(A1:A9)") == "'=SUM(A1:A9)"
    assert _csv_safe_cell("+1") == "'+1"
    assert _csv_safe_cell("-1") == "'-1"
    assert _csv_safe_cell("@cmd") == "'@cmd"
    assert _csv_safe_cell("normal text") == "normal text"
    # RESTORE/RERUN: a clean, non-formula value passes through untouched.
    assert _csv_safe_cell("row:1") == "row:1"
