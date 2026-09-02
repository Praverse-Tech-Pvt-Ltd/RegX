"""Tenant isolation, multi-gate authorization, DB governance, concurrency, cost.

The service layer answers first with clean 4xx. It is not the guarantee:
`Model.save()` resolves through `_base_manager` -- a plain `Manager` Django
auto-creates, not `objects` -- so restricting the public manager cannot cover
it, and a raw cursor never runs a line of Python.

Synthetic data only; generic section codes.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from dossier_upgrades import services
from dossier_upgrades.models import (
    ChangeType,
    DossierUpgradeApplication,
    DossierUpgradePlan,
    DossierUpgradePlanItem,
    ItemStatus,
    PlanStatus,
    UpgradeMutationForbidden,
    UpgradeSectionOrigin,
)
from dossier_upgrades.tests.conftest import (
    PLAN_API,
    accept_all,
    activate,
    draft_from,
    generate,
    make_blueprint_section,
    make_case,
    publish,
)

PLAN_TABLE = DossierUpgradePlan._meta.db_table
ITEM_TABLE = DossierUpgradePlanItem._meta.db_table
APPLICATION_TABLE = DossierUpgradeApplication._meta.db_table
ORIGIN_TABLE = UpgradeSectionOrigin._meta.db_table
DB_ERRORS = (InternalError, ProgrammingError)

DOSSIER_API = "/api/regx/v1/submission-dossiers"


def _sql(statement, params=()):
    """One statement in its own savepoint, so a refusal stays local."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def item_for(plan, change_type, code=None):
    for item in plan.items.all():
        if item.change_type == change_type and (code is None or item.section_code == code):
            return item
    return None


@pytest.fixture
def applied_plan(dossier_a, v2, tenant_a, admin_a):
    plan = generate(dossier_a, tenant_a, admin_a, v2)
    accept_all(plan, tenant_a, admin_a)
    application = services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
    plan.refresh_from_db()
    return plan, application


@pytest.fixture
def tenant_b_setup(db, tenant_b, admin_b):
    """A full, valid dossier-from-blueprint in tenant B."""
    from dossier_blueprints import services as bp

    blueprint = bp.create_blueprint(tenant=tenant_b, actor=admin_b, name="Outline B")
    v1 = publish(blueprint, tenant_b, admin_b, [("A", None, {}), ("B", None, {})])
    case = make_case(tenant_b, admin_b)
    record = bp.instantiate_version(
        version=v1,
        tenant=tenant_b,
        actor=admin_b,
        case_public_id=case.public_id,
        title="Tenant B dossier",
    )
    draft = draft_from(v1, tenant_b, admin_b)
    make_blueprint_section(draft, tenant_b, admin_b, "C")
    v2 = activate(draft, tenant_b, admin_b)
    plan = generate(record.dossier, tenant_b, admin_b, v2)
    return {"dossier": record.dossier, "v1": v1, "v2": v2, "plan": plan}


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    def test_plan_list_shows_only_this_tenant(
        self, client_admin_a, dossier_a, v2, tenant_a, admin_a, tenant_b_setup
    ):
        mine = generate(dossier_a, tenant_a, admin_a, v2)
        r = client_admin_a.get(f"{DOSSIER_API}/{dossier_a.public_id}/upgrade-plans/")
        ids = {row["public_id"] for row in r.data["results"]}
        assert str(mine.public_id) in ids
        assert str(tenant_b_setup["plan"].public_id) not in ids

    def test_cross_tenant_plan_is_404_not_403(self, client_admin_a, tenant_b_setup):
        """404, so the response cannot confirm the row exists."""
        r = client_admin_a.get(f"{PLAN_API}/{tenant_b_setup['plan'].public_id}/")
        assert r.status_code == 404

    def test_cross_tenant_dossier_is_404(self, client_admin_a, tenant_b_setup):
        r = client_admin_a.get(
            f"{DOSSIER_API}/{tenant_b_setup['dossier'].public_id}/upgrade-plans/"
        )
        assert r.status_code == 404

    def test_cross_tenant_apply_is_404(self, client_admin_a, tenant_b_setup):
        r = client_admin_a.post(f"{PLAN_API}/{tenant_b_setup['plan'].public_id}/apply/")
        assert r.status_code == 404
        tenant_b_setup["plan"].refresh_from_db()
        assert tenant_b_setup["plan"].status == PlanStatus.DRAFT

    def test_cross_tenant_item_review_is_404(self, client_admin_a, tenant_b_setup):
        item = tenant_b_setup["plan"].items.first()
        r = client_admin_a.post(
            f"{PLAN_API}/{tenant_b_setup['plan'].public_id}/items/{item.public_id}/accept/"
        )
        assert r.status_code == 404

    def test_cross_tenant_history_is_404(self, client_admin_a, tenant_b_setup):
        r = client_admin_a.get(
            f"{DOSSIER_API}/{tenant_b_setup['dossier'].public_id}/upgrade-history/"
        )
        assert r.status_code == 404

    def test_a_target_version_from_another_tenant_is_refused(
        self, dossier_a, tenant_a, admin_a, tenant_b_setup
    ):
        with pytest.raises(services.InvalidTarget):
            generate(dossier_a, tenant_a, admin_a, tenant_b_setup["v2"])

    def test_the_service_tenant_gate_refuses_a_foreign_plan(
        self, tenant_a, admin_a, tenant_b_setup
    ):
        """Isolates `_assert_tenant` from the view's tenant filter.

        Most cross-tenant paths are stopped twice; these call the service
        directly with a foreign object, so only the service gate can refuse.
        """
        foreign = tenant_b_setup["plan"]
        for call in (
            lambda: services.cancel_plan(plan=foreign, tenant=tenant_a, actor=admin_a),
            lambda: services.mark_ready(plan=foreign, tenant=tenant_a, actor=admin_a),
            lambda: services.regenerate_plan(plan=foreign, tenant=tenant_a, actor=admin_a),
            lambda: services.apply_plan(plan=foreign, tenant=tenant_a, actor=admin_a),
        ):
            with pytest.raises(DossierUpgradePlan.DoesNotExist):
                call()
        foreign.refresh_from_db()
        assert foreign.status == PlanStatus.DRAFT

    def test_the_service_tenant_gate_refuses_a_foreign_item(
        self, tenant_a, admin_a, tenant_b_setup
    ):
        item = tenant_b_setup["plan"].items.first()
        with pytest.raises(DossierUpgradePlanItem.DoesNotExist):
            services.set_item_status(item=item, tenant=tenant_a, actor=admin_a, accept=True)


