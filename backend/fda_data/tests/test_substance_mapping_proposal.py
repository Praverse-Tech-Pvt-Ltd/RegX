"""
Human-review remediation HR-02: the production substance-mapping
proposal path (POST /fda-data/mappings/substances/proposals/). Before
this endpoint existed, nothing in the shipped application could ever
create a SubstanceSynonymMapping -- see docs/HUMAN_REVIEW_PR5_REMEDIATION.md.
"""

import pytest

from fda_data.models import (
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDIngredient,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)

BASE = "/api/regx/v1"
URL = f"{BASE}/fda-data/mappings/substances/proposals/"


@pytest.fixture
def active_release(db):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="p1" + "0" * 62,
        status=FDAReleaseStatus.ACTIVE,
    )


@pytest.fixture
def superseded_release(db):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID Old",
        official_source_reference="ref-old",
        source_checksum_sha256="p2" + "0" * 62,
        status=FDAReleaseStatus.SUPERSEDED,
    )


@pytest.fixture
def canonical_ingredient(db):
    return IIDIngredient.objects.create(
        canonical_name="Synthetic Proposal Ingredient", normalized_name="PROPOSAL SYNTHETIC"
    )


def _payload(**overrides):
    payload = {
        "raw_ingredient_name": "Synthetic Proposal Brand (raw)",
        "normalized_ingredient_name": "PROPOSAL BRAND SYNTHETIC",
        "mapping_method": SubstanceMappingMethod.MANUAL,
        "reason": "Observed in synthetic IID row without an exact UNII match.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestSubstanceMappingProposalApi:
    def test_authorized_reviewer_creates_proposed_mapping(
        self, api_client_reviewer, active_release, canonical_ingredient
    ):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(
                release_public_id=str(active_release.public_id),
                proposed_ingredient_public_id=str(canonical_ingredient.public_id),
                proposed_unii="SYNPROP01",
            ),
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["status"] == "proposed"
        assert body["mapping_type"] == "substance"
        mapping = SubstanceSynonymMapping.objects.get(public_id=body["public_id"])
        assert mapping.status == SubstanceMappingStatus.PROPOSED
        assert mapping.raw_ingredient_name == "Synthetic Proposal Brand (raw)"

    def test_authorized_doer_creates_proposed_mapping(self, api_client_doer, active_release):
        resp = api_client_doer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_status_cannot_be_supplied_as_approved(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data={
                **_payload(release_public_id=str(active_release.public_id)),
                "status": "approved",
            },
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        # The request explicitly tried to smuggle status=approved; the
        # endpoint has no such input field, so it is silently ignored and
        # the row is created PROPOSED regardless.
        assert body["status"] == "proposed"

    def test_unauthorized_user_receives_403(self, tenant_a, user_a, active_release):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=user_a)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
        resp = client.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 403

    def test_invalid_release_returns_404(self, api_client_reviewer):
        import uuid

        resp = api_client_reviewer.post(
            URL, data=_payload(release_public_id=str(uuid.uuid4())), format="json"
        )
        assert resp.status_code == 404

    def test_superseded_release_rejected(self, api_client_reviewer, superseded_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(superseded_release.public_id)),
            format="json",
        )
        assert resp.status_code == 400
        assert not SubstanceSynonymMapping.objects.filter(
            raw_ingredient_name="Synthetic Proposal Brand (raw)"
        ).exists()

    def test_invalid_proposed_ingredient_returns_400(self, api_client_reviewer, active_release):
        import uuid

        resp = api_client_reviewer.post(
            URL,
            data=_payload(
                release_public_id=str(active_release.public_id),
                proposed_ingredient_public_id=str(uuid.uuid4()),
            ),
            format="json",
        )
        assert resp.status_code == 400

    def test_duplicate_proposal_conflict_handled_deterministically(
        self, api_client_reviewer, active_release
    ):
        first = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert first.status_code == 201
        second = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert second.status_code == 400
        assert (
            SubstanceSynonymMapping.objects.filter(
                raw_ingredient_name="Synthetic Proposal Brand (raw)",
                release=active_release,
                is_current=True,
            ).count()
            == 1
        )

    def test_exact_unii_proposal(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(
                release_public_id=str(active_release.public_id),
                mapping_method=SubstanceMappingMethod.EXACT_UNII,
                raw_unii="SYNU0001",
                proposed_unii="SYNU0001",
            ),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["proposed_unii"] == "SYNU0001"

    def test_exact_cas_proposal(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(
                release_public_id=str(active_release.public_id),
                mapping_method=SubstanceMappingMethod.EXACT_CAS,
                raw_cas_number="1234-56-7",
                proposed_cas_number="1234-56-7",
            ),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["proposed_cas_number"] == "1234-56-7"

    def test_manual_reviewed_synonym_proposal(
        self, api_client_reviewer, active_release, canonical_ingredient
    ):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(
                release_public_id=str(active_release.public_id),
                mapping_method=SubstanceMappingMethod.REVIEWED_SYNONYM,
                proposed_ingredient_public_id=str(canonical_ingredient.public_id),
            ),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["mapping_method"] == SubstanceMappingMethod.REVIEWED_SYNONYM

    def test_ambiguous_proposal_remains_proposed(self, api_client_reviewer, active_release):
        # No proposed_ingredient/UNII/CAS at all -- an ambiguous candidate
        # is still recorded, but only ever as PROPOSED, never auto-decided.
        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "proposed"

    def test_candidate_created_audit_emitted(self, api_client_reviewer, active_release):
        from audit.models import AuditEvent
        from fda_data.audit_events import FdaDataEvent

        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201
        event = AuditEvent.objects.get(resource_id=resp.json()["public_id"])
        assert event.event_type == FdaDataEvent.SUBSTANCE_MAPPING_CANDIDATE_CREATED
        assert "raw_ingredient_name" not in event.payload
        assert event.payload["mapping_type"] == "substance"

    def test_affected_records_linked_after_proposal(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201
        public_id = resp.json()["public_id"]
        affected = api_client_reviewer.get(
            f"{BASE}/fda-data/mappings/{public_id}/affected-records/"
        )
        assert affected.status_code == 200
        assert "results" in affected.json()

    def test_proposal_appears_in_mapping_review_list(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201
        listing = api_client_reviewer.get(f"{BASE}/fda-data/mappings/?type=substance")
        public_ids = {r["public_id"] for r in listing.json()["results"]}
        assert resp.json()["public_id"] in public_ids

    def test_proposal_public_uuid_only(self, api_client_reviewer, active_release):
        resp = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "id" not in body
        assert "pk" not in body

    def test_full_lifecycle_propose_review_approve(
        self, api_client_reviewer, api_client_vp, active_release
    ):
        propose = api_client_reviewer.post(
            URL,
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
        assert propose.status_code == 201
        public_id = propose.json()["public_id"]

        submit = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{public_id}/submit-review/", data={}, format="json"
        )
        assert submit.status_code == 200
        assert submit.json()["status"] == "under_review"

        approve = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{public_id}/approve/", data={}, format="json"
        )
        assert approve.status_code == 200
        assert approve.json()["status"] == "approved"
