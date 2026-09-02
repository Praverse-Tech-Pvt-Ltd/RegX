"""Facts re-proved at apply time that generation cannot keep true.

The structural fingerprint is not a substitute for any of this. It hashes the
dossier's section tree, and both failures below move no section at all:

  * retiring a blueprint version changes nothing about a dossier;
  * a sibling plan can advance the provenance chain while leaving the tree
    byte-identical, if every accepted item turned out to be a no-op.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import pytest

from dossier_blueprints.models import BlueprintVersionStatus
from dossier_upgrades import services
from dossier_upgrades.models import (
    ChangeType,
    DossierUpgradeApplication,
    ItemStatus,
    PlanStatus,
)
from dossier_upgrades.tests.conftest import (
    accept_all,
    activate,
    dossier_sections,
    draft_from,
    generate,
    make_blueprint_section,
)


def _audit_applies(plan):
    """Success events for one plan. `emit` keys them by the plan, not the dossier."""
    from audit.models import AuditEvent

    return AuditEvent.objects.filter(
        event_type="dossier_upgrade.plan_applied", resource_id=plan.public_id
    )


def _nothing_happened(dossier, plan, *, expect_status=PlanStatus.READY):
    """No history, no origins, no success audit, plan untouched."""
    from dossier_upgrades.models import UpgradeSectionOrigin

    plan.refresh_from_db()
    assert plan.status == expect_status
    assert plan.applied_at is None
    assert plan.items.filter(status=ItemStatus.APPLIED).count() == 0
    assert DossierUpgradeApplication.objects.filter(dossier=dossier).count() == 0
    assert UpgradeSectionOrigin.objects.filter(application__dossier=dossier).count() == 0
    assert _audit_applies(plan).count() == 0


def _next_version(previous, tenant, actor, *, code="C-EXTRA"):
    """A later version, differing by one added root section.

    Publishing it RETIRES `previous` in the same transaction -- only one version
    per blueprint is ACTIVE -- so the order tests call this in matters.
    """
    draft = draft_from(previous, tenant, actor)
    make_blueprint_section(draft, tenant, actor, code, title=f"Section {code}")
    return activate(draft, tenant, actor)


def _forged_plan(dossier, tenant, actor, source, target, status=PlanStatus.READY):
    """A plan row written straight to the table, bypassing the service.

    `0002` governs plan UPDATE and DELETE, not INSERT, so this is reachable by
    anything holding a cursor -- which is the threat model the `0003` chain
    trigger exists for. Without it the trigger could only ever be tested against
    states the service refuses to build, which would prove nothing.
    """
    from django.utils import timezone

    from dossier_upgrades.models import DossierUpgradePlan

    # `upgrade_plan_stamps_are_consistent` requires an applied plan to carry its
    # stamps, so a forged row still has to be internally coherent. Only the way
    # it came into being is illegitimate.
    stamps = (
        {"applied_by": actor, "applied_at": timezone.now()} if status == PlanStatus.APPLIED else {}
    )
    return DossierUpgradePlan.objects.create(
        tenant=tenant,
        dossier=dossier,
        blueprint=target.blueprint,
        source_version=source,
        target_version=target,
        status=status,
        dossier_fingerprint="0" * 64,
        created_by=actor,
        **stamps,
    )


def _forge_application(dossier, tenant, actor, plan, source, target):
    return DossierUpgradeApplication.objects.create(
        tenant=tenant,
        dossier=dossier,
        plan=plan,
        blueprint=plan.blueprint,
        source_version=source,
        target_version=target,
        source_version_number=source.version_number,
        target_version_number=target.version_number,
        applied_by=actor,
    )


# ---------------------------------------------------------------------------
# Test 1 -- the target was withdrawn between review and apply
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTargetRetiredAfterReview:
    def test_a_retired_target_refuses_to_apply(self, dossier_a, v2, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)  # also marks the plan ready
        before = {c: s.title for c, s in dossier_sections(dossier_a).items()}

        # Retirement is a deliberate withdrawal. It moves no dossier section, so
        # the fingerprint is untouched -- proving this gate is not the staleness
        # gate wearing a different name.
        bp.retire_version(version=v2, tenant=tenant_a, actor=admin_a)
        assert services.is_stale(plan) is False

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "no longer active" in str(exc.value)

        assert {c: s.title for c, s in dossier_sections(dossier_a).items()} == before
        _nothing_happened(dossier_a, plan)

    def test_the_message_names_no_restricted_identifier(self, dossier_a, v2, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        bp.retire_version(version=v2, tenant=tenant_a, actor=admin_a)

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        message = str(exc.value)
        for leaked in (str(v2.public_id), str(plan.public_id), v2.blueprint.name):
            assert leaked not in message
        assert str(v2.version_number) not in message


# ---------------------------------------------------------------------------
# Test 2 -- the chain moved on without this plan
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSourceProvenanceAdvanced:
    """WHY THIS GATE IS DEFENCE IN DEPTH RATHER THAN THE ONLY DEFENCE.

    Two upstream constraints already make the sequential fork unreachable
    through the service:

      * only one version per blueprint is ACTIVE -- `activate_version` retires
        the previous one in the same transaction;
      * at most one OPEN plan per (dossier, target).

    So two open plans must have different targets, and at most one of those
    targets can be ACTIVE. Every reachable sequential attempt is therefore met
    by the target-ACTIVE gate first, and that is worth stating plainly rather
    than dressing a scenario up to look like it reached this one.

    What this gate carries alone is the case where history arrives without
    passing the service at all -- a raw cursor, a psql session, a migration --
    and its counterpart at the database is `0003`. Both are exercised here.
    """

    def test_applying_can_advance_the_chain_without_moving_the_fingerprint(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """The premise: staleness provably cannot stand in for provenance.

        One accepted item, a blueprint default due-date. A manual due date
        appears before apply, so apply skips it -- correctly, a hand-set date is
        never overwritten. Zero sections move, the fingerprint is identical
        either side, and the chain still advanced from v1 to v2.
        """
        from datetime import date

        from dossier_blueprints import services as bp
        from dossier_upgrades.fingerprint import fingerprint_for_dossier
        from submission_dossiers import services as ds

        draft = draft_from(v1, tenant_a, admin_a)
        bp.update_section(
            section=draft.sections.get(section_code="A.1"),
            tenant=tenant_a,
            actor=admin_a,
            default_due_offset_days=21,
        )
        v2_dates = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, v2_dates)
        types = [i.change_type for i in plan.items.all()]
        assert types.count(ChangeType.UPDATE_DUE_OFFSET) == 1
        accept_all(plan, tenant_a, admin_a)

        ds.update_section(
            section=dossier_sections(dossier_a)["A.1"],
            tenant=tenant_a,
            actor=admin_a,
            due_date=date(2026, 11, 30),
        )

        before = fingerprint_for_dossier(dossier_a)
        application = services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        after = fingerprint_for_dossier(dossier_a)

        assert after == before, "the section tree did not move"
        assert (application.sections_added, application.sections_retired) == (0, 0)
        assert application.sections_updated == 0
        # ...and yet:
        assert services.current_version_for(dossier_a)[1].pk == v2_dates.pk
        assert dossier_sections(dossier_a)["A.1"].due_date == date(2026, 11, 30)

    def test_the_guard_refuses_a_plan_whose_source_is_no_longer_current(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """The gate itself, against a real plan row in a real state.

        After the apply this plan genuinely names v1 as its source while the
        dossier sits at v2. Nothing is forged: it is the object the service
        would be handed.
        """
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        plan.refresh_from_db()
        assert plan.source_version_id == v1.pk
        assert services.current_version_for(dossier_a)[1].pk == v2.pk

        with pytest.raises(services.UpgradeLocked) as exc:
            services._assert_provenance_unmoved(dossier_a, plan)
        assert "provenance" in str(exc.value).lower()

    def test_the_guard_accepts_a_plan_still_at_the_current_version(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """It must not refuse the ordinary case."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        services._assert_provenance_unmoved(dossier_a, plan)

    def test_a_dossier_with_no_provenance_at_all_fails_closed(
        self, case_a, v1, v2, tenant_a, admin_a
    ):
        """A hand-built dossier has no chain to continue.

        The instantiation row cannot simply be deleted -- M10 governance refuses
        that, correctly -- so this uses a dossier that never had one.
        """
        from submission_dossiers import services as ds

        manual = ds.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Built by hand"
        )
        forged = _forged_plan(manual, tenant_a, admin_a, source=v1, target=v2)

        with pytest.raises(services.UpgradeLocked):
            services._assert_provenance_unmoved(manual, forged)

    def test_apply_refuses_when_history_arrived_without_passing_the_service(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """The reachable shape of this gate, end to end through `apply_plan`.

        Every route where the *service* advances the chain is caught upstream by
        the target-ACTIVE gate, because publishing the next version retires the
        one an older plan points at. So the state that reaches this gate is the
        one it was written for: a history row that arrived some other way -- a
        raw insert, a psql session, a migration -- leaving a plan whose target is
        still perfectly ACTIVE and whose source is no longer where the dossier
        is.

        Forged only in how the chain advanced. The plan is a real reviewed plan,
        and `apply_plan` is called normally.
        """
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        # The chain advances v1 -> v2 without the service. This passes `0003`:
        # the dossier was instantiated from v1, so it is a legitimate first link.
        shadow = _forged_plan(
            dossier_a, tenant_a, admin_a, source=v1, target=v2, status=PlanStatus.APPLIED
        )
        _forge_application(dossier_a, tenant_a, admin_a, shadow, source=v1, target=v2)

        # The target is untouched and still ACTIVE, so gate 4 has nothing to say.
        v2.refresh_from_db()
        assert v2.status == BlueprintVersionStatus.ACTIVE
        # The section tree never moved, so the fingerprint has nothing to say.
        assert services.is_stale(plan) is False
        # Only the provenance gate can catch this.
        assert services.current_version_for(dossier_a)[1].pk == v2.pk
        assert plan.source_version_id == v1.pk

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "provenance" in str(exc.value).lower()

        # The forged link is the only one, and the real plan is untouched.
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1
        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY
        assert plan.applied_at is None
        assert _audit_applies(plan).count() == 0

    def test_apply_fails_closed_on_a_dossier_with_no_provenance_at_all(
        self, case_a, v1, v2, tenant_a, admin_a
    ):
        """A hand-built dossier has no chain, so there is nothing to continue.

        Reached through `apply_plan`, not the guard directly: provenance is
        checked before staleness, so this proves the fail-closed branch is wired
        in and not merely written.
        """
        from submission_dossiers import services as ds

        manual = ds.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Built by hand"
        )
        forged = _forged_plan(manual, tenant_a, admin_a, source=v1, target=v2)

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=forged, tenant=tenant_a, actor=admin_a)
        assert "provenance" in str(exc.value).lower()
        assert DossierUpgradeApplication.objects.filter(dossier=manual).count() == 0

    def test_apply_refuses_a_plan_whose_blueprint_is_not_the_dossiers(
        self, dossier_a, blueprint_a, tenant_a, admin_a
    ):
        """The dossier came from blueprint A; this plan describes another one.

        Cross-blueprint comparison is meaningless -- no section correspondence
        exists -- and `generate_plan` refuses it. This proves apply refuses it
        too, rather than trusting a plan row to have been built honestly.
        """
        from dossier_blueprints import services as bp
        from dossier_upgrades.tests.conftest import publish

        other = bp.create_blueprint(tenant=tenant_a, actor=admin_a, name="Unrelated outline")
        other_v1 = publish(other, tenant_a, admin_a, [("X", None, {})])
        other_v2 = _next_version(other_v1, tenant_a, admin_a, code="X-EXTRA")
        assert other.pk != blueprint_a.pk

        forged = _forged_plan(dossier_a, tenant_a, admin_a, source=other_v1, target=other_v2)

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=forged, tenant=tenant_a, actor=admin_a)
        assert "provenance" in str(exc.value).lower()
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 0

    def test_a_plan_naming_a_stale_source_is_refused_end_to_end(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """Whichever gate speaks first, nothing is written and one link stands."""
        plan_a = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan_a, tenant_a, admin_a)

        # Publishing v3 retires v2, so plan_b is the only one whose target is
        # still ACTIVE -- the reachable shape of this race.
        v3 = _next_version(v2, tenant_a, admin_a)
        plan_b = services.generate_plan(
            dossier=dossier_a,
            tenant=tenant_a,
            actor=admin_a,
            target_version_public_id=v3.public_id,
        )
        accept_all(plan_b, tenant_a, admin_a)
        assert plan_a.source_version_id == plan_b.source_version_id == v1.pk

        services.apply_plan(plan=plan_b, tenant=tenant_a, actor=admin_a)
        assert services.current_version_for(dossier_a)[1].pk == v3.pk

        with pytest.raises(services.UpgradeLocked):
            services.apply_plan(plan=plan_a, tenant=tenant_a, actor=admin_a)

        applications = list(DossierUpgradeApplication.objects.filter(dossier=dossier_a))
        assert len(applications) == 1
        assert applications[0].plan_id == plan_b.pk
        plan_a.refresh_from_db()
        assert plan_a.status == PlanStatus.READY
        assert plan_a.applied_at is None


