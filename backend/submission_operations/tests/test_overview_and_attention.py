"""Overview, internal readiness, attention ordering and due-date boundaries.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from submission_operations import services
from submission_operations.attention import REASON_RANK, AttentionReason, AttentionSeverity
from submission_operations.tests.conftest import (
    OPS_API,
    add_blocker,
    attention_of,
    make_case,
    make_dossier,
    make_section,
    overview_of,
    reasons_of,
    set_section,
)


def _today():
    return timezone.localdate()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOverview:
    def test_an_empty_tenant_reports_zeroes_not_nulls(self, client_admin_a):
        """Zero and null are different answers. An admin sees every module, so
        every block is a real object full of zeroes."""
        data = overview_of(client_admin_a)
        for module in ("cases", "dossiers", "sections", "blockers", "workflows", "upgrades"):
            assert data[module] is not None, f"{module} should be visible to an admin"
        assert data["cases"]["open"] == 0
        assert data["sections"]["required_total"] == 0
        assert data["restricted_modules"] == []

    def test_the_response_declares_itself_internal(self, client_admin_a):
        data = overview_of(client_admin_a)
        assert data["semantics"] == "internal_operational"
        assert data["due_soon_days"] == services.DISPLAY_DUE_SOON_DAYS

    def test_counts_reflect_real_domain_rows(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")
        make_section(dossier, tenant_a, admin_a, "B")
        make_section(dossier, tenant_a, admin_a, "OPT", required=False)

        data = overview_of(client_admin_a)
        assert data["cases"]["open"] == 1
        assert data["dossiers"]["open"] == 1
        # The optional section is excluded: the tenant said it does not gate.
        assert data["sections"]["required_total"] == 2

    def test_a_retired_section_stops_counting_as_work(self, client_admin_a, tenant_a, admin_a):
        """M9 retires rather than deletes so history survives. History is not a
        to-do list, and a retired overdue section nobody can clear would sit in
        the queue forever."""
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        keep = make_section(dossier, tenant_a, admin_a, "A")
        drop = make_section(dossier, tenant_a, admin_a, "B")
        assert overview_of(client_admin_a)["sections"]["required_total"] == 2

        ds.retire_section(section=drop, tenant=tenant_a, actor=admin_a)
        data = overview_of(client_admin_a)
        assert data["sections"]["required_total"] == 1
        assert keep.section_code == "A"

    def test_sections_in_a_terminal_dossier_are_not_outstanding_work(
        self, client_admin_a, tenant_a, admin_a
    ):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")
        assert overview_of(client_admin_a)["sections"]["required_total"] == 1

        ds.cancel_dossier(dossier=dossier, tenant=tenant_a, actor=admin_a, reason="Synthetic")
        assert overview_of(client_admin_a)["sections"]["required_total"] == 0

    def test_open_blockers_are_counted(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)
        assert overview_of(client_admin_a)["blockers"]["open"] == 1


# ---------------------------------------------------------------------------
# Internal readiness -- aggregated from M9, never recomputed
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInternalReadiness:
    def test_the_label_is_always_explicitly_internal(self):
        """Pinned wording. A badge reading plain "Ready" on an operations screen
        is the single most misleading thing this milestone could ship."""
        for value in services.INTERNAL_READINESS_VALUES:
            assert value.startswith("internally_") or value == "no_required_sections"
        assert "internally_ready" in services.INTERNAL_READINESS_VALUES
        for banned in ("submission_ready", "agency_ready", "compliant", "approved", "filing"):
            assert not any(banned in v for v in services.INTERNAL_READINESS_VALUES)

    def test_a_dossier_with_no_required_sections_is_not_ready(self):
        """It is not ready; there is nothing to be ready about. Collapsing this
        into the same green as finished work would be a lie by omission."""
        assert services.internal_readiness_label(0, 0) == services.INTERNAL_READINESS_NO_REQUIRED

    def test_labels_track_the_completion_ratio(self):
        assert services.internal_readiness_label(3, 3) == services.INTERNAL_READINESS_READY
        assert services.internal_readiness_label(3, 1) == services.INTERNAL_READINESS_PARTIAL
        assert services.internal_readiness_label(3, 0) == services.INTERNAL_READINESS_NOT_READY

    def test_the_dashboard_reads_m9_readiness_rather_than_section_status(
        self, client_admin_a, tenant_a, admin_a
    ):
        """The load-bearing test for "no second source of truth".

        A section is marked COMPLETE. M9 still derives readiness NOT_READY,
        because an open blocker outranks the status a user typed. A dashboard
        inferring readiness from status would call this complete; reading M9's
        column does not.
        """
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)
        set_section(section, tenant_a, admin_a, status=SectionStatus.COMPLETE)

        section.refresh_from_db()
        assert section.status == SectionStatus.COMPLETE, "the user said complete"
        assert section.readiness != Readiness.READY, "M9 disagrees, and M9 is authoritative"

        data = overview_of(client_admin_a)
        assert data["sections"]["required_total"] == 1
        assert data["sections"]["required_complete"] == 0, "dashboard follows M9, not status"


# ---------------------------------------------------------------------------
# Due dates
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDueDateBoundaries:
    """The window is a display threshold and carries no regulatory meaning."""

    def test_the_threshold_is_documented_as_operational_only(self):
        """The disclaimer must sit beside the constant, not in a doc nobody reads.

        Asserted against the source text: a future edit that changes 7 to 30 and
        drops the "no regulatory meaning" note turns this red, which is the only
        way a comment stays true.
        """
        import inspect

        assert services.DISPLAY_DUE_SOON_DAYS == 7
        source = inspect.getsource(services)
        marker = "DISPLAY_DUE_SOON_DAYS = 7"
        preamble = source[: source.index(marker)]
        disclaimer = preamble[preamble.rindex("#: Operational UX threshold") :]
        assert "carries no regulatory meaning" in disclaimer
        for banned in ("deadline", "statutory", "agency"):
            assert banned in disclaimer, f"the note should name {banned!r} as what this is NOT"

    @pytest.mark.parametrize(
        "offset_days,expect_overdue,expect_due_soon",
        [
            (-1, True, False),  # yesterday
            (0, False, True),  # today
            (1, False, True),
            (6, False, True),
            (7, False, True),  # the boundary is inclusive
            (8, False, False),  # outside the window
        ],
    )
    def test_boundaries(
        self, client_admin_a, tenant_a, admin_a, offset_days, expect_overdue, expect_due_soon
    ):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        set_section(
            section,
            tenant_a,
            admin_a,
            due_date=_today() + timedelta(days=offset_days),
        )

        data = overview_of(client_admin_a)["sections"]
        assert bool(data["required_overdue"]) is expect_overdue, f"offset {offset_days}"
        assert bool(data["required_due_soon"]) is expect_due_soon, f"offset {offset_days}"

    def test_a_ready_section_is_never_overdue(self, client_admin_a, tenant_a, admin_a):
        """An overdue badge on finished work is noise that trains people to
        ignore the badge."""
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        set_section(
            section,
            tenant_a,
            admin_a,
            status=SectionStatus.COMPLETE,
            due_date=_today() - timedelta(days=30),
        )
        section.refresh_from_db()
        assert section.readiness == Readiness.READY

        assert overview_of(client_admin_a)["sections"]["required_overdue"] == 0


# ---------------------------------------------------------------------------
# Attention queue
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAttentionQueue:
    def test_every_reason_has_a_rank_a_severity_and_a_module(self):
        """A reason missing from any of the three maps is a KeyError at request
        time -- or worse, a row whose module gate nobody checked."""
        from submission_operations.attention import REASON_MODULE, REASON_SEVERITY

        for reason in AttentionReason.values:
            assert reason in REASON_RANK, reason
            assert reason in REASON_SEVERITY, reason
            assert reason in REASON_MODULE, reason

    def test_the_documented_ranking_holds(self):
        """blocked < overdue < rejected workflow < due soon < not started < info."""
        assert REASON_RANK[AttentionReason.REQUIRED_SECTION_BLOCKED] == 1
        assert REASON_RANK[AttentionReason.OPEN_BLOCKER] == 1
        assert (
            REASON_RANK[AttentionReason.REQUIRED_SECTION_BLOCKED]
            < REASON_RANK[AttentionReason.OVERDUE_REQUIRED_SECTION]
            < REASON_RANK[AttentionReason.WORKFLOW_REJECTED]
            < REASON_RANK[AttentionReason.DUE_SOON_REQUIRED_SECTION]
            < REASON_RANK[AttentionReason.REQUIRED_SECTION_NOT_STARTED]
            < REASON_RANK[AttentionReason.STALE_UPGRADE_PLAN]
        )

    def test_severity_words_are_operational_not_regulatory(self):
        values = set(AttentionSeverity.values)
        assert values == {"blocked", "overdue", "attention", "informational"}
        for banned in ("major", "critical_deficiency", "deficiency", "agency"):
            assert banned not in values

    def test_rows_come_back_in_rank_order(self, client_admin_a, tenant_a, admin_a):
        from submission_dossiers.models import SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)

        blocked = make_section(dossier, tenant_a, admin_a, "A")
        set_section(blocked, tenant_a, admin_a, status=SectionStatus.BLOCKED)

        overdue = make_section(dossier, tenant_a, admin_a, "B")
        set_section(overdue, tenant_a, admin_a, due_date=_today() - timedelta(days=3))

        soon = make_section(dossier, tenant_a, admin_a, "C")
        set_section(soon, tenant_a, admin_a, due_date=_today() + timedelta(days=2))

        make_section(dossier, tenant_a, admin_a, "D")  # not started, no date

        payload = attention_of(client_admin_a)
        ranks = [REASON_RANK[r] for r in reasons_of(payload)]
        assert ranks == sorted(ranks), reasons_of(payload)

        codes = reasons_of(payload)
        assert AttentionReason.REQUIRED_SECTION_BLOCKED in codes
        assert AttentionReason.OVERDUE_REQUIRED_SECTION in codes
        assert AttentionReason.DUE_SOON_REQUIRED_SECTION in codes
        assert AttentionReason.REQUIRED_SECTION_NOT_STARTED in codes

    def test_ordering_is_stable_across_identical_rows(self, client_admin_a, tenant_a, admin_a):
        """Without a total order, pagination silently drops and repeats rows."""
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        due = _today() + timedelta(days=3)
        for code in ("A", "B", "C", "D", "E"):
            section = make_section(dossier, tenant_a, admin_a, code)
            set_section(section, tenant_a, admin_a, due_date=due)

        first = [r["resource_public_id"] for r in attention_of(client_admin_a)["results"]]
        second = [r["resource_public_id"] for r in attention_of(client_admin_a)["results"]]
        assert first == second

    def test_rows_carry_codes_not_generated_prose(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")

        row = attention_of(client_admin_a)["results"][0]
        assert set(row) == {
            "reason_code",
            "severity",
            "resource_type",
            "resource_public_id",
            "resource_label",
            "case_public_id",
            "dossier_public_id",
            "due_date",
            "operational_state",
        }
        assert row["reason_code"] in AttentionReason.values

    def test_an_open_blocker_produces_a_blocked_row(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a, title="Synthetic blocker text")

        payload = attention_of(client_admin_a)
        blocker_rows = [
            r for r in payload["results"] if r["reason_code"] == AttentionReason.OPEN_BLOCKER
        ]
        assert len(blocker_rows) == 1
        # The blocker's own title is tenant-authored prose about a problem and
        # is not echoed; the section code says where to look.
        assert "Synthetic blocker text" not in str(payload)

    def test_a_case_with_no_dossier_is_informational_not_urgent(
        self, client_admin_a, tenant_a, admin_a
    ):
        make_case(tenant_a, admin_a)
        payload = attention_of(client_admin_a)
        rows = [
            r
            for r in payload["results"]
            if r["reason_code"] == AttentionReason.CASE_WITH_NO_DOSSIER
        ]
        assert len(rows) == 1
        assert rows[0]["severity"] == AttentionSeverity.INFORMATIONAL

    def test_a_terminal_dossier_contributes_no_active_attention(
        self, client_admin_a, tenant_a, admin_a
    ):
        """Documented policy: active attention excludes terminal work. A
        completed dossier is history, and history does not need chasing."""
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        set_section(section, tenant_a, admin_a, due_date=_today() - timedelta(days=10))
        assert AttentionReason.OVERDUE_REQUIRED_SECTION in reasons_of(attention_of(client_admin_a))

        ds.cancel_dossier(dossier=dossier, tenant=tenant_a, actor=admin_a, reason="Synthetic")
        codes = reasons_of(attention_of(client_admin_a))
        assert AttentionReason.OVERDUE_REQUIRED_SECTION not in codes

    def test_filters_reject_values_outside_the_enum(self, client_admin_a):
        response = client_admin_a.get(f"{OPS_API}/attention/", {"severity": "catastrophic"})
        assert response.status_code == 400
        response = client_admin_a.get(f"{OPS_API}/attention/", {"reason_code": "../../etc"})
        assert response.status_code == 400

    def test_severity_filter_narrows_the_queue(self, client_admin_a, tenant_a, admin_a):
        from submission_dossiers.models import SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        blocked = make_section(dossier, tenant_a, admin_a, "A")
        set_section(blocked, tenant_a, admin_a, status=SectionStatus.BLOCKED)
        make_section(dossier, tenant_a, admin_a, "B")

        payload = attention_of(client_admin_a, severity=AttentionSeverity.BLOCKED)
        assert payload["results"]
        assert {r["severity"] for r in payload["results"]} == {AttentionSeverity.BLOCKED}