# ---------------------------------------------------------------------------
# Multi-gate authorization
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMultiGateAuthorization:
    def test_upgrade_view_alone_does_not_permit_apply(
        self, client_support_a, support_a, tenant_a, dossier_a, v2, admin_a
    ):
        """PLATFORM_SUPPORT holds `dossier_upgrades.view` and no
        `submission_dossiers.manage_sections`. Gate 1 is not enough."""
        from dossier_upgrades.permissions import PERM_VIEW, has_upgrade_permission
        from submission_dossiers.permissions import (
            PERM_MANAGE_SECTIONS,
            has_dossier_permission,
        )

        assert has_upgrade_permission(support_a, tenant_a, PERM_VIEW) is True
        assert has_dossier_permission(support_a, tenant_a, PERM_MANAGE_SECTIONS) is False

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        r = client_support_a.post(f"{PLAN_API}/{plan.public_id}/apply/")
        assert r.status_code == 403
        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY

    def test_dossier_manage_sections_is_required_at_the_service(
        self, dossier_a, v2, tenant_a, admin_a, reviewer_a
    ):
        """REVIEWER holds no `dossier_upgrades.apply` and no
        `submission_dossiers.manage_sections`; the service gate refuses even if
        the view gate were passed."""
        from submission_dossiers.permissions import (
            PERM_MANAGE_SECTIONS,
            has_dossier_permission,
        )

        assert has_dossier_permission(reviewer_a, tenant_a, PERM_MANAGE_SECTIONS) is False
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        with pytest.raises(services.InvalidTarget):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=reviewer_a)
        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY

    def test_blueprint_view_is_required_to_generate(
        self, dossier_a, v2, tenant_a, admin_a, monkeypatch
    ):
        """Reading a blueprint version needs the blueprint's own permission,
        checked before the target is resolved."""
        import dossier_upgrades.services as svc
        from dossier_blueprints import permissions as bp_perms

        monkeypatch.setattr(bp_perms, "has_blueprint_permission", lambda *a, **k: False)
        with pytest.raises(services.InvalidTarget):
            generate(dossier_a, tenant_a, admin_a, v2)
        assert svc

    def test_the_refusal_is_indistinguishable_from_a_missing_target(
        self, dossier_a, v2, tenant_a, admin_a, monkeypatch
    ):
        """An unauthorised caller and a nonexistent version must produce the
        same answer, or the endpoint is an existence oracle."""
        import uuid

        from dossier_blueprints import permissions as bp_perms

        with pytest.raises(services.InvalidTarget) as absent:
            services.generate_plan(
                dossier=dossier_a,
                tenant=tenant_a,
                actor=admin_a,
                target_version_public_id=uuid.uuid4(),
            )
        monkeypatch.setattr(bp_perms, "has_blueprint_permission", lambda *a, **k: False)
        with pytest.raises(services.InvalidTarget) as unauthorised:
            generate(dossier_a, tenant_a, admin_a, v2)
        assert str(absent.value) == str(unauthorised.value)

    def test_a_refused_apply_emits_no_success_audit(
        self, dossier_a, v2, tenant_a, admin_a, reviewer_a
    ):
        from audit.models import AuditEvent

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        before = AuditEvent.objects.filter(event_type="dossier_upgrade.plan_applied").count()
        with pytest.raises(services.InvalidTarget):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=reviewer_a)
        assert (
            AuditEvent.objects.filter(event_type="dossier_upgrade.plan_applied").count() == before
        )

    def test_a_doer_can_generate_review_and_apply(
        self, client_doer_a, dossier_a, v2, tenant_a, doer_a
    ):
        """The intended path must actually work for the role meant to do it."""
        r = client_doer_a.post(
            f"{DOSSIER_API}/{dossier_a.public_id}/upgrade-plans/",
            {"target_blueprint_version_public_id": str(v2.public_id)},
            format="json",
        )
        assert r.status_code == 201, r.data
        plan = DossierUpgradePlan.objects.get(public_id=r.data["public_id"])
        accept_all(plan, tenant_a, doer_a)
        assert client_doer_a.post(f"{PLAN_API}/{plan.public_id}/apply/").status_code == 201


