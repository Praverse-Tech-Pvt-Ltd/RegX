"""The attention scan's cap is applied by the database, not afterwards.

MEASURED BEFORE THE FIX (dicts built in order to keep at most 500):

    sections     kept   dicts built   queries carrying LIMIT
        10         10            10                 1 of 9
       100        100           100                 1 of 9
       600        500           600                 1 of 9
      1200        500          1200                 1 of 9

`add()` received an already-evaluated list comprehension, so the database
returned every candidate row and Python built a dict for each one before the cap
was applied. The cap bounded what was *displayed* and nothing else -- which is
the failure mode a query-count test cannot see, because the count was flat at 9
the whole time.

AFTER: dicts built is 500 at both 600 and 1200 sections, and all nine queries
carry a LIMIT.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from submission_operations import services
from submission_operations.projection import Visibility
from submission_operations.services import ATTENTION_SCAN_LIMIT
from submission_operations.tests.conftest import make_case, make_dossier, make_section

pytestmark = pytest.mark.slow


def _visibility_all():
    return Visibility(
        cases=True,
        dossiers=True,
        documents=True,
        workflows=True,
        checklists=True,
        blueprints=True,
        upgrades=True,
    )


def _sections(tenant, actor, count):
    """A dossier of required sections, all NOT_STARTED with no due date.

    That is the natural state of a newly created required section and is one of
    the attention scan's own branches, so the candidate set is `count` without
    writing to a governed row directly.
    """
    case = make_case(tenant, actor)
    dossier = make_dossier(case, tenant, actor)
    for i in range(count):
        make_section(dossier, tenant, actor, code=f"S{i}", required=True)
    return dossier


def _run(tenant, monkeypatch):
    """Run the scan, counting how many row dicts get built."""
    built = []
    real = services._section_row

    def counted(section, reason, visibility):
        built.append(1)
        return real(section, reason, visibility)

    monkeypatch.setattr(services, "_section_row", counted)
    with CaptureQueriesContext(connection) as ctx:
        rows, truncated = services.attention_rows(tenant=tenant, visibility=_visibility_all())
    return rows, truncated, len(built), ctx


@pytest.mark.django_db
class TestScanCapIsAppliedInSql:
    def test_work_stops_growing_once_past_the_cap(self, tenant_a, admin_a, monkeypatch):
        """THE regression test.

        Twice the cap must cost the same work as the cap, because the database
        was asked for a bounded set. Before the fix this built 1200 dicts to
        display 500.
        """
        _sections(tenant_a, admin_a, ATTENTION_SCAN_LIMIT * 2)
        rows, truncated, built, _ctx = _run(tenant_a, monkeypatch)

        assert truncated is True
        assert len(rows) == ATTENTION_SCAN_LIMIT
        assert built <= ATTENTION_SCAN_LIMIT, (
            f"built {built} row dicts for a cap of {ATTENTION_SCAN_LIMIT}; "
            "the cap is being applied after the work rather than before it"
        )

    def test_every_scan_query_carries_an_outer_limit(self, tenant_a, admin_a, monkeypatch):
        """A scan that means to bound its work has to say so in SQL.

        The LIMIT has to be the **outer** one. Searching the statement for the
        substring is not enough: an `Exists()` annotation compiles to a
        subquery ending `LIMIT 1`, so a completely unbounded outer query still
        contains the word. An earlier version of this test was fooled by exactly
        that and passed against a branch that read the whole table.

        Django emits the outer limit last, so the check is on the tail of the
        statement rather than on its contents.
        """
        import re

        _sections(tenant_a, admin_a, 40)
        _rows, _truncated, _built, ctx = _run(tenant_a, monkeypatch)

        tail = re.compile(r"LIMIT\s+\d+\s*(OFFSET\s+\d+\s*)?$", re.IGNORECASE)
        unlimited = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].upper().lstrip().startswith("SELECT") and not tail.search(q["sql"].strip())
        ]
        assert unlimited == [], f"{len(unlimited)} scan queries have no outer LIMIT: " + "; ".join(
            s[:120] for s in unlimited
        )

    def test_below_the_cap_nothing_is_lost(self, tenant_a, admin_a, monkeypatch):
        """The bound must not become a silent truncation of small tenants."""
        _sections(tenant_a, admin_a, 12)
        rows, truncated, built, _ctx = _run(tenant_a, monkeypatch)

        assert truncated is False
        assert len(rows) == 12
        assert built == 12

    def test_exactly_at_the_cap_is_not_reported_as_truncated(self, tenant_a, admin_a, monkeypatch):
        """The reason the slice asks for one more than the cap: this case."""
        _sections(tenant_a, admin_a, ATTENTION_SCAN_LIMIT)
        rows, truncated, _built, _ctx = _run(tenant_a, monkeypatch)

        assert len(rows) == ATTENTION_SCAN_LIMIT
        assert truncated is False

    def test_query_count_does_not_grow_with_the_data(self, tenant_a, admin_a, monkeypatch):
        """Compared across sizes rather than pinned to a number."""
        counts = []
        for target in (10, 60, 300):
            _sections(tenant_a, admin_a, target)
            _rows, _truncated, _built, ctx = _run(tenant_a, monkeypatch)
            counts.append((target, len(ctx.captured_queries)))

        distinct = {c for _size, c in counts}
        assert len(distinct) == 1, f"query count grows with the data: {counts}"


@pytest.mark.django_db
class TestPrivacyIsUnchanged:
    """A performance refactor must not widen what a caller can see.

    The scan builds rows through the same `_section_row` and `_case_row`
    helpers, which take `visibility` and blank the fields a restricted caller
    may not have. Rebuilding the call sites is exactly the kind of change that
    quietly drops that argument.
    """

    def test_a_restricted_module_contributes_nothing(self, tenant_a, admin_a, monkeypatch):
        _sections(tenant_a, admin_a, 5)
        visibility = Visibility(
            cases=False,
            dossiers=False,
            documents=False,
            workflows=False,
            checklists=False,
            blueprints=False,
            upgrades=False,
        )
        rows, truncated = services.attention_rows(tenant=tenant_a, visibility=visibility)
        assert rows == []
        assert truncated is False

    def test_case_identity_is_withheld_when_cases_are_restricted(self, tenant_a, admin_a):
        _sections(tenant_a, admin_a, 3)
        visibility = Visibility(
            cases=False,
            dossiers=True,
            documents=True,
            workflows=True,
            checklists=True,
            blueprints=True,
            upgrades=True,
        )
        rows, _truncated = services.attention_rows(tenant=tenant_a, visibility=visibility)
        assert rows, "the dossier branch should still contribute"
        assert all(row["case_public_id"] is None for row in rows)

    def test_tenant_isolation_survives_the_refactor(self, tenant_a, admin_a, tenant_b, admin_b):
        """A faster cross-tenant leak is not an improvement."""
        _sections(tenant_a, admin_a, 4)
        _sections(tenant_b, admin_b, 7)

        rows, _truncated = services.attention_rows(tenant=tenant_a, visibility=_visibility_all())
        b_ids = {
            str(s.public_id)
            for s in __import__(
                "submission_dossiers.models", fromlist=["DossierSection"]
            ).DossierSection.objects.filter(tenant=tenant_b)
        }
        assert not ({str(r["resource_public_id"]) for r in rows} & b_ids)
