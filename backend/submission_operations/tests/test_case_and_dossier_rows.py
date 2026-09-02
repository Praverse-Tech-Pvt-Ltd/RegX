"""The list surfaces, which reuse the same expressions as the overview.

Written because mutating the retired-section exclusion, the overdue boundary and
the tenant filter each turned only one test red -- all of them in the overview.
Every one of those expressions is also evaluated per-case, per-dossier and
per-owner, and a guard proven in one place and merely repeated in three is three
places nobody is checking.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from submission_operations import services
from submission_operations.tests.conftest import (
    OPS_API,
    add_blocker,
    make_case,
    make_dossier,
    make_section,
    set_section,
)


def _today():
    return timezone.localdate()


def _cases(client, **params):
    r = client.get(f"{OPS_API}/cases/", params)
    assert r.status_code == 200, r.data
    return r.data


def _dossiers(client, **params):
    r = client.get(f"{OPS_API}/dossiers/", params)
    assert r.status_code == 200, r.data
    return r.data


def _owners(client):
    r = client.get(f"{OPS_API}/owners/")
    assert r.status_code == 200, r.data
    return r.data["results"]


@pytest.mark.django_db
class TestCaseRows:
    def test_a_case_row_summarises_its_own_work(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a, title="Mine")
        dossier = make_dossier(case, tenant_a, admin_a)
        blocked = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(blocked, tenant_a, admin_a)
        overdue = make_section(dossier, tenant_a, admin_a, "B")
        set_section(overdue, tenant_a, admin_a, due_date=_today() - timedelta(days=4))

        row = _cases(client_admin_a)["results"][0]
        assert row["case_number"] == case.case_number
        assert row["dossiers"] == {"total": 1, "open": 1}
        assert row["sections"]["required_total"] == 2
        assert row["sections"]["overdue"] == 1
        assert row["open_blockers"] == 1
        assert row["internal_readiness"] == services.INTERNAL_READINESS_NOT_READY

    def test_case_row_completion_reads_m9_readiness_not_section_status(
        self, client_admin_a, tenant_a, admin_a
    ):
        """Constructed so the two disagree, which is the only state that can
        tell them apart.

        An open blocker means M9 derives NOT_READY however the user has set the
        status. A row inferring completion from status would call this done.
        """
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)
        set_section(section, tenant_a, admin_a, status=SectionStatus.COMPLETE)

        section.refresh_from_db()
        assert section.status == SectionStatus.COMPLETE
        assert section.readiness != Readiness.READY

        stats = _cases(client_admin_a)["results"][0]["sections"]
        assert stats["required_total"] == 1
        assert stats["required_complete"] == 0, "M9 is authoritative, not the status field"

    def test_case_rows_exclude_retired_sections(self, client_admin_a, tenant_a, admin_a):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")
        drop = make_section(dossier, tenant_a, admin_a, "B")
        set_section(drop, tenant_a, admin_a, due_date=_today() - timedelta(days=9))
        assert _cases(client_admin_a)["results"][0]["sections"]["required_total"] == 2

        ds.retire_section(section=drop, tenant=tenant_a, actor=admin_a)
        row = _cases(client_admin_a)["results"][0]
        assert row["sections"]["required_total"] == 1
        assert row["sections"]["overdue"] == 0, "a retired section is not outstanding work"

    def test_case_rows_count_only_this_tenants_work(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        case = make_case(tenant_a, admin_a, title="A case")
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")

        b_case = make_case(tenant_b, admin_b, title="B case")
        b_dossier = make_dossier(b_case, tenant_b, admin_b)
        for i in range(9):
            b_section = make_section(b_dossier, tenant_b, admin_b, f"B{i}")
            add_blocker(b_section, tenant_b, admin_b)
            set_section(b_section, tenant_b, admin_b, due_date=_today() - timedelta(days=1))

        rows = _cases(client_admin_a)["results"]
        assert len(rows) == 1
        assert rows[0]["sections"]["required_total"] == 1
        assert rows[0]["sections"]["overdue"] == 0
        assert rows[0]["open_blockers"] == 0

    def test_a_case_row_overdue_boundary_matches_the_documented_window(
        self, client_admin_a, tenant_a, admin_a
    ):
        """Today is due soon, not overdue. Off by one here means every team in
        the product is chased a day early."""
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        set_section(section, tenant_a, admin_a, due_date=_today())

        stats = _cases(client_admin_a)["results"][0]["sections"]
        assert stats["overdue"] == 0, "due today is not yet overdue"
        assert stats["due_soon"] == 1

    def test_case_search_and_status_filters_are_scoped_and_validated(
        self, client_admin_a, tenant_a, admin_a
    ):
        make_case(tenant_a, admin_a, title="Alpha")
        make_case(tenant_a, admin_a, title="Beta")

        assert _cases(client_admin_a, search="Alpha")["count"] == 1
        assert _cases(client_admin_a, status="open")["count"] == 2
        bad = client_admin_a.get(f"{OPS_API}/cases/", {"status": "nonsense"})
        assert bad.status_code == 400


@pytest.mark.django_db
class TestDossierRows:
    def test_a_dossier_row_reports_internal_readiness_from_m9(
        self, client_admin_a, tenant_a, admin_a
    ):
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        a = make_section(dossier, tenant_a, admin_a, "A")
        make_section(dossier, tenant_a, admin_a, "B")

        set_section(a, tenant_a, admin_a, status=SectionStatus.COMPLETE)
        a.refresh_from_db()
        assert a.readiness == Readiness.READY

        row = _dossiers(client_admin_a)["results"][0]
        assert row["required_total"] == 2
        assert row["required_complete"] == 1
        assert row["internal_readiness"] == services.INTERNAL_READINESS_PARTIAL

    def test_a_fully_ready_dossier_is_labelled_internally_ready(
        self, client_admin_a, tenant_a, admin_a
    ):
        from submission_dossiers.models import SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        for code in ("A", "B"):
            section = make_section(dossier, tenant_a, admin_a, code)
            set_section(section, tenant_a, admin_a, status=SectionStatus.COMPLETE)

        row = _dossiers(client_admin_a)["results"][0]
        assert row["internal_readiness"] == services.INTERNAL_READINESS_READY
        assert "internally" in row["internal_readiness"]

    def test_dossier_row_completion_reads_m9_readiness_not_section_status(
        self, client_admin_a, tenant_a, admin_a
    ):
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)
        set_section(section, tenant_a, admin_a, status=SectionStatus.COMPLETE)

        section.refresh_from_db()
        assert section.readiness != Readiness.READY

        row = _dossiers(client_admin_a)["results"][0]
        assert row["required_complete"] == 0
        assert row["internal_readiness"] == services.INTERNAL_READINESS_NOT_READY

    def test_dossier_rows_exclude_retired_sections(self, client_admin_a, tenant_a, admin_a):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")
        drop = make_section(dossier, tenant_a, admin_a, "B")
        set_section(drop, tenant_a, admin_a, due_date=_today() - timedelta(days=5))
        assert _dossiers(client_admin_a)["results"][0]["overdue_sections"] == 1

        ds.retire_section(section=drop, tenant=tenant_a, actor=admin_a)
        row = _dossiers(client_admin_a)["results"][0]
        assert row["required_total"] == 1
        assert row["overdue_sections"] == 0

    def test_dossier_rows_count_only_this_tenants_work(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a, title="A dossier")
        make_section(dossier, tenant_a, admin_a, "A")

        b_case = make_case(tenant_b, admin_b)
        b_dossier = make_dossier(b_case, tenant_b, admin_b, title="B dossier")
        for i in range(7):
            section = make_section(b_dossier, tenant_b, admin_b, f"B{i}")
            add_blocker(section, tenant_b, admin_b)

        rows = _dossiers(client_admin_a)["results"]
        assert len(rows) == 1
        assert rows[0]["required_total"] == 1
        assert rows[0]["open_blockers"] == 0

    def test_dossier_overdue_boundary_matches_the_documented_window(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        set_section(section, tenant_a, admin_a, due_date=_today())

        row = _dossiers(client_admin_a)["results"][0]
        assert row["overdue_sections"] == 0
        assert row["due_soon_sections"] == 1

    def test_the_readiness_filter_only_accepts_known_labels(
        self, client_admin_a, tenant_a, admin_a
    ):
        case = make_case(tenant_a, admin_a)
        make_dossier(case, tenant_a, admin_a)
        ok = client_admin_a.get(
            f"{OPS_API}/dossiers/",
            {"internal_readiness": services.INTERNAL_READINESS_NO_REQUIRED},
        )
        assert ok.status_code == 200
        bad = client_admin_a.get(f"{OPS_API}/dossiers/", {"internal_readiness": "ready"})
        assert bad.status_code == 400, "plain 'ready' is not a label this API emits"


@pytest.mark.django_db
class TestOwnerWorkload:
    def test_work_is_grouped_by_owner_with_unassigned_separate(
        self, client_admin_a, tenant_a, admin_a, doer_a
    ):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        owned = make_section(dossier, tenant_a, admin_a, "A")
        ds.update_section(section=owned, tenant=tenant_a, actor=admin_a, owner=doer_a)
        set_section(owned, tenant_a, admin_a, due_date=_today() - timedelta(days=3))
        make_section(dossier, tenant_a, admin_a, "B")  # unassigned

        rows = _owners(client_admin_a)
        by_owner = {(r["owner"] or {}).get("full_name"): r for r in rows}
        assert by_owner[doer_a.full_name]["outstanding"] == 1
        assert by_owner[doer_a.full_name]["overdue"] == 1
        unassigned = next(r for r in rows if r["unassigned"])
        assert unassigned["outstanding"] == 1
        assert unassigned["owner"] is None

    def test_owner_workload_excludes_retired_sections(
        self, client_admin_a, tenant_a, admin_a, doer_a
    ):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        ds.update_section(section=section, tenant=tenant_a, actor=admin_a, owner=doer_a)
        set_section(section, tenant_a, admin_a, due_date=_today() - timedelta(days=3))
        assert _owners(client_admin_a)

        ds.retire_section(section=section, tenant=tenant_a, actor=admin_a)
        assert _owners(client_admin_a) == [], "retired work is not somebody's workload"

    def test_owner_overdue_boundary_matches_the_documented_window(
        self, client_admin_a, tenant_a, admin_a, doer_a
    ):
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        ds.update_section(section=section, tenant=tenant_a, actor=admin_a, owner=doer_a)
        set_section(section, tenant_a, admin_a, due_date=_today())

        row = _owners(client_admin_a)[0]
        assert row["overdue"] == 0, "due today is not overdue"
        assert row["outstanding"] == 1

    def test_owner_workload_reads_m9_readiness_not_section_status(
        self, client_admin_a, tenant_a, admin_a, doer_a
    ):
        """Outstanding means "M9 does not call it ready", not "the user has not
        ticked complete"."""
        from submission_dossiers import services as ds
        from submission_dossiers.models import Readiness, SectionStatus

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        ds.update_section(section=section, tenant=tenant_a, actor=admin_a, owner=doer_a)
        add_blocker(section, tenant_a, admin_a)
        set_section(section, tenant_a, admin_a, status=SectionStatus.COMPLETE)

        section.refresh_from_db()
        assert section.status == SectionStatus.COMPLETE
        assert section.readiness != Readiness.READY

        row = _owners(client_admin_a)[0]
        assert row["outstanding"] == 1, "still outstanding: M9 is authoritative"


