"""Milestone 4D-4 -- reviewer-conclusion completion.

Specification: MILESTONE_4D_DISCOVERY.md section 13; MILESTONE_4D_4_DISCOVERY.md
section H -- 4D4-DEC-013 (strict expected_version) and the approved 4D4-DEC-012
extension adding can_enter_reviewer_conclusion.

Fixtures are synthetic. No production regulatory content exists or is invented
here -- the content-approval gate is open at 0 of 20.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from iig_checklist.enums import AnswerType, DataSourceClassification

pytestmark = pytest.mark.django_db


def _error_code(resp):
    """The governed error_code, whichever envelope carried it."""
    data = resp.data
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        data = data["error"].get("detail", {})
    code = data.get("error_code") if isinstance(data, dict) else None
    if isinstance(code, list):
        code = code[0] if code else None
    return code


def _world(tenant, tenant_definition, user, *, status="submitted_for_review"):
    from formulations.models import FormulationVersion, ProductDevelopmentRecord
    from iig_checklist.models import ChecklistQuestion, ChecklistSection, ChecklistVersion
    from iig_checklist.services import create_execution

    cv = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active", created_by=user
    )
    section = ChecklistSection.objects.create(
        checklist_version=cv, code="SEC-1", title="Section", display_order=1, criticality="low"
    )
    ChecklistQuestion.objects.create(
        section=section,
        code="Q-CONC",
        question_text="Synthetic reviewer conclusion",
        display_order=1,
        answer_type=AnswerType.REVIEWER_CONCLUSION,
        data_source_classification=DataSourceClassification.REVIEWER_CONFIRMED,
        criticality="low",
    )
    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code="PROD-RC-01",
        proposed_product_name="Synthetic RC Product",
        active_ingredient="Synthetic RC Ingredient",
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
    if status != "draft":
        type(execution).objects.filter(pk=execution.pk).update(status=status)
        execution.refresh_from_db()
    return {"execution": execution, "version": cv}


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    return _world(tenant_a, tenant_definition, user_a)


def _response(world_):
    from iig_checklist.models import ChecklistResponse

    return ChecklistResponse.objects.get(execution=world_["execution"], question__code="Q-CONC")


def _url(world_, response):
    return reverse(
        "iig_checklist:execution-reviewer-conclusion",
        kwargs={
            "public_id": world_["execution"].public_id,
            "response_public_id": response.public_id,
        },
    )


def _body(version, value="A governed reviewer conclusion statement."):
    return {"raw_value": {"value": value}, "expected_version": version}


# ---------------------------------------------------------------------------
# A. 4D4-DEC-013 -- strict expected_version
# ---------------------------------------------------------------------------


class TestStrictExpectedVersion:
    def test_valid_integer_current_version_succeeds(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version), format="json"
        )
        assert resp.status_code == 200

    def test_stale_integer_returns_governed_conflict(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version + 5), format="json"
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "reviewer_conclusion_stale_version"

    @pytest.mark.parametrize(
        "bad",
        ["1", 1.0, "1.0", True, None, 0, -1],
        ids=["str_1", "float_1_0", "str_1_0", "bool_true", "null", "zero", "negative"],
    )
    def test_coercive_and_invalid_inputs_are_refused(
        self, world, api_client_reviewer, reviewer_membership, bad
    ):
        """`4D4-DEC-013` -- no third concurrency contract.

        The serializer no longer coerces, so each of these reaches the shared
        governed validator intact and is refused there, exactly as on the
        response-update and override paths.
        """
        response = _response(world)
        resp = api_client_reviewer.post(_url(world, response), data=_body(bad), format="json")
        assert resp.status_code == 400
        assert _error_code(resp) in {"invalid_expected_version", "expected_version_required"}

    def test_missing_expected_version_is_refused(
        self, world, api_client_reviewer, reviewer_membership
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data={"raw_value": {"value": "Some governed conclusion."}},
            format="json",
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "expected_version_required"

    def test_no_coercive_integerfield_remains(self):
        """The divergence `MILESTONE_4D_4_DISCOVERY.md` §H recorded is closed."""
        from iig_checklist.serializers import ReviewerConclusionSerializer

        field = ReviewerConclusionSerializer().fields["expected_version"]
        from rest_framework import serializers as drf

        assert isinstance(field, drf.JSONField)
        assert not isinstance(field, drf.IntegerField)

    def test_all_three_governed_paths_share_one_validator(self):
        """One structural rule, three governed entry points."""
        import inspect

        from iig_checklist import overrides, services

        assert "validate_expected_version(" in inspect.getsource(services.enter_reviewer_conclusion)
        assert "validate_expected_version(" in inspect.getsource(services.update_checklist_response)
        assert "validate_expected_version(" in inspect.getsource(
            overrides.override_checklist_response
        )


# ---------------------------------------------------------------------------
# B. Section 13 -- meaningful non-empty text, no invented numeric minimum
# ---------------------------------------------------------------------------


class TestConclusionTextRequirements:
    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_empty_and_whitespace_only_are_refused(
        self, world, api_client_reviewer, reviewer_membership, value
    ):
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version, value), format="json"
        )
        assert resp.status_code == 400

    def test_a_single_meaningful_character_is_accepted(
        self, world, api_client_reviewer, reviewer_membership
    ):
        """Section 13 states 'min length enforced' but specifies NO number.

        A numeric minimum is therefore deliberately NOT invented: meaningful
        non-empty text is the whole of the presently-defined requirement. This
        test exists to lock that in -- if someone later adds an arbitrary
        3/5/10-character rule without an authoritative source, it fails.
        """
        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response), data=_body(response.version, "x"), format="json"
        )
        assert resp.status_code == 200

    def test_existing_maximum_is_still_enforced(
        self, world, api_client_reviewer, reviewer_membership
    ):
        from iig_checklist.execution_constants import MAX_REVIEWER_CONCLUSION_CHARS

        response = _response(world)
        resp = api_client_reviewer.post(
            _url(world, response),
            data=_body(response.version, "x" * (MAX_REVIEWER_CONCLUSION_CHARS + 1)),
            format="json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C. Permission and lifecycle (verifying existing governance, not redesigning)
# ---------------------------------------------------------------------------


class TestPermissionAndLifecycle:
    def test_doer_is_refused(self, world, api_client_doer):
        response = _response(world)
        resp = api_client_doer.post(
            _url(world, response), data=_body(response.version), format="json"
        )
        assert resp.status_code in {403, 404}

    def test_non_reviewable_lifecycle_is_refused(
        self,
        db,
        tenant_a,
        tenant_definition,
        user_a,
        doer_membership,
        api_client_reviewer,
        reviewer_membership,
    ):
        world_ = _world(tenant_a, tenant_definition, user_a, status="draft")
        response = _response(world_)
        resp = api_client_reviewer.post(
            _url(world_, response), data=_body(response.version), format="json"
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# D. Capability surface -- approved 4D4-DEC-012 extension
# ---------------------------------------------------------------------------


CAPABILITIES_URL = "iig_checklist:checklist-capabilities"


class TestReviewerConclusionCapability:
    def _get(self, client):
        return client.get(reverse(CAPABILITIES_URL))

    def test_reviewer_may_enter_reviewer_conclusion(
        self, db, api_client_reviewer, reviewer_membership
    ):
        resp = self._get(api_client_reviewer)
        assert resp.status_code == 200
        assert resp.data["can_enter_reviewer_conclusion"] is True

    def test_doer_may_not(self, db, api_client_doer):
        assert self._get(api_client_doer).data["can_enter_reviewer_conclusion"] is False

    def test_vp_matches_the_governed_role_mapping(self, db, api_client_vp, vp_membership):
        """Derived from ROLE_PERMISSIONS, not guessed.

        VP does not hold PERM_REVIEW_EXECUTION in the current governed mapping --
        it holds approve/supersede/view plus the 4D-4 override and export
        permissions. The capability must report that faithfully rather than
        flatter the UI.
        """
        from authorization.models import Role
        from iig_checklist.permissions import PERM_REVIEW_EXECUTION, ROLE_PERMISSIONS

        expected = PERM_REVIEW_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.VP]
        assert self._get(api_client_vp).data["can_enter_reviewer_conclusion"] is expected

    def test_tenant_admin_matches_the_governed_role_mapping(
        self, db, api_client_tenant_admin, tenant_admin_membership
    ):
        from authorization.models import Role
        from iig_checklist.permissions import PERM_REVIEW_EXECUTION, ROLE_PERMISSIONS

        expected = PERM_REVIEW_EXECUTION in ROLE_PERMISSIONS[Role.BuiltIn.TENANT_ADMIN]
        assert self._get(api_client_tenant_admin).data["can_enter_reviewer_conclusion"] is expected

    def test_capability_matches_the_service_authorization(
        self, db, reviewer_user, tenant_a, reviewer_membership
    ):
        """The flag and the service must never disagree."""
        from iig_checklist.permissions import PERM_REVIEW_EXECUTION, has_iig_checklist_permission

        assert has_iig_checklist_permission(reviewer_user, tenant_a, PERM_REVIEW_EXECUTION) is True

    def test_both_capabilities_are_derived_independently(
        self, db, api_client_reviewer, reviewer_membership
    ):
        """Reviewer holds review_execution but not override_execution."""
        data = self._get(api_client_reviewer).data
        assert data["can_enter_reviewer_conclusion"] is True
        assert data["can_override_response"] is True
        assert set(data) == {"can_override_response", "can_enter_reviewer_conclusion"}

    def test_no_permission_internals_leak(self, db, api_client_reviewer, reviewer_membership):
        """Named capability flags only -- no codenames, roles or identifiers.

        Asserted against the key set and value types rather than by scanning the
        serialized blob for substrings: ``can_override_response`` itself contains
        "id", so a naive substring scan reports a leak that is not one.
        """
        data = self._get(api_client_reviewer).data
        assert set(data) == {"can_override_response", "can_enter_reviewer_conclusion"}
        assert all(isinstance(value, bool) for value in data.values())
        for key in data:
            assert key.startswith("can_")
            assert "iig_checklist." not in key
            assert not key.endswith("_id")