# ---------------------------------------------------------------------------
# Test 3 -- the chain may not fork, enforced below the service
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChainIntegrityAtTheDatabase:
    """`objects.create()` resolves through `_base_manager` and takes no lock, so
    these are what a raw insert, a psql session or a migration would do."""

    def test_a_second_link_from_the_same_source_is_refused(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        from django.db import IntegrityError, transaction
        from django.db.utils import InternalError, ProgrammingError

        plan_a = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan_a, tenant_a, admin_a)
        services.apply_plan(plan=plan_a, tenant=tenant_a, actor=admin_a)

        v3 = _next_version(v2, tenant_a, admin_a)
        forged = _forged_plan(dossier_a, tenant_a, admin_a, source=v1, target=v3)

        # A second link also claiming to start at v1: the fork. A BEFORE INSERT
        # trigger runs ahead of index maintenance, so sequentially it is the
        # chain trigger that speaks; the unique index is what holds when two
        # transactions reach the insert without seeing each other.
        with (
            pytest.raises((InternalError, ProgrammingError, IntegrityError)),
            transaction.atomic(),
        ):
            _forge_application(dossier_a, tenant_a, admin_a, forged, source=v1, target=v3)

        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1

    def test_a_first_link_that_does_not_start_at_the_instantiation_is_refused(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """Unique (dossier, source) cannot catch this one; the chain trigger does.

        The dossier was instantiated from v1 and has no applied upgrade, so a
        first link claiming to start at v2 grafts onto nothing.
        """
        from django.db import transaction
        from django.db.utils import InternalError, ProgrammingError

        v3 = _next_version(v2, tenant_a, admin_a)
        forged = _forged_plan(dossier_a, tenant_a, admin_a, source=v2, target=v3)

        with pytest.raises((InternalError, ProgrammingError)) as exc, transaction.atomic():
            _forge_application(dossier_a, tenant_a, admin_a, forged, source=v2, target=v3)
        assert "instantiated" in str(exc.value)
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 0

    def test_a_link_grafted_past_the_end_of_the_chain_is_refused(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """The chain ends at v2; a link claiming to start at v3 skips a step."""
        from django.db import transaction
        from django.db.utils import InternalError, ProgrammingError

        plan_a = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan_a, tenant_a, admin_a)
        services.apply_plan(plan=plan_a, tenant=tenant_a, actor=admin_a)

        v3 = _next_version(v2, tenant_a, admin_a)
        v4 = _next_version(v3, tenant_a, admin_a, code="D-EXTRA")
        forged = _forged_plan(dossier_a, tenant_a, admin_a, source=v3, target=v4)

        with pytest.raises((InternalError, ProgrammingError)) as exc, transaction.atomic():
            _forge_application(dossier_a, tenant_a, admin_a, forged, source=v3, target=v4)
        assert "chain" in str(exc.value)
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1


# ---------------------------------------------------------------------------
# Test 4 -- the ordinary case still works
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSequentialUpgrade:
    def test_v1_to_v2_then_v2_to_v3(self, dossier_a, v1, v2, tenant_a, admin_a):
        plan_1 = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan_1, tenant_a, admin_a)
        services.apply_plan(plan=plan_1, tenant=tenant_a, actor=admin_a)
        assert services.current_version_for(dossier_a)[1].pk == v2.pk

        # v3 is published only now: activating it earlier would have retired v2
        # and made the first upgrade impossible.
        v3 = _next_version(v2, tenant_a, admin_a)

        plan_2 = generate(dossier_a, tenant_a, admin_a, v3)
        assert plan_2.source_version_id == v2.pk, "sources from the applied upgrade"
        accept_all(plan_2, tenant_a, admin_a)
        services.apply_plan(plan=plan_2, tenant=tenant_a, actor=admin_a)

        chain = [
            (a.source_version_number, a.target_version_number)
            for a in DossierUpgradeApplication.objects.filter(dossier=dossier_a).order_by(
                "created_at", "id"
            )
        ]
        assert chain == [
            (v1.version_number, v2.version_number),
            (v2.version_number, v3.version_number),
        ]
        assert services.current_version_for(dossier_a)[1].pk == v3.pk
        assert "C-EXTRA" in dossier_sections(dossier_a)