@pytest.mark.django_db
class TestAttentionOrderingEndToEnd:
    def test_the_first_rows_are_the_blocked_ones(self, client_admin_a, tenant_a, admin_a):
        """The ranking, asserted through the API rather than only against the
        rank table -- a correct table wired up wrongly still ships a wrong
        screen."""
        from submission_dossiers.models import SectionStatus
        from submission_operations.attention import AttentionSeverity

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)

        for code in ("N1", "N2", "N3"):
            make_section(dossier, tenant_a, admin_a, code)
        for code in ("D1", "D2"):
            s = make_section(dossier, tenant_a, admin_a, code)
            set_section(s, tenant_a, admin_a, due_date=_today() + timedelta(days=2))
        for code in ("O1", "O2"):
            s = make_section(dossier, tenant_a, admin_a, code)
            set_section(s, tenant_a, admin_a, due_date=_today() - timedelta(days=2))
        for code in ("B1", "B2"):
            s = make_section(dossier, tenant_a, admin_a, code)
            set_section(s, tenant_a, admin_a, status=SectionStatus.BLOCKED)

        r = client_admin_a.get(f"{OPS_API}/attention/", {"page_size": 50})
        severities = [row["severity"] for row in r.data["results"]]

        first_non_blocked = next(
            (i for i, s in enumerate(severities) if s != AttentionSeverity.BLOCKED),
            len(severities),
        )
        assert first_non_blocked >= 2, severities
        assert AttentionSeverity.BLOCKED not in severities[first_non_blocked:], severities

        overdue_at = severities.index(AttentionSeverity.OVERDUE)
        assert overdue_at >= first_non_blocked
        assert all(
            s != AttentionSeverity.OVERDUE
            for s in severities[: severities.index(AttentionSeverity.OVERDUE)]
            if s == AttentionSeverity.ATTENTION
        ), severities
