"""QA-09 (iig_checklist draft editing): a change and its audit record commit together.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL. The section, question and applicability-rule views had no transaction at
all, so on the old code the change stayed with no audit record and these tests failed.
One test per view method.

NOT covered here, on purpose: the execution, response, override and calculation paths
(and iid_assessment snapshots) emit through `transaction.on_commit()`, as the approved
spec requires (docs/MILESTONE_4D_2_IMPLEMENTATION_SPEC.md, "All events emitted via
transaction.on_commit()"). Moving those emits inside the transaction contradicts that
spec, so it is left for the owner to decide (see the PR description).
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from iig_checklist.models import ApplicabilityRule, ChecklistQuestion, ChecklistSection

BASE = "/api/regx/v1/iig-checklists"
pytestmark = pytest.mark.django_db(transaction=True)


def _fails(fn, *args, **kwargs):
    with audit_writes_fail():
        attempt(fn, *args, format="json", **kwargs)


def test_section_create(platform_draft_version, api_client_platform_actor):
    _fails(
        api_client_platform_actor.post,
        f"{BASE}/versions/{platform_draft_version.public_id}/sections/",
        data={"code": "SEC-QA09", "title": "s", "display_order": 2, "criticality": "low"},
    )
    assert not ChecklistSection.objects.filter(code="SEC-QA09").exists()


def test_section_update(platform_section, api_client_platform_actor):
    _fails(
        api_client_platform_actor.patch,
        f"{BASE}/sections/{platform_section.public_id}/",
        data={"title": "changed"},
    )
    platform_section.refresh_from_db()
    assert platform_section.title == "Section 1"


def test_section_delete(platform_section, api_client_platform_actor):
    _fails(api_client_platform_actor.delete, f"{BASE}/sections/{platform_section.public_id}/")
    assert ChecklistSection.objects.filter(pk=platform_section.pk).exists()


def test_question_create(platform_section, api_client_platform_actor):
    _fails(
        api_client_platform_actor.post,
        f"{BASE}/sections/{platform_section.public_id}/questions/",
        data={
            "code": "Q-QA09",
            "question_text": "Synthetic?",
            "display_order": 2,
            "answer_type": "yes_no",
            "data_source_classification": "user_required",
            "criticality": "low",
        },
    )
    assert not ChecklistQuestion.objects.filter(code="Q-QA09").exists()


def test_question_update(platform_question, api_client_platform_actor):
    _fails(
        api_client_platform_actor.patch,
        f"{BASE}/questions/{platform_question.public_id}/",
        data={"question_text": "changed"},
    )
    platform_question.refresh_from_db()
    assert platform_question.question_text == "Is this synthetic?"


def test_question_delete(platform_question, api_client_platform_actor):
    _fails(api_client_platform_actor.delete, f"{BASE}/questions/{platform_question.public_id}/")
    assert ChecklistQuestion.objects.filter(pk=platform_question.pk).exists()


def test_applicability_rule_create(platform_draft_version, api_client_platform_actor):
    _fails(
        api_client_platform_actor.post,
        f"{BASE}/versions/{platform_draft_version.public_id}/applicability-rules/",
        data={
            "code": "RULE-QA09",
            "condition_json": {"field": "product.route", "op": "eq", "value": "ORAL"},
            "outcome_if_true": "applicable",
            "outcome_if_false": "not_applicable",
            "reason_code": "route_match",
            "explanation_template": "Applies to oral products.",
            "field_registry_version": 1,
        },
    )
    assert not ApplicabilityRule.objects.filter(code="RULE-QA09").exists()
