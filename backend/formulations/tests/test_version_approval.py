"""Option A: formulation version review and approval (owner decision 2026-11-18;
docs/FORMULATION_APPROVAL_OPTIONS.md), through the real API.

Before: no endpoint or screen could approve a formulation version, so a newly
created formulation could never have the IIG checklist run on it (QA-01), and
components could be added to an approved version through the API.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, InternalError, ProgrammingError, transaction
from rest_framework.test import APIClient

from audit.models import AuditEvent
from formulations.models import (
    DosingRegimen,
    FormulationComponent,
    FormulationStatus,
    FormulationVersion,
)
from formulations.tests.conftest import _membership_with_role

BASE = "/api/regx/v1/formulations"
pytestmark = pytest.mark.django_db
DB_REFUSED = (ProgrammingError, InternalError, IntegrityError)


def _user(email):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=email
    )


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def people(tenant_a):
    """A Doer, a Reviewer, two VPs, and a user who is both Doer and VP."""
    out = {}
    for name, roles in {
        "doer": ["doer"],
        "reviewer": ["reviewer"],
        "vp": ["vp"],
        "vp2": ["vp"],
        "doer_vp": ["doer", "vp"],
    }.items():
        user = _user(f"{name}@approval.test")
        for role in roles:
            _membership_with_role(tenant_a, user, role)
        out[name] = (user, _client(user, tenant_a))
    return out


def _draft(client, *, components=1, code="APR-1"):
    product = client.post(
        f"{BASE}/products/",
        {
            "product_code": code,
            "proposed_product_name": "P",
            "active_ingredient": "X",
            "dosage_form": "TABLET",
        },
        format="json",
    ).json()
    version = client.post(
        f"{BASE}/products/{product['public_id']}/versions/",
        {
            "total_dosage_unit_weight": "250",
            "total_dosage_unit_weight_unit": "mg",
            "maximum_dosage_units_per_day": "4",
        },
        format="json",
    ).json()
    for i in range(components):
        resp = client.post(
            f"{BASE}/versions/{version['public_id']}/components/",
            {
                "component_type": "inactive",
                "ingredient_name": f"EXCIPIENT {i}",
                "quantity_per_dosage_unit": "10",
                "quantity_unit": "mg",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.json()
    return product, version["public_id"]


def _post(client, vid, action, body=None):
    return client.post(f"{BASE}/versions/{vid}/{action}/", body or {}, format="json")


def _status(vid):
    return FormulationVersion.objects.get(public_id=vid).status


class TestTheFlow:
    def test_submit_return_resubmit_approve(self, people):
        doer, reviewer, vp = people["doer"][1], people["reviewer"][1], people["vp"][1]
        _, vid = _draft(doer)
        assert _post(doer, vid, "submit-review").json()["status"] == "under_review"
        resp = _post(reviewer, vid, "return", {"reason": "Add the lubricant grade."})
        assert (resp.status_code, resp.json()["status"]) == (200, "draft")
        assert resp.json()["return_reason"] == "Add the lubricant grade."
        assert _post(doer, vid, "submit-review").status_code == 200
        resp = _post(vp, vid, "approve", {"note": "Composition reviewed (internal)."})
        assert (resp.status_code, resp.json()["status"]) == (200, "approved")
        body = resp.json()
        assert body["approved_by_email"] == "vp@approval.test"
        assert body["submitted_by_email"] == "doer@approval.test"
        assert [h["event"] for h in body["history"]] == [
            "created",
            "submitted for review",
            "returned to draft",
            "submitted for review",
            "approved (internal)",
        ]

    def test_every_step_is_audited(self, people):
        doer, vp = people["doer"][1], people["vp"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        _post(vp, vid, "approve", {"note": "ok"})
        events = list(
            AuditEvent.objects.filter(resource_id=vid).values_list("event_type", "actor_email")
        )
        assert ("formulations.version.submitted_for_review", "doer@approval.test") in events
        assert ("formulations.version.approved", "vp@approval.test") in events

    def test_reviewer_can_reject_with_a_reason(self, people):
        doer, reviewer = people["doer"][1], people["reviewer"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        assert _post(reviewer, vid, "reject", {"reason": " "}).status_code == 400
        resp = _post(reviewer, vid, "reject", {"reason": "Wrong product."})
        assert (resp.status_code, resp.json()["status"]) == (200, "retired")
        assert AuditEvent.objects.filter(
            resource_id=vid, event_type="formulations.version.rejected"
        ).exists()

    def test_approving_a_newer_version_supersedes_the_older(self, people):
        doer, vp = people["doer"][1], people["vp"][1]
        product, v1 = _draft(doer)
        _post(doer, v1, "submit-review")
        _post(vp, v1, "approve", {"note": "v1"})
        v2 = doer.post(
            f"{BASE}/products/{product['public_id']}/versions/",
            {"total_dosage_unit_weight": "250", "total_dosage_unit_weight_unit": "mg"},
            format="json",
        ).json()["public_id"]
        doer.post(
            f"{BASE}/versions/{v2}/components/",
            {
                "component_type": "inactive",
                "ingredient_name": "E",
                "quantity_per_dosage_unit": "5",
                "quantity_unit": "mg",
            },
            format="json",
        )
        _post(doer, v2, "submit-review")
        _post(vp, v2, "approve", {"note": "v2"})
        assert (_status(v1), _status(v2)) == ("superseded", "approved")


class TestRefusals:
    def test_an_empty_version_cannot_be_submitted(self, people):
        doer = people["doer"][1]
        _, vid = _draft(doer, components=0)
        resp = _post(doer, vid, "submit-review")
        assert (resp.status_code, resp.json()["error_code"]) == (400, "incomplete_version")

    def test_return_needs_a_reason_and_approve_needs_a_note(self, people):
        doer, reviewer, vp = people["doer"][1], people["reviewer"][1], people["vp"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        assert (
            _post(reviewer, vid, "return", {"reason": ""}).json()["error_code"] == "reason_required"
        )
        assert _post(vp, vid, "approve", {"note": ""}).json()["error_code"] == "note_required"
        assert _status(vid) == "under_review"

    def test_doer_and_reviewer_cannot_approve(self, people):
        doer, reviewer = people["doer"][1], people["reviewer"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        assert _post(doer, vid, "approve", {"note": "x"}).status_code == 403
        assert _post(reviewer, vid, "approve", {"note": "x"}).status_code == 403
        assert _status(vid) == "under_review"

    def test_the_doer_cannot_return_or_reject(self, people):
        doer = people["doer"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        assert _post(doer, vid, "return", {"reason": "x"}).status_code == 403
        assert _post(doer, vid, "reject", {"reason": "x"}).status_code == 403

    def test_a_vp_who_created_the_version_cannot_approve_it(self, people):
        doer_vp, vp = people["doer_vp"][1], people["vp"][1]
        _, vid = _draft(doer_vp, code="APR-SELF")
        _post(doer_vp, vid, "submit-review")
        resp = _post(doer_vp, vid, "approve", {"note": "mine"})
        assert (resp.status_code, resp.json()["error_code"]) == (403, "self_approval_forbidden")
        assert _post(vp, vid, "approve", {"note": "someone else"}).status_code == 200

    def test_a_vp_who_submitted_the_version_cannot_approve_it(self, people):
        doer, doer_vp = people["doer"][1], people["doer_vp"][1]
        _, vid = _draft(doer, code="APR-SUB")  # created by the Doer
        _post(doer_vp, vid, "submit-review")  # submitted by the Doer+VP
        resp = _post(doer_vp, vid, "approve", {"note": "submitted it myself"})
        assert (resp.status_code, resp.json()["error_code"]) == (403, "self_approval_forbidden")

    def test_only_a_draft_can_be_submitted(self, people):
        doer, vp = people["doer"][1], people["vp"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        assert _post(doer, vid, "submit-review").status_code == 409
        _post(vp, vid, "approve", {"note": "ok"})
        assert _post(vp, vid, "approve", {"note": "again"}).status_code == 409

    @pytest.mark.parametrize("stage", ["under_review", "approved"])
    def test_components_and_regimens_cannot_be_added_unless_draft(self, people, stage):
        doer, vp = people["doer"][1], people["vp"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        if stage == "approved":
            _post(vp, vid, "approve", {"note": "ok"})
        resp = doer.post(
            f"{BASE}/versions/{vid}/components/",
            {
                "component_type": "inactive",
                "ingredient_name": "LATE",
                "quantity_per_dosage_unit": "1",
                "quantity_unit": "mg",
            },
            format="json",
        )
        assert resp.status_code == 400 and "version_not_draft" in str(resp.json())
        resp = doer.post(
            f"{BASE}/versions/{vid}/dosing-regimens/",
            {
                "units_per_administration": "1",
                "administrations_per_day": "2",
                "maximum_units_per_day": "2",
            },
            format="json",
        )
        assert resp.status_code == 400


class TestButtonsFollowPermissions:
    def test_available_actions_per_role(self, people):
        doer, reviewer, vp, doer_vp = (people[k][1] for k in ("doer", "reviewer", "vp", "doer_vp"))
        _, vid = _draft(doer)
        assert doer.get(f"{BASE}/versions/{vid}/").json()["available_actions"] == ["submit"]
        assert reviewer.get(f"{BASE}/versions/{vid}/").json()["available_actions"] == []
        _post(doer, vid, "submit-review")
        assert doer.get(f"{BASE}/versions/{vid}/").json()["available_actions"] == []
        assert reviewer.get(f"{BASE}/versions/{vid}/").json()["available_actions"] == [
            "return",
            "reject",
        ]
        assert vp.get(f"{BASE}/versions/{vid}/").json()["available_actions"] == [
            "return",
            "reject",
            "approve",
        ]
        _, own = _draft(doer_vp, code="APR-OWN")
        _post(doer_vp, own, "submit-review")
        assert "approve" not in doer_vp.get(f"{BASE}/versions/{own}/").json()["available_actions"]


class TestMfaGate:
    def test_a_vp_without_mfa_cannot_approve(self, people, tenant_a):
        doer = people["doer"][1]
        vp_user = people["vp"][0]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        session_client = APIClient()
        session_client.force_login(vp_user)  # the MFA middleware reads the session user
        session_client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
        resp = session_client.post(f"{BASE}/versions/{vid}/approve/", {"note": "ok"}, format="json")
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "mfa_enrolment_required"
        assert _status(vid) == "under_review"


class TestTheDatabaseRefuses:
    @pytest.fixture
    def approved(self, people):
        doer, vp = people["doer"][1], people["vp"][1]
        _, vid = _draft(doer)
        _post(doer, vid, "submit-review")
        _post(vp, vid, "approve", {"note": "ok"})
        return FormulationVersion.objects.get(public_id=vid)

    def test_changing_an_approved_version(self, approved):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationVersion.objects.filter(pk=approved.pk).update(
                maximum_dosage_units_per_day=Decimal("9")
            )

    def test_moving_an_approved_version_back_to_draft(self, approved):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationVersion.objects.filter(pk=approved.pk).update(status=FormulationStatus.DRAFT)

    def test_adding_changing_or_deleting_a_component(self, approved):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationComponent.objects.create(
                formulation_version=approved,
                component_type="inactive",
                ingredient_name="X",
                quantity_per_dosage_unit=Decimal("1"),
                quantity_unit="mg",
            )
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationComponent.objects.filter(formulation_version=approved).update(
                quantity_per_dosage_unit=Decimal("99")
            )
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationComponent.objects.filter(formulation_version=approved).delete()

    def test_adding_a_dosing_regimen(self, approved):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            DosingRegimen.objects.create(
                formulation_version=approved,
                units_per_administration=Decimal("1"),
                administrations_per_day=Decimal("1"),
                maximum_units_per_day=Decimal("1"),
            )

    def test_deleting_an_approved_version(self, approved):
        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationVersion.objects.filter(pk=approved.pk).delete()

    def test_self_approval_even_by_a_direct_update(self, people):
        doer_vp_user, doer_vp = people["doer_vp"]
        _, vid = _draft(doer_vp, code="APR-DB")
        _post(doer_vp, vid, "submit-review")
        from django.utils import timezone

        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationVersion.objects.filter(public_id=vid).update(
                status=FormulationStatus.APPROVED,
                approved_by=doer_vp_user,
                approved_at=timezone.now(),
                approval_note="bypass",
            )

    def test_a_draft_cannot_jump_to_approved(self, people):
        _, vid = _draft(people["doer"][1], code="APR-JUMP")
        from django.utils import timezone

        with pytest.raises(DB_REFUSED), transaction.atomic():
            FormulationVersion.objects.filter(public_id=vid).update(
                status=FormulationStatus.APPROVED,
                approved_by=people["vp"][0],
                approved_at=timezone.now(),
                approval_note="skip review",
            )