# ---------------------------------------------------------------------------
# Nothing is written before the checks
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNoWritesBeforeTheChecks:
    def test_a_refused_apply_writes_no_section_and_no_history(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        from dossier_blueprints import services as bp
        from submission_dossiers.models import DossierSection

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        def snapshot():
            return {
                (s.pk, s.section_code, s.title, s.sequence, s.parent_id, s.retired_at)
                for s in DossierSection.objects.filter(dossier=dossier_a)
            }

        before = snapshot()
        bp.retire_version(version=v2, tenant=tenant_a, actor=admin_a)

        with pytest.raises(services.UpgradeLocked):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        assert snapshot() == before, "not one section row moved"
        _nothing_happened(dossier_a, plan)


# ---------------------------------------------------------------------------
# Concurrency -- real threads, real PostgreSQL
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestApplyConcurrency:
    def test_two_simultaneous_applies_produce_exactly_one_link(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """The dossier row is the serialization point.

        Both threads read provenance and insert history while holding it, so the
        loser sees a settled chain rather than one the winner is midway through
        extending.
        """
        import threading

        from django.db import connections

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        wins, errors = [], []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=15)
                wins.append(services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(wins) == 1, f"expected exactly one winner, got {len(wins)}: {errors}"
        assert len(errors) == 1
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1
        assert _audit_applies(plan).count() == 1

    def test_a_concurrent_fork_is_stopped_by_the_unique_index_not_the_trigger(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """The one case the chain trigger provably cannot catch.

        Both inserts run before either commits, so each trigger looks up the
        chain and sees the same settled state -- no prior application, and an
        instantiation at v1 -- and both legitimately pass. Nothing about a
        BEFORE INSERT trigger can close that: it reads committed rows.

        `UNIQUE (dossier_id, source_version_id)` is not snapshot-dependent, so it
        closes it regardless of isolation level or lock order. This is the split
        `0003` documents, demonstrated rather than asserted.
        """
        import threading

        from django.db import IntegrityError, connections, transaction

        v3 = _next_version(v2, tenant_a, admin_a)
        # Two plans, same source, different targets -- forged, because the
        # service would refuse to let both reach an insert.
        plans = [
            _forged_plan(dossier_a, tenant_a, admin_a, source=v1, target=v2),
            _forged_plan(dossier_a, tenant_a, admin_a, source=v1, target=v3),
        ]

        wins, errors = [], []
        barrier = threading.Barrier(2)

        def worker(plan):
            try:
                with transaction.atomic():
                    barrier.wait(timeout=15)
                    _forge_application(
                        dossier_a,
                        tenant_a,
                        admin_a,
                        plan,
                        source=v1,
                        target=plan.target_version,
                    )
                wins.append(plan.pk)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(p,)) for p in plans]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(wins) == 1, f"expected exactly one insert to survive: {errors}"
        assert len(errors) == 1
        assert isinstance(errors[0], IntegrityError), (
            f"the unique index should be what refused it, got {type(errors[0]).__name__}: "
            f"{errors[0]}"
        )
        assert DossierUpgradeApplication.objects.filter(dossier=dossier_a).count() == 1

    def test_apply_racing_target_retirement_never_applies_a_retired_version(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """Either order is a valid outcome. Applying a RETIRED target is not.

        Both transactions take the target version row FOR UPDATE --
        `retire_version` after the blueprint, `apply_plan` as its third lock --
        so one waits for the other and neither reads a status mid-flight. Which
        one wins is genuinely undetermined and the test does not pretend
        otherwise: it asserts the safety property, not a timing.
        """
        import threading

        from django.db import connections

        from dossier_blueprints import services as bp
        from dossier_blueprints.models import BlueprintVersionStatus, DossierBlueprintVersion

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        applied, apply_errors, retire_errors = [], [], []
        barrier = threading.Barrier(2)

        def apply_worker():
            try:
                barrier.wait(timeout=15)
                applied.append(services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a))
            except Exception as exc:
                apply_errors.append(exc)
            finally:
                connections.close_all()

        def retire_worker():
            try:
                barrier.wait(timeout=15)
                bp.retire_version(version=v2, tenant=tenant_a, actor=admin_a)
            except Exception as exc:
                retire_errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=apply_worker), threading.Thread(target=retire_worker)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(applied) + len(apply_errors) == 1, "the apply must reach a definite outcome"
        final = DossierBlueprintVersion.objects.get(pk=v2.pk)
        applications = DossierUpgradeApplication.objects.filter(dossier=dossier_a)

        if applied:
            # Apply took the version row first and observed ACTIVE. Legitimate:
            # at the instant it checked, the retirement had not happened. The
            # retirement then lands behind it, or reports its own conflict.
            assert applications.count() == 1
            assert applications.first().target_version_id == v2.pk
            assert _audit_applies(plan).count() == 1
            assert final.status in (
                BlueprintVersionStatus.RETIRED,
                BlueprintVersionStatus.ACTIVE,
            ), f"unexpected version state {final.status}; retire errors: {retire_errors}"
        else:
            # Retirement took it first, so apply must have refused outright --
            # and refused for that reason, not incidentally.
            assert final.status == BlueprintVersionStatus.RETIRED
            assert "no longer active" in str(apply_errors[0])
            assert applications.count() == 0
            assert _audit_applies(plan).count() == 0
            plan.refresh_from_db()
            assert plan.status == PlanStatus.READY

        # The invariant that holds either way: no applied link may name a target
        # that was already retired when the apply checked it. A retired target
        # with a successful apply is only sound if the retirement came second,
        # which is exactly the branch above.
        assert not (applications.count() and apply_errors), (
            "an apply that errored must have written nothing"
        )


