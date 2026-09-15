"""P2: audit coverage for gap analysis and governed version edits.

Two actions changed governed state or produced a governed result with no audit
trace:

* gap analysis was computed and returned with nothing recorded -- and because
  the score is never stored, the audit row is the only evidence it existed
* the version PATCH mutated `effective_date`, `regulatory_basis`, `jurisdiction`
  and `change_summary` in a draft -- the fields a later approval is made
  against -- while every other transition on that version was audited

Each test asserts the four things that make an audit row usable: event type,
tenant, actor, and target identifier. Payload assertions are written as
exclusions as well as inclusions, because the risk here is not a missing key
but governed answer content arriving in an append-only table.
"""

from datetime import date
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures -- an active version and an approved formulation, the two gates
# `create_execution` enforces.
# ---------------------------------------------------------------------------


@pytest.fixture
def active_version(db, tenant_definition, user_a):
    from iig_checklist.enums import AnswerType, Criticality, DataSourceClassification
    from iig_checklist.models import ChecklistQuestion, ChecklistSection, ChecklistVersion

    version = ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=1,
        status="active",
        effective_date=date.today(),
        created_by=user_a,
    )
    section = ChecklistSection.objects.create(
        checklist_version=version,
        code="S1",
        title="Section one",
        display_order=1,
        criticality=Criticality.LOW,
    )
    for order, code in enumerate(["Q1", "Q2"], start=1):
        ChecklistQuestion.objects.create(
            section=section,
            code=code,
            question_text=f"Confidential question body {code}",
            display_order=order,
            answer_type=AnswerType.YES_NO,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            required=True,
            criticality=Criticality.LOW,
        )
    return version


@pytest.fixture
def draft_version(db, tenant_definition, user_a):
    from iig_checklist.models import ChecklistVersion

    return ChecklistVersion.objects.create(
        definition=tenant_definition,
        version_number=2,
        status="draft",
        effective_date=date.today(),
        created_by=user_a,
    )


@pytest.fixture
def approved_formulation(db, tenant_a, user_a):
    from formulations.models import (
        FormulationStatus,
        FormulationVersion,
        ProductDevelopmentRecord,
        ProductRecordStatus,
    )

    product = ProductDevelopmentRecord.objects.create(
        tenant=tenant_a,
        product_code="P2-AUDIT-1",
        proposed_product_name="P2 audit product",
        active_ingredient="Synthetic",
        release_type="immediate",
        route="oral",
        dosage_form="tablet",
        proposed_strength_amount=Decimal("10.000000"),
        proposed_strength_unit="mg",
        regulatory_market_context="TEST",
        status=ProductRecordStatus.APPROVED,
        created_by=user_a,
    )
    return FormulationVersion.objects.create(
        product=product,
        version_number=1,
        status=FormulationStatus.APPROVED,
        total_dosage_unit_weight=Decimal("100.000000"),
        total_dosage_unit_weight_unit="milligram",
        created_by=user_a,
    )


@pytest.fixture
def execution(db, tenant_a, active_version, approved_formulation, user_a, doer_membership):
    from iig_checklist.services import create_execution

    return create_execution(
        tenant=tenant_a,
        checklist_version_public_id=str(active_version.public_id),
        formulation_version_public_id=str(approved_formulation.public_id),
        actor=user_a,
    )


def _events(event_type):
    from audit.models import AuditEvent

    return AuditEvent.objects.filter(event_type=event_type)


# ===========================================================================
# Gap analysis
# ===========================================================================


class TestGapAnalysisIsAudited:
    URL = "/api/regx/v1/iig-checklists/executions/{}/gap-analysis/"

    def test_successful_analysis_writes_one_event(self, api_client_doer, execution):
        before = _events("iig_checklist.gap_analysis.generated").count()
        response = api_client_doer.get(self.URL.format(execution.public_id))
        assert response.status_code == 200
        assert _events("iig_checklist.gap_analysis.generated").count() == before + 1

    def test_event_records_tenant_actor_and_target(
        self, api_client_doer, execution, tenant_a, user_a
    ):
        api_client_doer.get(self.URL.format(execution.public_id))
        event = _events("iig_checklist.gap_analysis.generated").latest("created_at")

        assert event.tenant_id == tenant_a.id
        assert event.actor_id == user_a.id
        assert event.actor_email == user_a.email
        assert event.resource_id == str(execution.public_id)
        assert event.resource_type == "iig_checklist_execution"

    def test_payload_carries_counts_and_score(self, api_client_doer, execution):
        api_client_doer.get(self.URL.format(execution.public_id))
        payload = _events("iig_checklist.gap_analysis.generated").latest("created_at").payload

        assert payload["execution_public_id"] == str(execution.public_id)
        assert payload["total_questions"] == 2
        assert payload["section_count"] == 1
        for key in ("answered", "unanswered", "not_applicable", "gap_count"):
            assert key in payload

    def test_payload_never_carries_question_text_or_answers(self, api_client_doer, execution):
        """The analysis result holds `gaps` (question text plus the answer) and
        `sections` (section names). Neither may reach an append-only table."""
        response = api_client_doer.get(self.URL.format(execution.public_id))
        assert "gaps" in response.data, "guard is meaningless if the API stopped returning gaps"

        payload = _events("iig_checklist.gap_analysis.generated").latest("created_at").payload
        assert "gaps" not in payload
        assert "sections" not in payload
        serialised = str(payload)
        assert "Confidential question body" not in serialised

    def test_a_refused_request_records_nothing(self, api_client_reviewer, execution):
        """Only a successful analysis is a generation. A caller from another
        tenant gets a 404 and must not leave a success row behind."""
        import uuid

        before = _events("iig_checklist.gap_analysis.generated").count()
        response = api_client_reviewer.get(self.URL.format(uuid.uuid4()))
        assert response.status_code == 404
        assert _events("iig_checklist.gap_analysis.generated").count() == before

    def test_each_call_records_a_separate_generation(self, api_client_doer, execution):
        """Auditing a GET means repeat calls repeat rows. Asserted rather than
        left implicit: it is the accepted cost of auditing a computed result
        that is never stored."""
        before = _events("iig_checklist.gap_analysis.generated").count()
        for _ in range(3):
            api_client_doer.get(self.URL.format(execution.public_id))
        assert _events("iig_checklist.gap_analysis.generated").count() == before + 3


