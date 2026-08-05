"""Milestone 4D-3 -- ORM-backed registry activation validation.

Real PostgreSQL-backed tests.  The central validator is never exercised through
mocked QuerySets or managers: every case builds actual persisted checklist
content and drives the governed activation endpoint.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-REG-018/019  activation validation and structured rejection
  - M4D3-TRG-006/007  dependency and trigger agreement
  - M4D3-FCR-012      registry_component_code selector disabled
  - M4D3-DEP-006      form E targets must be SYSTEM_CALCULATED
"""

from __future__ import annotations

import datetime

import pytest

from iig_checklist import calculation_registry as registry_mod
from iig_checklist.activation_validation import (
    DEPENDENCY_NOT_CALCULATED,
    QUESTION_CODE_DUPLICATE,
    QUESTION_CODE_MISSING,
    SELECTOR_WRONG_ANSWER_TYPE,
    UNKNOWN_REGISTRY_IDENTIFIER,
    WRONG_ANSWER_TYPE,
    validate_version_calculation_bindings,
)
from iig_checklist.enums import (
    AnswerType,
    ChecklistVersionStatus,
    Criticality,
    DataSourceClassification,
)

pytestmark = pytest.mark.django_db

#: Matches the existing lifecycle tests' base path.
BASE = "/api/regx/v1"


# ---------------------------------------------------------------------------
# Persisted content helpers -- no mocks anywhere.
# ---------------------------------------------------------------------------


def _section(version, code="S1", order=1):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version,
        code=code,
        title=f"Section {code}",
        display_order=order,
        criticality=Criticality.MEDIUM,
    )


def _question(
    section,
    code,
    *,
    answer_type,
    classification,
    binding="",
    order=1,
):
    from iig_checklist.models import ChecklistQuestion

    return ChecklistQuestion.objects.create(
        section=section,
        code=code,
        question_text=f"Q {code}",
        display_order=order,
        answer_type=answer_type,
        data_source_classification=classification,
        calculation_binding_identifier=binding,
        criticality=Criticality.LOW,
    )


def _selector_question(section, code=None, *, answer_type=None, order=90):
    """The governed component-reference selector the registry binds to."""
    return _question(
        section,
        code or registry_mod.Q_SUBJECT_COMPONENT,
        answer_type=answer_type or AnswerType.FORMULATION_COMPONENT_REFERENCE,
        classification=DataSourceClassification.USER_REQUIRED,
        order=order,
    )


def _calculated_question(section, code, identifier, *, order=1, answer_type=None):
    return _question(
        section,
        code,
        answer_type=answer_type or AnswerType.CALCULATED_VALUE,
        classification=DataSourceClassification.SYSTEM_CALCULATED,
        binding=identifier,
        order=order,
    )


def _valid_percentage_w_w_version(draft_version):
    """A version whose single binding resolves cleanly."""
    section = _section(draft_version)
    _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=1)
    _selector_question(section)
    return draft_version


def _prepare_for_activation(version):
    version.effective_date = datetime.date(2026, 1, 1)
    version.save(update_fields=["effective_date", "updated_at"])


def _approve_then_activate(version, api_client_doer, api_client_vp):
    """Drive the real governed lifecycle: submit -> approve -> activate."""
    pid = version.public_id
    submit = api_client_doer.post(
        f"{BASE}/iig-checklists/versions/{pid}/submit-review/", data={}
    )
    assert submit.status_code == 200, submit.data
    approve = api_client_vp.post(
        f"{BASE}/iig-checklists/versions/{pid}/approve/", data={}
    )
    assert approve.status_code == 200, approve.data
    return api_client_vp.post(
        f"{BASE}/iig-checklists/versions/{pid}/activate/", data={}
    )


# ===========================================================================
# A. Valid activation
# ===========================================================================


