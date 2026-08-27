"""The internal-readiness filter, and where it has to happen.

Filtering a materialised page instead of the queryset makes `count` describe the
unfiltered set and hides every match that falls on a later page: a filtered first
page comes back empty while the matching dossier sits at position 80, then
appears on page 4 as if it had been there all along. Almost every test here is
built to be larger than one page for exactly that reason -- a single-page fixture
cannot tell the two implementations apart.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import pytest

from submission_operations import services
from submission_operations.tests.conftest import (
    OPS_API,
    add_blocker,
    make_case,
    make_dossier,
    make_section,
    set_section,
)

PAGE_SIZE = 25  # the project default, and the thing this bug hid behind


def _complete(section, tenant, actor):
    from submission_dossiers.models import SectionStatus

    set_section(section, tenant, actor, status=SectionStatus.COMPLETE)


def _dossiers(client, **params):
    r = client.get(f"{OPS_API}/dossiers/", params)
    assert r.status_code == 200, r.data
    return r.data


def _titles(payload):
    return [row["title"] for row in payload["results"]]


@pytest.fixture
def many_dossiers(tenant_a, admin_a):
    """More dossiers than one page, with exactly one of each interesting label.

    The ready / partial / no-required dossiers are created LAST so they sort to
    the front by `-updated_at`... which is precisely why each test asserts by
    identity rather than position.
    """
    case = make_case(tenant_a, admin_a)
    built = {}

    # 40 plainly not-ready dossiers, more than one page on their own.
    for i in range(40):
        d = make_dossier(case, tenant_a, admin_a, title=f"Not ready {i:02d}")
        make_section(d, tenant_a, admin_a, f"NR{i}-A")
        make_section(d, tenant_a, admin_a, f"NR{i}-B")
    built["not_ready_count"] = 40

    ready = make_dossier(case, tenant_a, admin_a, title="The ready one")
    for code in ("R-A", "R-B"):
        _complete(make_section(ready, tenant_a, admin_a, code), tenant_a, admin_a)
    built["ready"] = ready

    partial = make_dossier(case, tenant_a, admin_a, title="The partial one")
    _complete(make_section(partial, tenant_a, admin_a, "P-A"), tenant_a, admin_a)
    make_section(partial, tenant_a, admin_a, "P-B")
    built["partial"] = partial

    empty = make_dossier(case, tenant_a, admin_a, title="The empty one")
    built["empty"] = empty

    built["case"] = case
    return built


@pytest.mark.django_db
class TestReadinessFilterPagination:
    def test_a_match_beyond_the_first_page_is_still_returned(
        self, client_admin_a, tenant_a, admin_a
    ):
        """The exact defect, reproduced.

        Builds its own data rather than reusing `many_dossiers`, because the
        ordering has to be controlled: the list sorts by the DOSSIER's
        `updated_at`, so the one match is created FIRST and forty others after
        it, putting it last and well past page one.
        """
        case = make_case(tenant_a, admin_a)

        ready = make_dossier(case, tenant_a, admin_a, title="The only ready one")
        _complete(make_section(ready, tenant_a, admin_a, "R"), tenant_a, admin_a)

        for i in range(40):
            d = make_dossier(case, tenant_a, admin_a, title=f"Not ready {i:02d}")
            make_section(d, tenant_a, admin_a, f"NR{i}")

        unfiltered = _dossiers(client_admin_a, page_size=PAGE_SIZE, page=1)
        assert unfiltered["count"] == 41
        assert "The only ready one" not in _titles(unfiltered), (
            "precondition: the match is genuinely not on the first page"
        )

        filtered = _dossiers(
            client_admin_a,
            page_size=PAGE_SIZE,
            page=1,
            internal_readiness=services.INTERNAL_READINESS_READY,
        )
        assert filtered["count"] == 1, "count must describe the FILTERED set, not all 41"
        assert _titles(filtered) == ["The only ready one"]

    def test_the_match_is_not_hiding_on_a_later_page_either(
        self, client_admin_a, tenant_a, admin_a
    ):
        """The other half of the defect: a broken filter leaks the match onto
        whichever page it happens to fall on, so a filtered page 2 would show
        it while page 1 showed nothing."""
        case = make_case(tenant_a, admin_a)
        ready = make_dossier(case, tenant_a, admin_a, title="The only ready one")
        _complete(make_section(ready, tenant_a, admin_a, "R"), tenant_a, admin_a)
        for i in range(40):
            d = make_dossier(case, tenant_a, admin_a, title=f"Not ready {i:02d}")
            make_section(d, tenant_a, admin_a, f"NR{i}")

        # Page 2 of the UNFILTERED set is real...
        assert (
            client_admin_a.get(
                f"{OPS_API}/dossiers/", {"page_size": PAGE_SIZE, "page": 2}
            ).status_code
            == 200
        )
        # ...and page 2 of the FILTERED set does not exist, because one match is
        # one page. A filter applied after slicing would have made this page
        # real and put the match on it.
        page_two = client_admin_a.get(
            f"{OPS_API}/dossiers/",
            {
                "page_size": PAGE_SIZE,
                "page": 2,
                "internal_readiness": services.INTERNAL_READINESS_READY,
            },
        )
        assert page_two.status_code == 404, page_two.data

    def test_the_paginator_count_is_the_filtered_count(self, client_admin_a, many_dossiers):
        assert _dossiers(client_admin_a)["count"] == 43
        for label, expected in [
            (services.INTERNAL_READINESS_READY, 1),
            (services.INTERNAL_READINESS_PARTIAL, 1),
            (services.INTERNAL_READINESS_NO_REQUIRED, 1),
            (services.INTERNAL_READINESS_NOT_READY, 40),
        ]:
            payload = _dossiers(client_admin_a, internal_readiness=label)
            assert payload["count"] == expected, label

    def test_page_count_follows_the_filtered_set(self, client_admin_a, many_dossiers):
        """40 not-ready dossiers at page_size 25 is two pages, and the second
        page must exist and be full of matches."""
        first = _dossiers(
            client_admin_a,
            page_size=PAGE_SIZE,
            internal_readiness=services.INTERNAL_READINESS_NOT_READY,
        )
        assert first["count"] == 40
        assert len(first["results"]) == PAGE_SIZE
        assert first["next"] is not None

        second = _dossiers(
            client_admin_a,
            page_size=PAGE_SIZE,
            page=2,
            internal_readiness=services.INTERNAL_READINESS_NOT_READY,
        )
        assert len(second["results"]) == 15
        assert second["next"] is None
        for row in second["results"]:
            assert row["internal_readiness"] == services.INTERNAL_READINESS_NOT_READY

    def test_a_filtered_page_never_contains_a_non_matching_row(self, client_admin_a, many_dossiers):
        for label in services.INTERNAL_READINESS_VALUES:
            payload = _dossiers(client_admin_a, page_size=100, internal_readiness=label)
            for row in payload["results"]:
                assert row["internal_readiness"] == label, label
            assert payload["count"] == len(payload["results"]), label


@pytest.mark.django_db
class TestEachLabelFilters:
    def test_no_required_sections(self, client_admin_a, many_dossiers):
        payload = _dossiers(
            client_admin_a, internal_readiness=services.INTERNAL_READINESS_NO_REQUIRED
        )
        assert _titles(payload) == ["The empty one"]

    def test_internally_ready(self, client_admin_a, many_dossiers):
        payload = _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_READY)
        assert _titles(payload) == ["The ready one"]

    def test_internally_partially_ready(self, client_admin_a, many_dossiers):
        payload = _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_PARTIAL)
        assert _titles(payload) == ["The partial one"]

    def test_internally_not_ready(self, client_admin_a, many_dossiers):
        payload = _dossiers(
            client_admin_a,
            page_size=100,
            internal_readiness=services.INTERNAL_READINESS_NOT_READY,
        )
        assert payload["count"] == 40
        assert all(t.startswith("Not ready") for t in _titles(payload))


@pytest.mark.django_db
class TestFilterAgreesWithTheRowItReturns:
    def test_the_sql_filter_and_the_python_label_agree_for_every_dossier(
        self, client_admin_a, many_dossiers
    ):
        """The differential test.

        `filter_by_internal_readiness` is a second expression of the rule in
        `internal_readiness_label` -- one in SQL, one in Python -- and two
        implementations drift. This partitions the whole tenant by the SQL
        filter and asserts the partition matches what the rows themselves say,
        so a change to one that is not made to the other turns red.
        """
        everything = _dossiers(client_admin_a, page_size=200)
        by_label: dict[str, set[str]] = {}
        for row in everything["results"]:
            by_label.setdefault(row["internal_readiness"], set()).add(row["public_id"])

        seen: set[str] = set()
        for label in services.INTERNAL_READINESS_VALUES:
            filtered = _dossiers(client_admin_a, page_size=200, internal_readiness=label)
            ids = {row["public_id"] for row in filtered["results"]}
            assert ids == by_label.get(label, set()), label
            seen |= ids

        assert seen == {row["public_id"] for row in everything["results"]}, (
            "the four labels must partition the set exactly -- no dossier "
            "unclassified, none counted twice"
        )


@pytest.mark.django_db
class TestFilterRespectsSectionSemantics:
    def test_retired_sections_do_not_affect_the_filter(self, client_admin_a, tenant_a, admin_a):
        """A retired incomplete section must not keep a dossier out of the ready
        bucket -- retirement is withdrawal, not outstanding work."""
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a, title="Retired then ready")
        _complete(make_section(dossier, tenant_a, admin_a, "A"), tenant_a, admin_a)
        drop = make_section(dossier, tenant_a, admin_a, "B")

        assert (
            _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_READY)["count"]
            == 0
        )

        ds.retire_section(section=drop, tenant=tenant_a, actor=admin_a)
        payload = _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_READY)
        assert _titles(payload) == ["Retired then ready"]

    def test_optional_sections_do_not_affect_the_filter(self, client_admin_a, tenant_a, admin_a):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a, title="Optional left open")
        _complete(make_section(dossier, tenant_a, admin_a, "A"), tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "OPT", required=False)

        payload = _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_READY)
        assert _titles(payload) == ["Optional left open"]

    def test_the_filter_reads_m9_readiness_not_section_status(
        self, client_admin_a, tenant_a, admin_a
    ):
        """A section marked COMPLETE that M9 still calls NOT_READY, because it
        carries an open blocker. A filter inferring from status would put this
        dossier in the ready bucket."""
        from submission_dossiers.models import Readiness

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a, title="Blocked but ticked")
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)
        _complete(section, tenant_a, admin_a)

        section.refresh_from_db()
        assert section.readiness != Readiness.READY

        assert (
            _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_READY)["count"]
            == 0
        )
        assert _titles(
            _dossiers(client_admin_a, internal_readiness=services.INTERNAL_READINESS_NOT_READY)
        ) == ["Blocked but ticked"]

    def test_a_terminal_dossier_is_filtered_on_the_same_terms_as_it_is_listed(
        self, client_admin_a, tenant_a, admin_a
    ):
        """M12 lists terminal dossiers as history, and `dossier_rows` counts
        their required sections. The filter must use exactly those numbers, or a
        filtered list would disagree with the rows it returns."""
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a, title="Completed history")
        _complete(make_section(dossier, tenant_a, admin_a, "A"), tenant_a, admin_a)
        ds.complete_dossier(dossier=dossier, tenant=tenant_a, actor=admin_a)

        listed = _dossiers(client_admin_a)["results"]
        row = next(r for r in listed if r["title"] == "Completed history")
        filtered = _dossiers(client_admin_a, internal_readiness=row["internal_readiness"])
        assert row["public_id"] in {r["public_id"] for r in filtered["results"]}

    def test_an_invalid_label_is_rejected_rather_than_ignored(self, client_admin_a):
        r = client_admin_a.get(f"{OPS_API}/dossiers/", {"internal_readiness": "ready"})
        assert r.status_code == 400, "plain 'ready' is not a label this API emits"
        r = client_admin_a.get(f"{OPS_API}/dossiers/", {"internal_readiness": "'; DROP TABLE--"})
        assert r.status_code == 400


@pytest.mark.django_db
class TestFilterTenantIsolation:
    def test_another_tenants_matches_do_not_reach_the_filtered_count(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        """Tenant B is full of ready dossiers. Tenant A has one."""
        b_case = make_case(tenant_b, admin_b)
        for i in range(30):
            d = make_dossier(b_case, tenant_b, admin_b, title=f"B ready {i}")
            _complete(make_section(d, tenant_b, admin_b, f"B{i}"), tenant_b, admin_b)

        a_case = make_case(tenant_a, admin_a)
        a_ready = make_dossier(a_case, tenant_a, admin_a, title="A ready")
        _complete(make_section(a_ready, tenant_a, admin_a, "A"), tenant_a, admin_a)

        payload = _dossiers(
            client_admin_a,
            page_size=100,
            internal_readiness=services.INTERNAL_READINESS_READY,
        )
        assert payload["count"] == 1
        assert _titles(payload) == ["A ready"]
        assert "B ready" not in str(payload)

    def test_the_mirror_holds_for_tenant_b(
        self, client_admin_b, tenant_a, admin_a, tenant_b, admin_b
    ):
        a_case = make_case(tenant_a, admin_a)
        for i in range(5):
            d = make_dossier(a_case, tenant_a, admin_a, title=f"A ready {i}")
            _complete(make_section(d, tenant_a, admin_a, f"A{i}"), tenant_a, admin_a)

        b_case = make_case(tenant_b, admin_b)
        b = make_dossier(b_case, tenant_b, admin_b, title="B only")
        _complete(make_section(b, tenant_b, admin_b, "B"), tenant_b, admin_b)

        payload = _dossiers(
            client_admin_b,
            page_size=100,
            internal_readiness=services.INTERNAL_READINESS_READY,
        )
        assert payload["count"] == 1
        assert _titles(payload) == ["B only"]
