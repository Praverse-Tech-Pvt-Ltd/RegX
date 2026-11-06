"""
Human-review remediation HR-01: the authoritative mapping-transition
matrix (fda_data/mapping_transitions.py) closes the segregation-of-duties
bypass where any status transition succeeded regardless of the mapping's
current status. These tests cover the 15 required scenarios for both the
substance type (the richer 5-status lifecycle) and route (representative
of the 4-status legacy types), plus concurrency.
"""

import threading

import pytest
from django.db import connection

from fda_data.mapping_transitions import (
    IllegalMappingTransition,
    MappingAction,
    validate_mapping_transition,
)
from fda_data.models import (
    ControlledRoute,
    MappingDecisionStatus,
    RouteMapping,
    SubstanceMappingMethod,
    SubstanceMappingStatus,
    SubstanceSynonymMapping,
)

BASE = "/api/regx/v1"


@pytest.fixture
def substance_mapping_proposed(db):
    return SubstanceSynonymMapping.objects.create(
        source_dataset="fda_iid",
        raw_ingredient_name="SYNTHETIC-LIFECYCLE",
        normalized_ingredient_name="LIFECYCLE SYNTHETIC",
        mapping_method=SubstanceMappingMethod.MANUAL,
        status=SubstanceMappingStatus.PROPOSED,
    )


@pytest.fixture
def route_mapping_proposed(db):
    route = ControlledRoute.objects.create(
        code="oral-lc", canonical_label="Oral", lifecycle="active"
    )
    return RouteMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value="ORAL-LC",
        controlled_route=route,
        status=MappingDecisionStatus.PROPOSED,
    )


@pytest.mark.django_db
class TestTransitionMatrixUnit:
    """Direct unit tests of validate_mapping_transition() itself."""

    def test_substance_approve_from_proposed_illegal(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.PROPOSED, MappingAction.APPROVE
            )

    def test_substance_approve_from_returned_illegal(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.RETURNED, MappingAction.APPROVE
            )

    def test_substance_approve_from_rejected_illegal(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.REJECTED, MappingAction.APPROVE
            )

    def test_substance_approve_from_under_review_legal(self):
        assert (
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.UNDER_REVIEW, MappingAction.APPROVE
            )
            == SubstanceMappingStatus.APPROVED
        )

    def test_substance_submit_review_from_returned_legal(self):
        assert (
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.RETURNED, MappingAction.SUBMIT_REVIEW
            )
            == SubstanceMappingStatus.UNDER_REVIEW
        )

    def test_substance_submit_review_from_under_review_illegal(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.UNDER_REVIEW, MappingAction.SUBMIT_REVIEW
            )

    def test_substance_reject_from_rejected_illegal(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "substance", SubstanceMappingStatus.REJECTED, MappingAction.REJECT
            )

    def test_substance_no_transition_from_approved(self):
        for action in (
            MappingAction.SUBMIT_REVIEW,
            MappingAction.APPROVE,
            MappingAction.REJECT,
            MappingAction.RETURN,
        ):
            with pytest.raises(IllegalMappingTransition):
                validate_mapping_transition("substance", SubstanceMappingStatus.APPROVED, action)

    def test_route_has_no_return_action(self):
        with pytest.raises(IllegalMappingTransition):
            validate_mapping_transition(
                "route", MappingDecisionStatus.REVIEWED, MappingAction.RETURN
            )