class TestValidActivation:
    def test_valid_bindings_produce_no_findings(self, draft_version):
        _valid_percentage_w_w_version(draft_version)
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_version_with_no_calculated_questions_is_unaffected(self, draft_version):
        section = _section(draft_version)
        _question(
            section,
            "Q_PLAIN",
            answer_type=AnswerType.SHORT_TEXT,
            classification=DataSourceClassification.USER_REQUIRED,
        )
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_unreferenced_registry_entries_do_not_block(self, draft_version):
        """Only identifiers the version actually references are validated."""
        _valid_percentage_w_w_version(draft_version)
        assert len(registry_mod.CALCULATION_BINDING_REGISTRY) == 6
        assert validate_version_calculation_bindings(draft_version) == ()

    def test_activation_succeeds_end_to_end(
        self, draft_version, api_client_doer, api_client_vp
    ):
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 200, response.data
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.ACTIVE
        assert draft_version.activated_at is not None

    def test_activation_emits_success_audit(
        self, draft_version, api_client_doer, api_client_vp
    ):
        from audit.models import AuditEvent

        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert AuditEvent.objects.filter(
            event_type="iig_checklist.version.activated",
            resource_id=str(draft_version.public_id),
        ).exists()


# ===========================================================================
# B. Missing bindings
# ===========================================================================


class TestMissingBindings:
    def test_missing_component_selector_question(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        findings = validate_version_calculation_bindings(draft_version)
        codes = {f.validation_code for f in findings}
        assert QUESTION_CODE_MISSING in codes
        assert any(f.question_code == registry_mod.Q_SUBJECT_COMPONENT for f in findings)

    def test_missing_form_e_dependency_question(self, draft_version):
        """percentage_of_iid_mde depends on the daily-exposure response."""
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_DAILY_EXPOSURE
            for f in findings
        )

    def test_missing_binding_blocks_activation_with_zero_mutation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED
        assert draft_version.activated_at is None

    def test_failed_activation_emits_no_success_audit(
        self, draft_version, api_client_doer, api_client_vp
    ):
        from audit.models import AuditEvent

        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert not AuditEvent.objects.filter(
            event_type="iig_checklist.version.activated",
            resource_id=str(draft_version.public_id),
        ).exists()

    def test_failed_activation_does_not_supersede_prior_active(
        self, draft_version, tenant_definition, user_a, api_client_doer, api_client_vp
    ):
        """The supersede step must never run when validation fails."""
        from iig_checklist.models import ChecklistVersion

        prior = ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=99,
            created_by=user_a,
            status=ChecklistVersionStatus.ACTIVE,
            effective_date=datetime.date(2025, 1, 1),
        )
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        prior.refresh_from_db()
        assert prior.status == ChecklistVersionStatus.ACTIVE


# ===========================================================================
# C. Duplicate bindings
# ===========================================================================


class TestDuplicateBindings:
    def test_duplicate_question_code_across_sections_is_rejected(self, draft_version):
        """Codes are unique per SECTION, so a version may hold duplicates."""
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)

        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_DUPLICATE
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
            for f in findings
        )

    def test_duplicate_never_silently_selects_one(self, draft_version):
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)
        findings = validate_version_calculation_bindings(draft_version)
        # Ambiguity is reported, not resolved -- no success despite one match
        # being perfectly valid on its own.
        assert findings != ()

    def test_duplicate_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section_one = _section(draft_version, code="S1", order=1)
        section_two = _section(draft_version, code="S2", order=2)
        _calculated_question(section_one, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section_one)
        _selector_question(section_two)
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED


# ===========================================================================
# D. Type and classification
# ===========================================================================


