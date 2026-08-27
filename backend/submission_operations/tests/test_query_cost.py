"""Query growth, measured rather than assumed.

The requirement is **bounded**, not tiny. A dashboard reading seven domains will
issue a double-digit number of queries and that is fine; what is not fine is
that number growing with the number of rows. So every assertion here compares
counts across fixture sizes instead of pinning an absolute -- an absolute number
breaks on every harmless refactor and still would not catch the thing that
matters.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from submission_operations.tests.conftest import (
    OPS_API,
    add_blocker,
    make_case,
    make_dossier,
    make_section,
    set_section,
)


def _count(client, url, params=None):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url, params or {})
        assert response.status_code == 200, response.data
    return len(ctx.captured_queries)


def _build(tenant, actor, *, cases, dossiers_per_case=1, sections_per_dossier=3):
    """A realistic shape: cases, dossiers, sections, blockers, due dates."""
    today = timezone.localdate()
    for c in range(cases):
        case = make_case(tenant, actor, title=f"Case {c}")
        for d in range(dossiers_per_case):
            dossier = make_dossier(case, tenant, actor, title=f"Dossier {c}-{d}")
            for s in range(sections_per_dossier):
                section = make_section(dossier, tenant, actor, f"S{c}-{d}-{s}")
                if s == 0:
                    add_blocker(section, tenant, actor)
                if s == 1:
                    set_section(section, tenant, actor, due_date=today - timedelta(days=2))


@pytest.mark.django_db
class TestOverviewQueryCost:
    def test_overview_is_flat_across_tenant_size(self, client_admin_a, tenant_a, admin_a):
        # Build incrementally so each measurement sees a strictly larger tenant.
        counts = {}
        built = 0
        for target in (1, 20, 100):
            _build(tenant_a, admin_a, cases=target - built)
            built = target
            counts[target] = _count(client_admin_a, f"{OPS_API}/overview/")
        assert counts[1] == counts[20] == counts[100], counts


@pytest.mark.django_db
class TestListQueryCost:
    """Lists aggregate per page, so a bigger page costs no more queries."""

    def test_case_list_is_flat_across_page_size(self, client_admin_a, tenant_a, admin_a):
        _build(tenant_a, admin_a, cases=120)
        counts = {
            size: _count(client_admin_a, f"{OPS_API}/cases/", {"page_size": size})
            for size in (10, 50, 100)
        }
        assert counts[10] == counts[50] == counts[100], counts

    def test_dossier_list_is_flat_across_page_size(self, client_admin_a, tenant_a, admin_a):
        _build(tenant_a, admin_a, cases=40, dossiers_per_case=3)
        counts = {
            size: _count(client_admin_a, f"{OPS_API}/dossiers/", {"page_size": size})
            for size in (10, 50, 100)
        }
        assert counts[10] == counts[50] == counts[100], counts

    def test_attention_is_flat_across_tenant_size(self, client_admin_a, tenant_a, admin_a):
        counts = {}
        built = 0
        for target in (10, 60, 150):
            _build(tenant_a, admin_a, cases=target - built)
            built = target
            counts[target] = _count(client_admin_a, f"{OPS_API}/attention/")
        assert counts[10] == counts[60] == counts[150], counts

    def test_owner_workload_is_flat_across_owner_count(self, client_admin_a, tenant_a, admin_a):
        from submission_dossiers import services as ds
        from submission_operations.tests.conftest import _make_user, _membership_with_roles

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)

        counts = {}
        built = 0
        for target in (5, 25, 60):
            for i in range(built, target):
                from authorization.models import Role

                owner = _make_user(f"owner-{i}@example.test", f"Owner {i}")
                _membership_with_roles(tenant_a, owner, [Role.BuiltIn.DOER])
                section = make_section(dossier, tenant_a, admin_a, f"OW{i}")
                ds.update_section(section=section, tenant=tenant_a, actor=admin_a, owner=owner)
            built = target
            counts[target] = _count(client_admin_a, f"{OPS_API}/owners/", {"page_size": 200})
        assert counts[5] == counts[25] == counts[60], counts

    def test_recent_activity_is_flat_across_event_volume(self, client_admin_a, tenant_a, admin_a):
        counts = {}
        built = 0
        for target in (5, 40, 120):
            _build(tenant_a, admin_a, cases=target - built)
            built = target
            counts[target] = _count(client_admin_a, f"{OPS_API}/recent-activity/")
        assert counts[5] == counts[40] == counts[120], counts


@pytest.mark.django_db
class TestUpgradeStalenessIsBatched:
    """The known N+1 trap in this milestone.

    M11's `is_stale()` loads one dossier's sections per call. Calling it per plan
    would be one extra query per plan -- exactly the bug M11's own review caught
    in its plan list. The dashboard batches the loading and reuses M11's hash.
    """

    def test_dossier_list_upgrade_flags_do_not_grow_with_plan_count(
        self, client_admin_a, tenant_a, admin_a
    ):
        from dossier_blueprints import services as bp
        from dossier_upgrades import services as up

        counts = {}
        built = 0
        for target in (2, 8, 20):
            for i in range(built, target):
                blueprint = bp.create_blueprint(tenant=tenant_a, actor=admin_a, name=f"Outline {i}")
                v1 = bp.create_version(blueprint=blueprint, tenant=tenant_a, actor=admin_a)
                bp.create_section(
                    version=v1,
                    tenant=tenant_a,
                    actor=admin_a,
                    section_code="A",
                    title="Section A",
                )
                v1 = bp.activate_version(version=v1, tenant=tenant_a, actor=admin_a)
                case = make_case(tenant_a, admin_a, title=f"Upgrade case {i}")
                # instantiate_version returns the provenance record, not the
                # dossier -- the record is the governed artefact M10 exists for.
                instantiation = bp.instantiate_version(
                    version=v1,
                    tenant=tenant_a,
                    actor=admin_a,
                    case_public_id=case.public_id,
                    title=f"Instantiated {i}",
                )
                dossier = instantiation.dossier
                v2 = bp.create_version(
                    blueprint=blueprint, tenant=tenant_a, actor=admin_a, source_version=v1
                )
                bp.create_section(
                    version=v2,
                    tenant=tenant_a,
                    actor=admin_a,
                    section_code="B",
                    title="Section B",
                )
                v2 = bp.activate_version(version=v2, tenant=tenant_a, actor=admin_a)
                up.generate_plan(
                    dossier=dossier,
                    tenant=tenant_a,
                    actor=admin_a,
                    target_version_public_id=v2.public_id,
                )
            built = target
            counts[target] = _count(client_admin_a, f"{OPS_API}/dossiers/", {"page_size": 100})
        assert counts[2] == counts[8] == counts[20], counts


@pytest.mark.django_db
class TestReadinessFilterQueryCost:
    """The filter must not trade a flat query count for a correct answer.

    Pushed into the queryset as an annotation, so the paginator counts and
    slices the filtered set in SQL. Materialising every dossier to filter in
    Python would give the same answer and grow with the tenant.
    """

    def _sizes(self, client, tenant, actor, params):
        counts = {}
        built = 0
        for target in (1, 20, 100, 500):
            _build(tenant, actor, cases=target - built, sections_per_dossier=2)
            built = target
            counts[target] = _count(client, f"{OPS_API}/dossiers/", params)
        return counts

    def test_flat_with_the_filter_off(self, client_admin_a, tenant_a, admin_a):
        counts = self._sizes(client_admin_a, tenant_a, admin_a, {"page_size": 25})
        assert len(set(counts.values())) == 1, counts

    def test_flat_with_the_filter_on(self, client_admin_a, tenant_a, admin_a):
        counts = self._sizes(
            client_admin_a,
            tenant_a,
            admin_a,
            {"page_size": 25, "internal_readiness": "internally_not_ready"},
        )
        assert len(set(counts.values())) == 1, counts

    def test_the_filter_costs_no_extra_queries(self, client_admin_a, tenant_a, admin_a):
        """Filtering narrows the same query rather than adding one."""
        _build(tenant_a, admin_a, cases=60, sections_per_dossier=2)
        off = _count(client_admin_a, f"{OPS_API}/dossiers/", {"page_size": 25})
        on = _count(
            client_admin_a,
            f"{OPS_API}/dossiers/",
            {"page_size": 25, "internal_readiness": "internally_not_ready"},
        )
        assert on == off, f"filter off={off} on={on}"
