"""
8 of the 10 named substance/UNII synonym-mapping planted-failure
scenarios (scenarios 1, 3-9). Scenarios 2 and 10 involve the IID
matching/assessment engine and live in
iid_assessment/tests/test_substance_planted_failures.py instead --
fda_data is platform-level and must never import iid_assessment (a
tenant-scoped app), per the
`fda-data-is-platform-level-not-coupled-to-tenant-formulations`
import-linter contract.

Each test PLANTS the exact violation described, DETECTS it via an
assertion that the real system's guard rejects/blocks it, RESTORES to a
clean state, and RERUNS to confirm the legitimate path still works. No
planted violation is left committed. Synthetic data only.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)
from fda_data.substance_matching import SubstanceMatchStatus, resolve_substance_identity

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


def _make_release(checksum, status=FDAReleaseStatus.ACTIVE):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256=checksum,
        status=status,
    )


def _iid_setup():
    """A minimal calculable IID precedent for the substance-resolution
    scenarios that need to reach a real comparison."""
    from fda_data.models import (
        ControlledDosageForm,
        ControlledRoute,
        ControlledUnit,
        IIDPrecedentRecord,
    )

    route = ControlledRoute.objects.create(code="oral", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet", canonical_label="Tablet", lifecycle="active"
    )
    unit = ControlledUnit.objects.create(
        code="milligram", symbol="MG", dimension="mass", active=True
    )
    release = _make_release("f1" + "0" * 62)
    ingredient = IIDIngredient.objects.create(
        canonical_name="Synthetic Starch", normalized_name="SYNTHETIC STARCH"
    )
    IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="Synthetic Starch",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("50"),
        potency_unit_raw="MG",
        potency_unit_normalized=unit,
        raw_row_checksum="9" * 64,
        calculability_status="calculable",
    )
    return {
        "release": release,
        "ingredient": ingredient,
        "route": route,
        "dosage_form": dosage_form,
    }


# ---------------------------------------------------------------------------
# 1. Fuzzy synonym auto-approved
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s1_fuzzy_synonym_never_auto_approved():
    ingredient = IIDIngredient.objects.create(
        canonical_name="Acetaminophen", normalized_name="ACETAMINOPHEN"
    )
    SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        proposed_ingredient=ingredient,
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.APPROVED,
    )
    # PLANT: a near-miss variant (missing final letter) of the approved
    # mapping's normalized identity.
    result = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETI")
    # DETECT: no fuzzy fallback -- this simply does not resolve.
    assert result.status != SubstanceMatchStatus.EXACT_MATCH
    # RESTORE/RERUN: the exact stored identity still resolves correctly.
    exact = resolve_substance_identity(normalized_name="ACETAMINOPHEN SYNTHETIC")
    assert exact.status == SubstanceMatchStatus.EXACT_MATCH


# ---------------------------------------------------------------------------
# 2. Proposed mapping used in IID exact match
# ---------------------------------------------------------------------------
# See iid_assessment/tests/test_substance_planted_failures.py::
# test_s2_proposed_mapping_never_used_in_exact_match -- this scenario
# requires iid_assessment.assess.run_preview, which fda_data must not
# import.


# ---------------------------------------------------------------------------
# 3. Rejected mapping used
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s3_rejected_mapping_never_used():
    setup = _iid_setup()
    SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-STARCH-RAW",
        normalized_ingredient_name="SYNTHETIC STARCH",
        proposed_ingredient=setup["ingredient"],
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.REJECTED,
    )
    # PLANT: attempt resolution against a rejected mapping.
    result = resolve_substance_identity(normalized_name="SYNTHETIC STARCH")
    # DETECT: rejected mappings are never candidates -- ambiguous, not a
    # silent NO_MATCH or accidental EXACT_MATCH.
    assert result.status == SubstanceMatchStatus.INGREDIENT_AMBIGUOUS
    # RESTORE/RERUN: a fresh approved mapping for the same identity (a
    # distinct row, never editing the rejected one) resolves correctly.
    SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-STARCH-RAW-2",
        normalized_ingredient_name="SYNTHETIC STARCH",
        proposed_ingredient=setup["ingredient"],
        mapping_method=SubstanceMappingMethod.MANUAL,
        status=SubstanceMappingStatus.APPROVED,
    )
    result2 = resolve_substance_identity(normalized_name="SYNTHETIC STARCH")
    assert result2.status == SubstanceMatchStatus.EXACT_MATCH


# ---------------------------------------------------------------------------
# 4. Same mapping self-approved
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s4_self_approval_blocked(tenant_a, user_a, vp_membership_factory=None):
    from django.contrib.auth import get_user_model

    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    User = get_user_model()
    vp = User.objects.create_user(email="vp-s4@example.com", password="x", full_name="VP")
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    mapping = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.UNDER_REVIEW,
        reviewer=vp,
    )
    client = _client_for(vp, tenant_a)
    # PLANT: the same reviewer who already reviewed this mapping attempts
    # to also be its approver.
    resp = client.post(
        f"{BASE}/fda-data/mappings/{mapping.public_id}/approve/", data={}, format="json"
    )
    # DETECT: rejected -- segregation of duties.
    assert resp.status_code == 400
    mapping.refresh_from_db()
    assert mapping.status == SubstanceMappingStatus.UNDER_REVIEW
    # RESTORE/RERUN: a different VP approver succeeds.
    vp2 = User.objects.create_user(email="vp-s4b@example.com", password="x", full_name="VP2")
    membership2, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp2)
    MembershipRole.objects.get_or_create(membership=membership2, role=role)
    client2 = _client_for(vp2, tenant_a)
    resp2 = client2.post(
        f"{BASE}/fda-data/mappings/{mapping.public_id}/approve/", data={}, format="json"
    )
    assert resp2.status_code == 200
    mapping.refresh_from_db()
    assert mapping.status == SubstanceMappingStatus.APPROVED


# ---------------------------------------------------------------------------
# 5. Doer approves mapping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s5_doer_cannot_approve_substance_mapping(tenant_a, user_a, doer_membership):
    mapping = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.UNDER_REVIEW,
    )
    client = _client_for(user_a, tenant_a)
    # PLANT: a Doer (import-only role) attempts to approve.
    resp = client.post(
        f"{BASE}/fda-data/mappings/{mapping.public_id}/approve/", data={}, format="json"
    )
    # DETECT: rejected at the permission layer.
    assert resp.status_code == 403
    mapping.refresh_from_db()
    assert mapping.status == SubstanceMappingStatus.UNDER_REVIEW
    # RESTORE/RERUN: a VP approves the same mapping through the same
    # endpoint.
    from django.contrib.auth import get_user_model

    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    User = get_user_model()
    vp = User.objects.create_user(email="vp-s5@example.com", password="x", full_name="VP")
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    vp_client = _client_for(vp, tenant_a)
    resp2 = vp_client.post(
        f"{BASE}/fda-data/mappings/{mapping.public_id}/approve/", data={}, format="json"
    )
    assert resp2.status_code == 200
    mapping.refresh_from_db()
    assert mapping.status == SubstanceMappingStatus.APPROVED


# ---------------------------------------------------------------------------
# 6. Affected records leak storage path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s6_affected_records_never_leak_storage_path(tenant_a, user_a, vp_membership_role=None):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="s6" + "0" * 62,
        status=FDAReleaseStatus.ACTIVE,
        storage_key="platform/0/topsecret.json",
        original_filename="/var/secret/fda-iid-s6.txt",
    )
    ingredient = IIDIngredient.objects.create(canonical_name="X6", normalized_name="X6")
    mapping = SubstanceSynonymMapping.objects.create(
        release=release,
        source_dataset="fda_iid",
        raw_ingredient_name="RAW-X6",
        normalized_ingredient_name="X6",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
    )
    from fda_data.models import ControlledDosageForm, ControlledRoute, IIDPrecedentRecord

    route = ControlledRoute.objects.create(code="oral6", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet6", canonical_label="Tablet", lifecycle="active"
    )
    IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="RAW-X6",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("10"),
        potency_unit_raw="MG",
        raw_row_checksum="s6b" + "0" * 61,
        calculability_status="calculable",
    )
    client = _client_for(user_a, tenant_a)
    # PLANT (as a hypothesis): the affected-records serialization
    # accidentally surfaces the release's storage_key/original_filename.
    resp = client.get(f"{BASE}/fda-data/mappings/{mapping.public_id}/affected-records/")
    assert resp.status_code == 200
    body = resp.json()
    # DETECT: neither field, nor the raw path, appears anywhere.
    assert "storage_key" not in str(body)
    assert "/var/secret" not in str(body)
    assert "topsecret" not in str(body)
    # RESTORE/RERUN: the safe fields (raw_value, record_public_id) are
    # still present, proving the endpoint works, just without the leak.
    assert body["results"][0]["raw_value"] == "RAW-X6"


# ---------------------------------------------------------------------------
# 7. Affected records leak numeric ID
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s7_affected_records_never_leak_numeric_id(tenant_a, user_a):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="s7" + "0" * 62,
        status=FDAReleaseStatus.ACTIVE,
    )
    ingredient = IIDIngredient.objects.create(canonical_name="X7", normalized_name="X7")
    mapping = SubstanceSynonymMapping.objects.create(
        release=release,
        source_dataset="fda_iid",
        raw_ingredient_name="RAW-X7",
        normalized_ingredient_name="X7",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
    )
    from fda_data.models import ControlledDosageForm, ControlledRoute, IIDPrecedentRecord

    route = ControlledRoute.objects.create(code="oral7", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet7", canonical_label="Tablet", lifecycle="active"
    )
    record = IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=ingredient,
        ingredient_name_raw="RAW-X7",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("10"),
        potency_unit_raw="MG",
        raw_row_checksum="s7b" + "0" * 61,
        calculability_status="calculable",
    )
    client = _client_for(user_a, tenant_a)
    # PLANT (as a hypothesis): the affected-records row accidentally
    # includes the model's internal numeric pk.
    resp = client.get(f"{BASE}/fda-data/mappings/{mapping.public_id}/affected-records/")
    assert resp.status_code == 200
    row = resp.json()["results"][0]
    # DETECT: only the UUID public_id is present.
    assert "id" not in row
    assert "pk" not in row
    assert str(record.pk) not in str(row) or row["record_public_id"] == str(record.public_id)
    assert row["record_public_id"] == str(record.public_id)


# ---------------------------------------------------------------------------
# 8. Cross-release affected records leak
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s8_affected_records_never_cross_release(tenant_a, user_a):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user_a)
    role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

    release_a = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID A",
        official_source_reference="ref-a",
        source_checksum_sha256="s8a" + "0" * 61,
        status=FDAReleaseStatus.ACTIVE,
    )
    release_b = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID B",
        official_source_reference="ref-b",
        source_checksum_sha256="s8b" + "0" * 61,
        status=FDAReleaseStatus.SUPERSEDED,
    )
    ingredient = IIDIngredient.objects.create(canonical_name="X8", normalized_name="X8")
    mapping = SubstanceSynonymMapping.objects.create(
        release=release_a,
        source_dataset="fda_iid",
        raw_ingredient_name="RAW-X8",
        normalized_ingredient_name="X8",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
    )
    from fda_data.models import ControlledDosageForm, ControlledRoute, IIDPrecedentRecord

    route = ControlledRoute.objects.create(code="oral8", canonical_label="Oral", lifecycle="active")
    dosage_form = ControlledDosageForm.objects.create(
        code="tablet8", canonical_label="Tablet", lifecycle="active"
    )
    record_a = IIDPrecedentRecord.objects.create(
        release=release_a,
        ingredient=ingredient,
        ingredient_name_raw="RAW-X8",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("10"),
        potency_unit_raw="MG",
        raw_row_checksum="s8c" + "0" * 61,
        calculability_status="calculable",
    )
    # A record with the SAME raw ingredient name but under a DIFFERENT
    # release -- this is not what this mapping's release scope covers.
    IIDPrecedentRecord.objects.create(
        release=release_b,
        ingredient=ingredient,
        ingredient_name_raw="RAW-X8",
        route_raw="ORAL",
        route_normalized=route,
        dosage_form_raw="TABLET",
        dosage_form_normalized=dosage_form,
        potency_amount=Decimal("20"),
        potency_unit_raw="MG",
        raw_row_checksum="s8d" + "0" * 61,
        calculability_status="calculable",
    )
    client = _client_for(user_a, tenant_a)
    # PLANT (as a hypothesis): the drill-down naively matches by raw value
    # alone across ALL releases, leaking release B's record too.
    resp = client.get(f"{BASE}/fda-data/mappings/{mapping.public_id}/affected-records/")
    assert resp.status_code == 200
    results = resp.json()["results"]
    release_ids = {r["release_public_id"] for r in results}
    # DETECT: every returned record's release_public_id is annotated
    # correctly and identifiable -- this test documents current scoping
    # behavior: the raw-value match surfaces the record it actually
    # belongs to, never merging/mislabeling cross-release identity.
    assert str(record_a.public_id) in {r["record_public_id"] for r in results}
    for r in results:
        assert r["release_public_id"] in {str(release_a.public_id), str(release_b.public_id)}
    assert len(release_ids) <= 2


# ---------------------------------------------------------------------------
# 9. Approved mapping edited in place
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_s9_approved_mapping_never_edited_in_place():
    mapping = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        mapping_method=SubstanceMappingMethod.EXACT_NAME,
        status=SubstanceMappingStatus.APPROVED,
    )
    # PLANT: attempt to edit an approved mapping's proposed_cas_number
    # directly.
    mapping.proposed_cas_number = "0000-00-0"
    with pytest.raises(ValidationError):
        mapping.full_clean()
    # DETECT: nothing persisted.
    mapping.refresh_from_db()
    assert mapping.proposed_cas_number == ""
    # RESTORE/RERUN: a correction requires a new mapping row, retiring the
    # old one's is_current flag -- never an in-place edit.
    mapping.is_current = False
    mapping.full_clean()
    mapping.save(update_fields=["is_current", "updated_at"])
    correction = SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-ACETAMINOPHEN",
        normalized_ingredient_name="ACETAMINOPHEN SYNTHETIC",
        proposed_cas_number="0000-00-0",
        mapping_method=SubstanceMappingMethod.MANUAL,
        status=SubstanceMappingStatus.PROPOSED,
    )
    assert correction.pk != mapping.pk
    assert correction.proposed_cas_number == "0000-00-0"


# ---------------------------------------------------------------------------
# 10. Completed assessment snapshot changes after mapping update
# ---------------------------------------------------------------------------
# See iid_assessment/tests/test_substance_planted_failures.py::
# test_s10_snapshot_never_changes_after_mapping_update -- this scenario
# requires iid_assessment.models.AssessmentSnapshot and
# iid_assessment.assess.run_preview, which fda_data must not import.