# ---------------------------------------------------------------------------
# Migration symmetry and counts
# ---------------------------------------------------------------------------
class TestMigrationSymmetry:
    """Docstring counts drift silently; SQL does not.

    `0002` already claimed these numbers were checked by a test. They were not:
    the test lived in `dossier_blueprints` and covered only that app, so the
    claim was true of M10 and false here. Asserting them is what turns a
    documentation error into a build failure -- which is exactly how M10's
    "five functions and eight triggers" over seven of each got through.
    """

    CASES = [
        ("0002_upgrade_db_governance", 6, 7),
        ("0003_upgrade_provenance_chain", 1, 1),
    ]

    def _module(self, name):
        import importlib

        return importlib.import_module(f"dossier_upgrades.migrations.{name}")

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_create_and_drop_are_symmetric(self, name, functions, triggers):
        m = self._module(name)
        assert m.CREATE_SQL.count("CREATE OR REPLACE FUNCTION") == functions
        assert m.CREATE_SQL.count("CREATE TRIGGER") == triggers
        assert m.DROP_SQL.count("DROP FUNCTION") == functions
        assert m.DROP_SQL.count("DROP TRIGGER") == triggers

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_the_docstring_states_the_real_counts(self, name, functions, triggers):
        m = self._module(name)
        doc = " ".join((m.__doc__ or "").split())
        assert f"{functions} plpgsql function" in doc, doc[:300]
        assert f"{triggers} trigger" in doc, doc[:300]

    @pytest.mark.parametrize("name,functions,triggers", CASES)
    def test_every_created_trigger_is_dropped_by_name(self, name, functions, triggers):
        m = self._module(name)
        created = {
            line.split()[2]
            for line in m.CREATE_SQL.splitlines()
            if line.startswith("CREATE TRIGGER")
        }
        dropped = {
            line.split()[4] for line in m.DROP_SQL.splitlines() if line.startswith("DROP TRIGGER")
        }
        assert created == dropped, f"{name}: created {created}, dropped {dropped}"

    def test_the_two_migrations_share_no_object_name(self):
        """A later migration silently replacing an earlier guard would leave the
        docstring counts right and the protection halved."""
        names = []
        for name, _, _ in self.CASES:
            m = self._module(name)
            names += [
                line.split()[2]
                for line in m.CREATE_SQL.splitlines()
                if line.startswith("CREATE TRIGGER")
            ]
            names += [
                line.split()[4].split("(")[0]
                for line in m.CREATE_SQL.splitlines()
                if line.startswith("CREATE OR REPLACE FUNCTION")
            ]
        assert len(names) == len(set(names)), f"duplicate database object name: {names}"