class TestTypeAndClassification:
    def test_wrong_answer_type_on_calculated_target(self, draft_version):
        section = _section(draft_version)
        # CALCULATED_STATUS is also SYSTEM_CALCULATED-compatible, but the
        # registry entry declares calculated_value.
        _calculated_question(
            section,
            "Q_PCT_WW",
            "percentage_w_w",
            answer_type=AnswerType.CALCULATED_STATUS,
        )
        _selector_question(section)
        findings = validate_version_calculation_bindings(draft_version)
        assert any(f.validation_code == WRONG_ANSWER_TYPE for f in findings)

    def test_selector_with_wrong_answer_type(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")
        _selector_question(section, answer_type=AnswerType.SHORT_TEXT)
        findings = validate_version_calculation_bindings(draft_version)
        assert any(f.validation_code == SELECTOR_WRONG_ANSWER_TYPE for f in findings)

    def test_form_e_dependency_must_be_system_calculated(self, draft_version):
        """A non-calculated question cannot satisfy a prior-outcome dependency."""
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        _question(
            section,
            registry_mod.Q_DAILY_EXPOSURE,
            answer_type=AnswerType.DECIMAL,
            classification=DataSourceClassification.USER_REQUIRED,
            order=2,
        )
        findings = validate_version_calculation_bindings(draft_version)
        assert any(f.validation_code == DEPENDENCY_NOT_CALCULATED for f in findings)


# ===========================================================================
# E. Registry integrity
# ===========================================================================


class TestRegistryIntegrity:
    def test_unknown_calculation_binding_identifier(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == UNKNOWN_REGISTRY_IDENTIFIER
            and f.registry_identifier == "not_a_registry_key"
            for f in findings
        )

    def test_unknown_identifier_blocks_activation(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        draft_version.refresh_from_db()
        assert draft_version.status == ChecklistVersionStatus.APPROVED

    def test_full_mde_chain_validates(self, draft_version):
        """daily_exposure -> percentage_of_iid_mde resolves end to end."""
        section = _section(draft_version)
        _calculated_question(
            section, registry_mod.Q_DAILY_EXPOSURE, "daily_exposure", order=1
        )
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde", order=2)
        _selector_question(section)
        assert validate_version_calculation_bindings(draft_version) == ()


# ===========================================================================
# F. Isolation, lifecycle and determinism
# ===========================================================================


class TestIsolationAndLifecycle:
    def test_same_code_in_another_version_cannot_satisfy_binding(
        self, draft_version, tenant_definition, user_a
    ):
        from iig_checklist.models import ChecklistVersion

        other = ChecklistVersion.objects.create(
            definition=tenant_definition, version_number=7, created_by=user_a
        )
        other_section = _section(other, code="OTHER", order=1)
        _selector_question(other_section)  # correct code, wrong version

        section = _section(draft_version)
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w")

        findings = validate_version_calculation_bindings(draft_version)
        assert any(
            f.validation_code == QUESTION_CODE_MISSING
            and f.question_code == registry_mod.Q_SUBJECT_COMPONENT
            for f in findings
        )

    def test_cross_tenant_activation_returns_404(
        self, draft_version, tenant_b, api_client_vp
    ):
        """A caller who *has* the permission still cannot see another tenant.

        The actor is a VP who can legitimately activate in their own tenant, so
        a 404 here proves tenant scoping rather than a permission denial -- and
        avoids leaking whether the version exists.
        """
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        draft_version.definition.tenant = tenant_b
        draft_version.definition.save(update_fields=["tenant"])
        response = api_client_vp.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/activate/",
            data={},
        )
        assert response.status_code == 404
        draft_version.refresh_from_db()
        assert draft_version.status != ChecklistVersionStatus.ACTIVE

    def test_doer_cannot_activate(self, draft_version, api_client_doer):
        _valid_percentage_w_w_version(draft_version)
        _prepare_for_activation(draft_version)
        response = api_client_doer.post(
            f"{BASE}/iig-checklists/versions/{draft_version.public_id}/activate/"
        )
        assert response.status_code == 403

    def test_validation_ordering_is_deterministic(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_MDE_PCT", "percentage_of_iid_mde")
        _calculated_question(section, "Q_PCT_WW", "percentage_w_w", order=2)
        runs = [
            tuple(
                (f.question_code, f.registry_identifier, f.validation_code)
                for f in validate_version_calculation_bindings(draft_version)
            )
            for _ in range(5)
        ]
        assert len(set(runs)) == 1
        assert runs[0] != ()


# ===========================================================================
# G. Result integrity
# ===========================================================================


class TestResultIntegrity:
    def test_findings_expose_no_internal_ids(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        findings = validate_version_calculation_bindings(draft_version)
        assert findings
        for finding in findings:
            assert "pk" not in finding.message.lower()
            assert "select " not in finding.message.lower()
            assert "traceback" not in finding.message.lower()
            if finding.question_public_id is not None:
                # A public UUID, never a bare integer primary key.
                assert "-" in finding.question_public_id

    def test_error_body_is_structured_and_sanitized(
        self, draft_version, api_client_doer, api_client_vp
    ):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        _prepare_for_activation(draft_version)
        response = _approve_then_activate(draft_version, api_client_doer, api_client_vp)
        assert response.status_code == 400
        body = str(response.data)
        assert "REGISTRY_VALIDATION_FAILED" in body
        assert "not_a_registry_key" in body
        assert "Traceback" not in body

    def test_findings_are_immutable(self, draft_version):
        section = _section(draft_version)
        _calculated_question(section, "Q_BAD", "not_a_registry_key")
        finding = validate_version_calculation_bindings(draft_version)[0]
        with pytest.raises(AttributeError):
            finding.validation_code = "TAMPERED"
