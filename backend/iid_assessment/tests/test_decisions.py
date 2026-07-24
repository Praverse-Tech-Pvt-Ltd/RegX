"""
Precedent decision engine tests. Every test that plants a violation is
noted.
"""

from decimal import Decimal

import pytest

from iid_assessment.decisions import PrecedentDecision, PrecedentDecisionStatus, decide
from iid_assessment.matching import MatchStatus


class TestPassWithPrecedent:
    def test_within_potency_and_mde(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=Decimal("20"),
            selected_mde=Decimal("40"),
            mde_available=True,
        )
        assert decision.status == PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT
        assert "not an automatic safety" in decision.note.lower()

    def test_at_exact_threshold_still_passes(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("10"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        # Equal to potency does not exceed it -- but MDE unavailable
        # routes to REVIEW_REQUIRED per the "review required" rule.
        assert decision.status == PrecedentDecisionStatus.REVIEW_REQUIRED


class TestExceedsPrecedent:
    def test_exceeds_potency(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("15"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT
        assert decision.escalation_required

    def test_exceeds_mde(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=Decimal("50"),
            selected_mde=Decimal("40"),
            mde_available=True,
        )
        assert decision.status == PrecedentDecisionStatus.EXCEEDS_IID_PRECEDENT
        assert decision.escalation_required


class TestReviewRequired:
    def test_multiple_candidates(self):
        decision = decide(
            match_status=MatchStatus.MULTIPLE_EXACT_MATCHES,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=None,
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
            multiple_candidates=True,
        )
        assert decision.status == PrecedentDecisionStatus.REVIEW_REQUIRED

    def test_mde_unavailable_with_valid_potency(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.REVIEW_REQUIRED

    def test_superseded_source_release(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=Decimal("20"),
            selected_mde=Decimal("40"),
            mde_available=True,
            source_release_superseded=True,
        )
        assert decision.status == PrecedentDecisionStatus.REVIEW_REQUIRED


class TestNoMatch:
    def test_no_matching_precedent(self):
        decision = decide(
            match_status=MatchStatus.NO_MATCHING_IID_PRECEDENT,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=None,
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.NO_MATCH


class TestNotComparable:
    def test_route_mismatch(self):
        decision = decide(
            match_status=MatchStatus.ROUTE_MISMATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=None,
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.NOT_COMPARABLE

    def test_dosage_form_mismatch(self):
        decision = decide(
            match_status=MatchStatus.DOSAGE_FORM_MISMATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=None,
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.NOT_COMPARABLE

    def test_unit_conversion_failed(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=False,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
        )
        assert decision.status == PrecedentDecisionStatus.NOT_COMPARABLE

    def test_density_required_forces_not_comparable(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=None,
            selected_mde=None,
            mde_available=False,
            density_or_basis_required=True,
        )
        assert decision.status == PrecedentDecisionStatus.NOT_COMPARABLE


class TestNoForbiddenStatusPossible:
    """PLANTED VIOLATION (detected): the engine's vocabulary must
    structurally forbid SAFE/FDA APPROVED/AUTOMATICALLY ACCEPTABLE/
    REGULATORILY CLEARED as a decision outcome."""

    @pytest.mark.parametrize("status", list(PrecedentDecisionStatus.__dict__.values()))
    def test_no_status_constant_is_a_safety_claim(self, status):
        if not isinstance(status, str):
            return
        forbidden = ("SAFE", "FDA APPROVED", "AUTOMATICALLY ACCEPTABLE", "REGULATORILY CLEARED")
        assert not any(f in status.upper() for f in forbidden)

    def test_illegal_status_value_rejected_at_construction(self):
        with pytest.raises(ValueError):
            PrecedentDecision(status="SAFE", note="irrelevant")

    def test_note_asserting_forbidden_conclusion_rejected(self):
        with pytest.raises(ValueError):
            PrecedentDecision(
                status=PrecedentDecisionStatus.PASS_WITH_IID_PRECEDENT,
                note="This formulation is FDA APPROVED.",
            )

    def test_required_precedent_note_is_used_on_pass(self):
        decision = decide(
            match_status=MatchStatus.EXACT_MATCH,
            unit_conversion_ok=True,
            proposed_amount_per_unit=Decimal("5"),
            selected_potency_amount=Decimal("10"),
            proposed_daily_exposure=Decimal("20"),
            selected_mde=Decimal("40"),
            mde_available=True,
        )
        assert "not an automatic safety" in decision.note.lower()
        assert "not" in decision.note.lower() and "regulatory approval" in decision.note.lower()