@pytest.mark.django_db
class TestSubstanceLifecycleApi:
    """1-10, 13-14 from Section 8, against the substance type."""

    def test_1_vp_cannot_approve_proposed_mapping(self, api_client_vp, substance_mapping_proposed):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.PROPOSED

    def test_2_vp_cannot_approve_returned_mapping(self, api_client_vp, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.RETURNED
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.RETURNED

    def test_3_vp_cannot_approve_rejected_mapping(self, api_client_vp, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.REJECTED
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.REJECTED

    def test_4_approved_mapping_cannot_transition(self, api_client_vp, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.APPROVED
        substance_mapping_proposed.save(update_fields=["status"])
        for action_url in ("submit-review", "approve", "reject", "return"):
            resp = api_client_vp.post(
                f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/{action_url}/",
                data={},
                format="json",
            )
            assert resp.status_code == 400, action_url
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.APPROVED

    def test_5_proposed_may_submit_for_review(
        self, api_client_reviewer, substance_mapping_proposed
    ):
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/submit-review/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.UNDER_REVIEW

    def test_6_returned_may_resubmit(self, api_client_reviewer, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.RETURNED
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/submit-review/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.UNDER_REVIEW

    def test_7_under_review_may_approve(self, api_client_vp, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.APPROVED

    def test_8_under_review_may_reject(self, api_client_vp, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/reject/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.REJECTED

    def test_9_under_review_may_return(self, api_client_reviewer, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_reviewer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/return/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.RETURNED

    def test_10_rejected_is_terminal(
        self, api_client_vp, api_client_reviewer, substance_mapping_proposed
    ):
        substance_mapping_proposed.status = SubstanceMappingStatus.REJECTED
        substance_mapping_proposed.save(update_fields=["status"])
        for client, action_url in (
            (api_client_reviewer, "submit-review"),
            (api_client_vp, "approve"),
            (api_client_vp, "reject"),
        ):
            resp = client.post(
                f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/{action_url}/",
                data={},
                format="json",
            )
            assert resp.status_code == 400, action_url
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.REJECTED

    def test_11_doer_cannot_approve(self, api_client_doer, substance_mapping_proposed):
        substance_mapping_proposed.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping_proposed.save(update_fields=["status"])
        resp = api_client_doer.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 403

    def test_12_submitter_cannot_self_approve(
        self, api_client_vp, vp_user, substance_mapping_proposed
    ):
        substance_mapping_proposed.status = SubstanceMappingStatus.UNDER_REVIEW
        substance_mapping_proposed.reviewer = vp_user
        substance_mapping_proposed.save(update_fields=["status", "reviewer"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        substance_mapping_proposed.refresh_from_db()
        assert substance_mapping_proposed.status == SubstanceMappingStatus.UNDER_REVIEW

    def test_13_illegal_transition_returns_structured_400(
        self, api_client_vp, substance_mapping_proposed
    ):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert isinstance(body, list | dict)

    def test_14_illegal_transition_produces_no_success_audit_event(
        self, api_client_vp, substance_mapping_proposed
    ):
        from audit.models import AuditEvent

        before = AuditEvent.objects.filter(
            resource_id=str(substance_mapping_proposed.public_id)
        ).count()
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{substance_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        after = AuditEvent.objects.filter(
            resource_id=str(substance_mapping_proposed.public_id)
        ).count()
        assert after == before


@pytest.mark.django_db
class TestRouteLifecycleApi:
    """Representative terminology-mapping (legacy) type coverage."""

    def test_route_approve_from_proposed_illegal(self, api_client_vp, route_mapping_proposed):
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        route_mapping_proposed.refresh_from_db()
        assert route_mapping_proposed.status == MappingDecisionStatus.PROPOSED

    def test_route_approve_from_rejected_illegal(self, api_client_vp, route_mapping_proposed):
        route_mapping_proposed.status = MappingDecisionStatus.REJECTED
        route_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 400
        route_mapping_proposed.refresh_from_db()
        assert route_mapping_proposed.status == MappingDecisionStatus.REJECTED

    def test_route_reviewed_may_approve(self, api_client_vp, route_mapping_proposed):
        route_mapping_proposed.status = MappingDecisionStatus.REVIEWED
        route_mapping_proposed.save(update_fields=["status"])
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/approve/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        route_mapping_proposed.refresh_from_db()
        assert route_mapping_proposed.status == MappingDecisionStatus.APPROVED

    def test_route_reject_directly_from_proposed_allowed(
        self, api_client_vp, route_mapping_proposed
    ):
        # Rejecting an obviously-wrong proposal without forcing a review
        # step first is intentionally allowed (rejection is always safe).
        resp = api_client_vp.post(
            f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/reject/",
            data={},
            format="json",
        )
        assert resp.status_code == 200
        route_mapping_proposed.refresh_from_db()
        assert route_mapping_proposed.status == MappingDecisionStatus.REJECTED


@pytest.mark.django_db(transaction=True)
class TestConcurrentApproval:
    def test_15_concurrent_approval_cannot_create_inconsistent_provenance(self, vp_user, tenant_a):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=vp_user)
        role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
        MembershipRole.objects.get_or_create(membership=membership, role=role)

        mapping = SubstanceSynonymMapping.objects.create(
            source_dataset="fda_iid",
            raw_ingredient_name="SYNTHETIC-CONCURRENCY",
            normalized_ingredient_name="CONCURRENCY SYNTHETIC",
            mapping_method=SubstanceMappingMethod.MANUAL,
            status=SubstanceMappingStatus.UNDER_REVIEW,
        )

        from rest_framework.test import APIClient

        results = []

        def approve_once():
            client = APIClient()
            client.force_authenticate(user=vp_user)
            client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
            resp = client.post(
                f"{BASE}/fda-data/mappings/{mapping.public_id}/approve/",
                data={},
                format="json",
            )
            results.append(resp.status_code)
            connection.close()

        threads = [threading.Thread(target=approve_once) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        mapping.refresh_from_db()
        assert mapping.status == SubstanceMappingStatus.APPROVED
        # select_for_update() serializes the two concurrent attempts:
        # exactly one succeeds (200) and transitions UNDER_REVIEW->APPROVED;
        # the other, once it acquires the lock, sees the already-APPROVED
        # row and is correctly rejected (400, approve has no legal
        # FROM-APPROVED entry) rather than double-applying the transition
        # or corrupting provenance.
        assert sorted(results) == [200, 400]
        assert mapping.approved_by_id == vp_user.id
        assert mapping.approved_at is not None
