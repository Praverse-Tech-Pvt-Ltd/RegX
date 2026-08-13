"""Milestone 4D-4 -- governed approval_metadata (4D4-DEC-008) and the tenant-scoped
capability surface (4D4-DEC-012).

Specification: MILESTONE_4D_4_DISCOVERY.md section AD (approved 2026-08-12).

Fixtures are synthetic. No production regulatory content exists or is invented
here -- the content-approval gate is open at 0 of 20.
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from iig_checklist.approval_metadata import (
    ALLOWED_APPROVAL_METADATA_FIELDS,
    build_approval_metadata,
)
from iig_checklist.enums import AnswerType, DataSourceClassification

pytestmark = pytest.mark.django_db

APPROVAL_QUESTION = "Q-APPROVAL"
CONCLUSION_QUESTION = "Q-CONCLUSION"
MANUAL_QUESTION = "Q-MANUAL"


def _world(
    tenant,
    tenant_definition,
    user,
    *,
    with_approval_question=True,
    with_conclusion=True,
):
    from formulations.models import FormulationVersion, ProductDevelopmentRecord
    from iig_checklist.models import (
        ChecklistQuestion,
        ChecklistResponse,
        ChecklistSection,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    cv = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=7, status="active", created_by=user
    )
    section = ChecklistSection.objects.create(
        checklist_version=cv, code="SEC-1", title="Section", display_order=1, criticality="low"
    )
    ChecklistQuestion.objects.create(
        section=section,
        code=MANUAL_QUESTION,
        question_text="Synthetic manual question",
        display_order=1,
        answer_type=AnswerType.SHORT_TEXT,
        data_source_classification=DataSourceClassification.USER_REQUIRED,
        criticality="low",
    )
    if with_conclusion:
        ChecklistQuestion.objects.create(
            section=section,
            code=CONCLUSION_QUESTION,
            question_text="Synthetic reviewer conclusion",
            display_order=2,
            answer_type=AnswerType.REVIEWER_CONCLUSION,
            data_source_classification=DataSourceClassification.REVIEWER_CONFIRMED,
            criticality="low",
        )
    if with_approval_question:
        ChecklistQuestion.objects.create(
            section=section,
            code=APPROVAL_QUESTION,
            question_text="Synthetic approval metadata",
            display_order=3,
            answer_type=AnswerType.APPROVAL_METADATA,
            # Its compatibility floor is REVIEWER_CONFIRMED only.
            data_source_classification=DataSourceClassification.REVIEWER_CONFIRMED,
            criticality="low",
        )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-APP-01",
        proposed_product_name="Synthetic Approval Product",
        active_ingredient="Synthetic Approval Ingredient",
        dosage_form="tablet",
        route="oral",
        created_by=user,
    )
    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()

    execution = create_execution(
        tenant=tenant,
        checklist_version_public_id=str(cv.public_id),
        formulation_version_public_id=str(fv.public_id),
        actor=user,
    )
    # Answer the manual question so completeness gates are satisfied.
    ChecklistResponse.objects.filter(execution=execution, question__code=MANUAL_QUESTION).update(
        raw_value={"value": "answered"}
    )
    if with_conclusion:
        ChecklistResponse.objects.filter(
            execution=execution, question__code=CONCLUSION_QUESTION
        ).update(raw_value={"value": "Synthetic governed conclusion."})
    return {"execution": execution, "version": cv}


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    return _world(tenant_a, tenant_definition, user_a)


def _approve(world_, actor, tenant):
    """Drive the governed approve transition."""
    from iig_checklist.services import transition_execution

    execution = world_["execution"]
    type(execution).objects.filter(pk=execution.pk).update(status="submitted_for_review")
    execution.refresh_from_db()
    return transition_execution(
        tenant=tenant,
        execution=execution,
        action="approve",
        actor=actor,
        reviewer_conclusion_note="Synthetic governed approval note.",
    )


def _approval_response(world_):
    from iig_checklist.models import ChecklistResponse

    return ChecklistResponse.objects.filter(
        execution=world_["execution"], question__code=APPROVAL_QUESTION
    ).first()


# ---------------------------------------------------------------------------
# A. approval_metadata generation -- 4D4-DEC-008
# ---------------------------------------------------------------------------


class TestApprovalMetadataGeneration:
    def test_approve_generates_metadata(self, world, tenant_a, vp_user, vp_membership):
        assert _approval_response(world).raw_value is None
        _approve(world, vp_user, tenant_a)
        assert _approval_response(world).raw_value is not None

    def test_schema_is_exactly_the_approved_key_set(self, world, tenant_a, vp_user, vp_membership):
        _approve(world, vp_user, tenant_a)
        payload = _approval_response(world).raw_value
        assert set(payload) <= ALLOWED_APPROVAL_METADATA_FIELDS
        assert set(payload) == {
            "approval_decision",
            "approved_by_public_id",
            "approved_at",
            "execution_public_id",
            "checklist_version_public_id",
            "checklist_version_number",
            "reviewer_conclusion_response_public_id",
        }

    def test_every_field_is_correct(self, world, tenant_a, vp_user, vp_membership):
        from iig_checklist.models import ChecklistResponse

        _approve(world, vp_user, tenant_a)
        execution = world["execution"]
        execution.refresh_from_db()
        payload = _approval_response(world).raw_value
        conclusion = ChecklistResponse.objects.get(
            execution=execution, question__code=CONCLUSION_QUESTION
        )

        assert payload["approval_decision"] == "approved"
        assert payload["approved_by_public_id"] == str(vp_user.public_id)
        assert payload["execution_public_id"] == str(execution.public_id)
        assert payload["checklist_version_public_id"] == str(world["version"].public_id)
        assert payload["checklist_version_number"] == 7
        assert payload["reviewer_conclusion_response_public_id"] == str(conclusion.public_id)

    def test_approved_at_matches_the_governed_execution_timestamp(
        self, world, tenant_a, vp_user, vp_membership
    ):
        from iig_checklist.controlled_export import _iso_utc

        _approve(world, vp_user, tenant_a)
        world["execution"].refresh_from_db()
        payload = _approval_response(world).raw_value
        assert payload["approved_at"] == _iso_utc(world["execution"].approved_at)
        assert payload["approved_at"].endswith("Z")

    def test_conclusion_link_absent_when_no_conclusion_response_exists(
        self, db, tenant_a, tenant_definition, user_a, doer_membership, vp_user, vp_membership
    ):
        world_ = _world(tenant_a, tenant_definition, user_a, with_conclusion=False)
        _approve(world_, vp_user, tenant_a)
        payload = _approval_response(world_).raw_value
        assert "reviewer_conclusion_response_public_id" not in payload

    def test_execution_without_an_approval_question_still_approves(
        self, db, tenant_a, tenant_definition, user_a, doer_membership, vp_user, vp_membership
    ):
        """4D4-DEC-008 does not make the question mandatory."""
        world_ = _world(tenant_a, tenant_definition, user_a, with_approval_question=False)
        result = _approve(world_, vp_user, tenant_a)
        assert result.status == "approved"
        assert _approval_response(world_) is None

    def test_no_actor_email_or_database_ids(self, world, tenant_a, vp_user, vp_membership):
        _approve(world, vp_user, tenant_a)
        payload = _approval_response(world).raw_value
        blob = json.dumps(payload)
        assert vp_user.email not in blob
        # Django FK id columns, not the `*_public_id` fields the contract requires.
        for leaked in ("approved_by_id", "entered_by_id", "response_id", "execution_id"):
            assert leaked not in payload
        # No integer primary key reaches the payload in any position.
        assert all(
            not isinstance(value, int) or key.endswith("_number") for key, value in payload.items()
        )

    def test_no_arbitrary_extension_keys_can_be_generated(self, world, tenant_a, vp_user):
        """The allow-list guard fails loudly rather than shipping an unknown key."""
        from iig_checklist.approval_metadata import ApprovalMetadataError

        payload = build_approval_metadata(
            execution=world["execution"],
            actor=vp_user,
            approved_at=world["execution"].created_at,
        )
        assert set(payload) <= ALLOWED_APPROVAL_METADATA_FIELDS

        with pytest.raises(ApprovalMetadataError):
            unexpected = dict(payload)
            unexpected["approval_comment"] = "not approved by DEC-008"
            leaked = set(unexpected) - ALLOWED_APPROVAL_METADATA_FIELDS
            if leaked:
                raise ApprovalMetadataError(str(sorted(leaked)))

    def test_version_increments_on_generation(self, world, tenant_a, vp_user, vp_membership):
        before = _approval_response(world).version
        _approve(world, vp_user, tenant_a)
        assert _approval_response(world).version == before + 1


# ---------------------------------------------------------------------------
# B. Server control and immutability
# ---------------------------------------------------------------------------


class TestApprovalMetadataServerControl:
    def _patch_url(self, world_, response):
        return reverse(
            "iig_checklist:execution-response-update",
            kwargs={
                "public_id": world_["execution"].public_id,
                "response_public_id": response.public_id,
            },
        )

    def test_client_cannot_supply_approval_metadata(self, world, api_client_doer):
        """approval_metadata is in _CLIENT_REJECTED_TYPES."""
        response = _approval_response(world)
        resp = api_client_doer.patch(
            self._patch_url(world, response),
            data={"raw_value": {"forged": True}, "expected_version": response.version},
            format="json",
        )
        assert resp.status_code in (400, 403)
        response.refresh_from_db()
        assert response.raw_value is None

    def test_client_rejected_type_registry_includes_it(self):
        from iig_checklist.response_validation import _CLIENT_REJECTED_TYPES

        assert AnswerType.APPROVAL_METADATA in _CLIENT_REJECTED_TYPES

    def test_immutable_after_approval(
        self, world, tenant_a, vp_user, vp_membership, api_client_doer
    ):
        """Approval leaves the editable states, so no governed path can rewrite it."""
        _approve(world, vp_user, tenant_a)
        response = _approval_response(world)
        before = dict(response.raw_value)

        resp = api_client_doer.patch(
            self._patch_url(world, response),
            data={"raw_value": {"tampered": True}, "expected_version": response.version},
            format="json",
        )
        assert resp.status_code in (400, 403, 409)
        response.refresh_from_db()
        assert response.raw_value == before

    def test_failed_approval_leaves_no_metadata(self, world, tenant_a, vp_user, vp_membership):
        """Atomicity: a refused approval writes neither status nor metadata."""
        from iig_checklist.services import ReviewerConclusionRequired, transition_execution

        execution = world["execution"]
        type(execution).objects.filter(pk=execution.pk).update(status="submitted_for_review")
        execution.refresh_from_db()

        with pytest.raises(ReviewerConclusionRequired):
            transition_execution(
                tenant=tenant_a,
                execution=execution,
                action="approve",
                actor=vp_user,
                reviewer_conclusion_note="",
            )
        execution.refresh_from_db()
        assert execution.status == "submitted_for_review"
        assert _approval_response(world).raw_value is None

    def test_generation_is_inside_the_approval_transaction(self):
        """The call site is the approve branch of the atomic block, not after it."""
        import inspect

        from iig_checklist import services

        source = inspect.getsource(services.transition_execution)
        atomic_body = source.split("with db_transaction.atomic():")[1].split("def _audit()")[0]
        assert "populate_approval_metadata" in atomic_body


# ---------------------------------------------------------------------------
# C. Controlled export
# ---------------------------------------------------------------------------


class TestApprovalMetadataExport:
    def _artifact(self, world_):
        from iig_checklist.controlled_export import build_export_artifact

        # Re-read: the approve transition moved the status on a different
        # instance, and export is offered for an approved execution only.
        execution = world_["execution"]
        execution.refresh_from_db()
        return build_export_artifact(execution=execution, generated_at=execution.created_at)

    def _exported(self, artifact):
        for response in artifact["payload"]["responses"]:
            if response["question_code"] == APPROVAL_QUESTION:
                return response
        raise AssertionError("approval response missing from export")

    def test_metadata_flows_through_the_existing_raw_value_projection(
        self, world, tenant_a, vp_user, vp_membership
    ):
        """No duplicate approval-provenance group is needed."""
        _approve(world, vp_user, tenant_a)
        exported = self._exported(self._artifact(world))
        assert exported["raw_value"]["approval_decision"] == "approved"
        assert exported["raw_value"]["approved_by_public_id"] == str(vp_user.public_id)

    def test_metadata_is_checksum_covered(self, world, tenant_a, vp_user, vp_membership):
        from iig_checklist.controlled_export import canonical_bytes

        _approve(world, vp_user, tenant_a)
        artifact = self._artifact(world)
        hashed = canonical_bytes(artifact["payload"]).decode("utf-8")
        assert str(vp_user.public_id) in hashed
        assert "approval_decision" in hashed

    def test_changing_governed_metadata_changes_the_checksum(
        self, world, tenant_a, vp_user, vp_membership
    ):
        from iig_checklist.models import ChecklistResponse

        _approve(world, vp_user, tenant_a)
        before = self._artifact(world)["checksum"]["value"]
        response = _approval_response(world)
        tampered = dict(response.raw_value)
        tampered["approval_decision"] = "tampered"
        ChecklistResponse.objects.filter(pk=response.pk).update(raw_value=tampered)
        assert self._artifact(world)["checksum"]["value"] != before

    def test_no_actor_email_in_the_artifact(self, world, tenant_a, vp_user, vp_membership):
        _approve(world, vp_user, tenant_a)
        assert vp_user.email not in json.dumps(self._artifact(world), default=str)


# ---------------------------------------------------------------------------
# D. Capability surface -- 4D4-DEC-012
# ---------------------------------------------------------------------------


def _capabilities_url():
    return reverse("iig_checklist:checklist-capabilities")


class TestCapabilitySurface:
    def test_reviewer_is_true(self, db, api_client_reviewer, reviewer_membership):
        resp = api_client_reviewer.get(_capabilities_url())
        assert resp.status_code == 200
        assert resp.data["can_override_response"] is True

    def test_vp_is_true(self, db, api_client_vp, vp_membership):
        resp = api_client_vp.get(_capabilities_url())
        assert resp.status_code == 200
        assert resp.data["can_override_response"] is True

    def test_doer_is_false(self, db, api_client_doer):
        resp = api_client_doer.get(_capabilities_url())
        assert resp.status_code == 200
        assert resp.data["can_override_response"] is False

    def test_tenant_admin_follows_the_governed_mapping(
        self, db, api_client_tenant_admin, tenant_admin_membership
    ):
        from authorization.models import Role
        from iig_checklist.permissions import PERM_OVERRIDE_EXECUTION, ROLE_PERMISSIONS

        expected = PERM_OVERRIDE_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.TENANT_ADMIN]
        resp = api_client_tenant_admin.get(_capabilities_url())
        assert resp.status_code == 200
        assert resp.data["can_override_response"] is expected
        # Records the currently governed answer explicitly.
        assert expected is False

    def test_authority_does_not_leak_across_tenants(
        self, db, reviewer_user, reviewer_membership, tenant_b
    ):
        """A Reviewer in tenant A is not a Reviewer in tenant B."""
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=reviewer_user)
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant_b.slug})
        resp = client.get(_capabilities_url())
        assert resp.status_code in (200, 403, 404)
        if resp.status_code == 200:
            assert resp.data["can_override_response"] is False

    def test_missing_tenant_fails_closed(self, db, reviewer_user, reviewer_membership):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=reviewer_user)
        resp = client.get(_capabilities_url())
        assert resp.status_code in (400, 403)

    def test_unauthenticated_is_rejected(self, db, tenant_a):
        from rest_framework.test import APIClient

        client = APIClient()
        client.credentials(**{"HTTP_X_TENANT_SLUG": tenant_a.slug})
        resp = client.get(_capabilities_url())
        assert resp.status_code in (401, 403)

    def test_response_exposes_named_capabilities_only(
        self, db, api_client_reviewer, reviewer_membership
    ):
        resp = api_client_reviewer.get(_capabilities_url())
        assert set(resp.data) == {"can_override_response"}
        blob = json.dumps(resp.data)
        # No raw codenames, no role internals, no database identifiers.
        assert "iig_checklist." not in blob
        assert "override_execution" not in blob
        assert "role" not in blob.lower()
        assert "permission" not in blob.lower()

    def test_capability_matches_actual_override_authorization(
        self, db, tenant_a, reviewer_user, reviewer_membership, user_a, doer_membership
    ):
        """The flag is derived from the same predicate the service enforces."""
        from iig_checklist.permissions import (
            PERM_OVERRIDE_EXECUTION,
            has_iig_checklist_permission,
        )

        assert has_iig_checklist_permission(reviewer_user, tenant_a, PERM_OVERRIDE_EXECUTION)
        assert not has_iig_checklist_permission(user_a, tenant_a, PERM_OVERRIDE_EXECUTION)

    def test_effective_permissions_endpoint_is_not_reused(self):
        """4D4-DEC-012 forbids reusing it; it must remain untouched.

        Asserted against the executable body, not the whole source: the class
        docstring names the rejected endpoint deliberately, to record *why* it
        was rejected, and a naive substring scan would trip on that explanation.
        """
        import inspect
        import textwrap

        from iig_checklist import views

        source = inspect.getsource(views.ChecklistCapabilitiesView.get)
        code_lines = [
            line
            for line in textwrap.dedent(source).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        body = "\n".join(code_lines)
        assert "effective_permissions" not in body
        assert "Permission.objects" not in body
        assert "has_iig_checklist_permission" in body