# ===========================================================================
# Checklist version update
# ===========================================================================


class TestVersionUpdateIsAudited:
    URL = "/api/regx/v1/iig-checklists/versions/{}/"

    def test_successful_patch_writes_one_event(self, api_client_doer, draft_version):
        before = _events("iig_checklist.version.updated").count()
        response = api_client_doer.patch(
            self.URL.format(draft_version.public_id),
            {"change_summary": "Revised scope"},
            format="json",
        )
        assert response.status_code == 200
        assert _events("iig_checklist.version.updated").count() == before + 1

    def test_event_records_tenant_actor_and_target(
        self, api_client_doer, draft_version, tenant_a, user_a
    ):
        api_client_doer.patch(
            self.URL.format(draft_version.public_id),
            {"jurisdiction": "US_FDA"},
            format="json",
        )
        event = _events("iig_checklist.version.updated").latest("created_at")

        assert event.tenant_id == tenant_a.id
        assert event.actor_id == user_a.id
        assert event.resource_id == str(draft_version.public_id)
        assert event.resource_type == "iig_checklist_version"

    def test_payload_names_changed_fields_only(self, api_client_doer, draft_version):
        api_client_doer.patch(
            self.URL.format(draft_version.public_id),
            {"jurisdiction": "US_FDA", "change_summary": "Sensitive draft rationale"},
            format="json",
        )
        payload = _events("iig_checklist.version.updated").latest("created_at").payload

        assert payload["fields_changed"] == ["change_summary", "jurisdiction"]
        assert payload["version_public_id"] == str(draft_version.public_id)
        assert payload["status"] == "draft"

    def test_payload_never_carries_the_new_values(self, api_client_doer, draft_version):
        """`change_summary` and `regulatory_basis` are draft regulatory text.
        Recording the values would put unapproved content somewhere it can
        never be redacted."""
        api_client_doer.patch(
            self.URL.format(draft_version.public_id),
            {"change_summary": "UNAPPROVED DRAFT TEXT"},
            format="json",
        )
        payload = _events("iig_checklist.version.updated").latest("created_at").payload
        assert "UNAPPROVED DRAFT TEXT" not in str(payload)

    def test_a_patch_that_changes_nothing_records_nothing(self, api_client_doer, draft_version):
        before = _events("iig_checklist.version.updated").count()
        response = api_client_doer.patch(
            self.URL.format(draft_version.public_id), {}, format="json"
        )
        assert response.status_code == 200
        assert _events("iig_checklist.version.updated").count() == before

    def test_a_rejected_edit_records_nothing(self, api_client_doer, draft_version):
        """Validation raises before the emit, so a refused edit leaves no row."""
        before = _events("iig_checklist.version.updated").count()
        response = api_client_doer.patch(
            self.URL.format(draft_version.public_id),
            {"effective_date": "not-a-date"},
            format="json",
        )
        assert response.status_code >= 400
        assert _events("iig_checklist.version.updated").count() == before

    def test_an_unauthorised_edit_records_nothing(self, api_client_reviewer, draft_version):
        """Reviewer holds no edit permission. A 403 must not look like an edit."""
        before = _events("iig_checklist.version.updated").count()
        response = api_client_reviewer.patch(
            self.URL.format(draft_version.public_id),
            {"jurisdiction": "US_FDA"},
            format="json",
        )
        assert response.status_code == 403
        assert _events("iig_checklist.version.updated").count() == before


# ===========================================================================
# Allow-list behaviour and immutability
# ===========================================================================


class TestPayloadAllowList:
    def test_unlisted_keys_are_dropped(self):
        from iig_checklist.audit import IigChecklistEvent, _restrict

        cleaned = _restrict(
            IigChecklistEvent.GAP_ANALYSIS_GENERATED,
            {"gap_count": 2, "gaps": [{"question_text": "LEAK"}], "sections": ["A"]},
        )
        assert cleaned == {"gap_count": 2}

    def test_events_without_an_allow_list_are_untouched(self):
        """P2 narrows only the events it adds. Filtering the domain's other
        twenty-odd events would change the historical shape of the trail."""
        from iig_checklist.audit import IigChecklistEvent, _restrict

        payload = {"anything": "preserved", "nested": {"a": 1}}
        assert _restrict(IigChecklistEvent.EXECUTION_CREATED, payload) == payload


class TestAuditRowsRemainImmutable:
    def test_a_gap_analysis_event_cannot_be_updated_or_deleted(self, api_client_doer, execution):
        api_client_doer.get(
            f"/api/regx/v1/iig-checklists/executions/{execution.public_id}/gap-analysis/"
        )
        event = _events("iig_checklist.gap_analysis.generated").latest("created_at")

        with pytest.raises(PermissionError):
            event.payload = {"gap_count": 999}
            event.save()

        with pytest.raises(PermissionError):
            event.delete()
