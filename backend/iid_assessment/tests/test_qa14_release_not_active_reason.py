"""QA-14 (QA_CODEX_REPORT.md): a preview against a superseded IID release gave a misleading reason.

The exact row existed in that release, but matching only uses an approved or
active release, so the preview answered "No IID record with this route and dosage
form". The reason now says the chosen release is not usable and names the active
release to choose instead.
"""

import pytest

from fda_data.models import FDADataSourceRelease, FDAReleaseStatus, IIDPrecedentRecord

from .test_amount_limits_preview import _preview


def _copy_release(setup, status, checksum):
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref (older copy)",
        source_checksum_sha256=checksum * 64,
        status=status,
    )
    record = setup["record"]
    IIDPrecedentRecord.objects.create(
        release=release,
        ingredient=record.ingredient,
        ingredient_name_raw=record.ingredient_name_raw,
        route_raw=record.route_raw,
        route_normalized=record.route_normalized,
        dosage_form_raw=record.dosage_form_raw,
        dosage_form_normalized=record.dosage_form_normalized,
        potency_amount=record.potency_amount,
        potency_unit_raw=record.potency_unit_raw,
        potency_expression=record.potency_expression,
        raw_row_checksum="2" * 64,
        calculability_status=record.calculability_status,
    )
    return release


@pytest.mark.django_db
class TestReleaseNotActive:
    @pytest.mark.parametrize(
        ("status", "word"),
        [(FDAReleaseStatus.SUPERSEDED, "superseded"), (FDAReleaseStatus.REGISTERED, "registered")],
    )
    def test_the_reason_names_the_release_problem(
        self, api_client_doer, active_iid_setup, status, word
    ):
        old = _copy_release(active_iid_setup, status, "a" if word == "superseded" else "b")
        resp = _preview(
            api_client_doer,
            active_iid_setup,
            "10",
            "mg",
            active_release_public_id=str(old.public_id),
        )
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["match_reason_code"] == "RELEASE_NOT_ACTIVE"
        assert word in body["decision_note"]
        assert str(active_iid_setup["release"].public_id) in body["decision_note"]
        assert body["calculations"].get("potency_comparison") is None

    def test_the_active_release_still_compares(self, api_client_doer, active_iid_setup):
        _copy_release(active_iid_setup, FDAReleaseStatus.SUPERSEDED, "c")
        body = _preview(api_client_doer, active_iid_setup, "10", "mg").json()
        assert body["match_status"] == "EXACT_MATCH"
        assert body["calculations"]["potency_comparison"]["comparable"] is True