# ---------------------------------------------------------------------------
# Database governance
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDatabaseGovernance:
    def test_triggers_are_installed(self):
        expected = {
            PLAN_TABLE: {"UPDATE", "DELETE"},
            ITEM_TABLE: {"UPDATE", "DELETE"},
            APPLICATION_TABLE: {"INSERT", "UPDATE", "DELETE"},
            ORIGIN_TABLE: {"UPDATE", "DELETE"},
        }
        with connection.cursor() as cur:
            for table, events in expected.items():
                cur.execute(
                    "SELECT event_manipulation FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                found = {row[0] for row in cur.fetchall()}
                assert events <= found, f"{table}: missing {events - found}"

    def test_public_queryset_writes_nothing(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        with pytest.raises(UpgradeMutationForbidden):
            DossierUpgradePlan.objects.filter(pk=plan.pk).update(status=PlanStatus.APPLIED)
        with pytest.raises(UpgradeMutationForbidden):
            DossierUpgradePlan.objects.filter(pk=plan.pk).delete()
        with pytest.raises(UpgradeMutationForbidden):
            DossierUpgradePlanItem.objects.filter(plan=plan).update(status=ItemStatus.ACCEPTED)
        plan.refresh_from_db()
        assert plan.status == PlanStatus.DRAFT

    def test_plan_identity_and_provenance_are_frozen(
        self, dossier_a, v2, tenant_a, tenant_b, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        for column, value in (
            ("tenant_id", tenant_b.pk),
            ("source_version_id", v2.pk),
            ("dossier_id", dossier_a.pk + 999),
        ):
            with pytest.raises(DB_ERRORS) as exc:
                _sql(f"UPDATE {PLAN_TABLE} SET {column} = %s WHERE id = %s", [value, plan.pk])
            assert "immutable" in str(exc.value).lower(), column

    def test_an_applied_plan_refuses_every_update(self, applied_plan):
        plan, _ = applied_plan
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {PLAN_TABLE} SET notes = 'edited' WHERE id = %s", [plan.pk])
        assert "immutable" in str(exc.value).lower()

    def test_a_plan_cannot_be_deleted(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {PLAN_TABLE} WHERE id = %s", [plan.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert DossierUpgradePlan.objects.filter(pk=plan.pk).exists()

    def test_a_plan_cannot_skip_straight_to_applied(self, dossier_a, v2, tenant_a, admin_a):
        """DRAFT -> APPLIED without review is refused at the database."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {PLAN_TABLE} SET status = 'applied', applied_at = NOW(), "
                f"applied_by_id = created_by_id WHERE id = %s",
                [plan.pk],
            )
        assert "marked ready" in str(exc.value).lower()

    def test_item_content_is_frozen_and_only_review_status_may_move(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        item = item_for(plan, ChangeType.UPDATE_TITLE, "A")
        for column, value in (
            ("change_type", "'add_section'"),
            ("after_value", "'forged'"),
            ("section_code", "'ZZ'"),
        ):
            with pytest.raises(DB_ERRORS) as exc:
                _sql(f"UPDATE {ITEM_TABLE} SET {column} = {value} WHERE id = %s", [item.pk])
            assert "immutable" in str(exc.value).lower(), column

    def test_items_of_an_applied_plan_are_immutable(self, applied_plan):
        """This is what makes the accept/reject record permanent."""
        plan, _ = applied_plan
        item = plan.items.first()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"UPDATE {ITEM_TABLE} SET status = 'rejected' WHERE id = %s", [item.pk])
        assert "applied plan" in str(exc.value).lower()

    def test_items_of_an_applied_plan_cannot_be_deleted(self, applied_plan):
        plan, _ = applied_plan
        item = plan.items.first()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(f"DELETE FROM {ITEM_TABLE} WHERE id = %s", [item.pk])
        assert "history" in str(exc.value).lower()
        assert DossierUpgradePlanItem.objects.filter(pk=item.pk).exists()

    def test_items_of_an_open_plan_may_be_deleted_by_regenerate(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """The one sanctioned deletion, and the reason the trigger is
        conditional rather than absolute."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        before = set(plan.items.values_list("public_id", flat=True))
        services.regenerate_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        after = set(plan.items.values_list("public_id", flat=True))
        assert before.isdisjoint(after), "the items were genuinely replaced"

    def test_applied_history_is_immutable_and_undeletable(self, applied_plan, tenant_b):
        _, application = applied_plan
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {APPLICATION_TABLE} SET target_version_number = 99 WHERE id = %s",
                [application.pk],
            )
        assert "permanent record" in str(exc.value).lower()
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {APPLICATION_TABLE} WHERE id = %s", [application.pk])
        assert DossierUpgradeApplication.objects.filter(pk=application.pk).exists()

    def test_upgrade_section_origins_are_immutable_and_undeletable(self, applied_plan):
        origin = UpgradeSectionOrigin.objects.first()
        with pytest.raises(DB_ERRORS):
            _sql(f"UPDATE {ORIGIN_TABLE} SET tenant_id = tenant_id WHERE id = %s", [origin.pk])
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {ORIGIN_TABLE} WHERE id = %s", [origin.pk])
        assert UpgradeSectionOrigin.objects.filter(pk=origin.pk).exists()

    def test_false_history_cannot_be_inserted(self, applied_plan, tenant_b, admin_a):
        """Learning from the Milestone 10 review: freezing a row that was never
        checked on the way in preserves whatever was written."""
        plan, application = applied_plan
        columns = (
            "public_id, created_at, updated_at, tenant_id, dossier_id, plan_id, blueprint_id, "
            "source_version_id, target_version_id, source_version_number, "
            "target_version_number, sections_added, sections_retired, sections_updated, "
            "applied_by_id"
        )
        # Tenant that disagrees with the plan.
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"INSERT INTO {APPLICATION_TABLE} ({columns}) VALUES "
                f"(gen_random_uuid(), NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s)",
                [
                    tenant_b.pk,
                    plan.dossier_id,
                    plan.pk,
                    plan.blueprint_id,
                    plan.source_version_id,
                    plan.target_version_id,
                    1,
                    2,
                    admin_a.pk,
                ],
            )
        assert "tenant does not match" in str(exc.value).lower()

    def test_a_fabricated_version_number_in_history_is_refused(
        self, applied_plan, tenant_a, admin_a
    ):
        plan, _ = applied_plan
        columns = (
            "public_id, created_at, updated_at, tenant_id, dossier_id, plan_id, blueprint_id, "
            "source_version_id, target_version_id, source_version_number, "
            "target_version_number, sections_added, sections_retired, sections_updated, "
            "applied_by_id"
        )
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"INSERT INTO {APPLICATION_TABLE} ({columns}) VALUES "
                f"(gen_random_uuid(), NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s)",
                [
                    tenant_a.pk,
                    plan.dossier_id,
                    plan.pk,
                    plan.blueprint_id,
                    plan.source_version_id,
                    plan.target_version_id,
                    99,
                    99,
                    admin_a.pk,
                ],
            )
        assert "version_number snapshot" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    def test_only_one_of_two_simultaneous_applies_wins(self, dossier_a, v2, tenant_a, admin_a):
        import threading

        from django.db import connections

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        wins, errors = [], []

        def worker():
            try:
                wins.append(services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(wins) == 1, f"expected exactly one winner, got {len(wins)}"
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1

    def test_two_simultaneous_generations_cannot_both_create_an_open_plan(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        import threading

        from django.db import connections

        created, errors = [], []

        def worker():
            try:
                created.append(generate(dossier_a, tenant_a, admin_a, v2))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        open_plans = DossierUpgradePlan.objects.filter(
            dossier=dossier_a, status__in=[PlanStatus.DRAFT, PlanStatus.READY]
        )
        assert open_plans.count() == 1, "the partial unique index holds"

    def test_a_dossier_edit_between_ready_and_apply_makes_the_plan_stale(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """The apply-versus-edit race, in the deterministic direction: whichever
        edit lands first, the plan must refuse rather than write against facts
        that moved."""
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        ds.create_section(
            dossier=dossier_a, tenant=tenant_a, actor=admin_a, section_code="RACE", title="Race"
        )
        with pytest.raises(services.PlanStale):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)


# ---------------------------------------------------------------------------
# Query cost
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestQueryCost:
    """Invariance, not an absolute. An absolute encodes today's fixed overhead
    and breaks on unrelated changes; what must never change is the shape."""

    def _count(self, client, url):
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
            assert response.status_code == 200, response.data
        return len(ctx.captured_queries)

    def test_plan_list_is_flat_in_the_number_of_plans(
        self, client_admin_a, dossier_a, v1, v2, tenant_a, admin_a
    ):
        url = f"{DOSSIER_API}/{dossier_a.public_id}/upgrade-plans/"
        counts = {}
        made = 0
        for target in (1, 20, 100):
            while made < target:
                made += 1
                # Cancelled plans accumulate as history, which is exactly the
                # list this endpoint has to stay flat over.
                plan = generate(dossier_a, tenant_a, admin_a, v2)
                services.cancel_plan(plan=plan, tenant=tenant_a, actor=admin_a)
            counts[target] = self._count(client_admin_a, url)
        assert counts[1] == counts[20] == counts[100], counts

    def test_plan_detail_is_flat_in_the_number_of_items(
        self, client_admin_a, dossier_a, v1, tenant_a, admin_a
    ):
        from dossier_blueprints import services as bp

        counts = {}
        for size in (10, 100, 500):
            draft = draft_from(v1, tenant_a, admin_a)
            for i in range(size):
                make_blueprint_section(draft, tenant_a, admin_a, f"S{i:04d}")
            target = activate(draft, tenant_a, admin_a)
            plan = generate(dossier_a, tenant_a, admin_a, target)
            counts[size] = self._count(client_admin_a, f"{PLAN_API}/{plan.public_id}/")
            services.cancel_plan(plan=plan, tenant=tenant_a, actor=admin_a)
            assert bp

        assert counts[10] == counts[100] == counts[500], counts

    def test_generation_cost_grows_linearly_not_quadratically(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """The runtime facts that decide retirement safety are batched into a
        handful of aggregates; a per-section query would be quadratic here."""
        from django.test.utils import CaptureQueriesContext

        measured = {}
        for size in (20, 40):
            draft = draft_from(v1, tenant_a, admin_a)
            for i in range(size):
                make_blueprint_section(draft, tenant_a, admin_a, f"T{size}_{i:04d}")
            target = activate(draft, tenant_a, admin_a)
            with CaptureQueriesContext(connection) as ctx:
                plan = generate(dossier_a, tenant_a, admin_a, target)
            measured[size] = len(ctx.captured_queries)
            services.cancel_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        ratio = measured[40] / measured[20]
        assert ratio < 2.6, f"generation looks super-linear: {measured}"
