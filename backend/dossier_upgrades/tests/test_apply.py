"""Applying a plan: only accepted items, all or nothing, runtime work preserved.

**Nothing here is automatic.** Every write in this file is reached only because
a caller explicitly accepted an item and then explicitly applied the plan.

Synthetic data only; generic section codes.
"""

from datetime import date

import pytest
from django.db import InternalError, ProgrammingError

from dossier_upgrades import services
from dossier_upgrades.models import (
    ChangeType,
    DossierUpgradeApplication,
    ItemStatus,
    PlanStatus,
    UpgradeSectionOrigin,
)
from dossier_upgrades.tests.conftest import (
    accept_all,
    activate,
    dossier_sections,
    draft_from,
    generate,
    make_blueprint_section,
)
from submission_dossiers.models import DossierSection

DB_ERRORS = (InternalError, ProgrammingError)


def item_for(plan, change_type, code=None):
    for item in plan.items.all():
        if item.change_type == change_type and (code is None or item.section_code == code):
            return item
    return None


def accept(plan, tenant, actor, item):
    return services.set_item_status(item=item, tenant=tenant, actor=actor, accept=True)


def reject(plan, tenant, actor, item):
    return services.set_item_status(item=item, tenant=tenant, actor=actor, accept=False)


def review_rest(plan, tenant, actor):
    """Reject anything still proposed, then mark ready."""
    from dossier_upgrades.models import ACTIONABLE_CHANGE_TYPES

    for item in plan.items.all():
        if item.change_type in ACTIONABLE_CHANGE_TYPES and item.status == ItemStatus.PROPOSED:
            services.set_item_status(item=item, tenant=tenant, actor=actor, accept=False)
    return services.mark_ready(plan=plan, tenant=tenant, actor=actor)


# ---------------------------------------------------------------------------
# Selective application
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSelectiveApply:
    def test_only_accepted_items_are_written(self, dossier_a, v2, tenant_a, admin_a):
        """The core promise: a reviewer's choices are honoured exactly."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        reject(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_REQUIRED, "A.2"))
        review_rest(plan, tenant_a, admin_a)

        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        sections = dossier_sections(dossier_a)
        assert sections["A"].title == "Section A, revised", "accepted"
        assert sections["A.2"].required is False, "rejected -- unchanged"

    def test_rejected_additions_are_not_created(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        for item in plan.items.filter(change_type=ChangeType.ADD_SECTION):
            reject(plan, tenant_a, admin_a, item)
        # One unrelated item is accepted so the apply has something to do --
        # rejecting everything is a different case, covered by
        # `test_a_plan_with_nothing_accepted_refuses_to_apply`.
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        codes = set(dossier_sections(dossier_a))
        assert "C" not in codes
        assert "C.1" not in codes

    def test_accepted_additions_preserve_hierarchy_and_metadata(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        for item in plan.items.filter(change_type=ChangeType.ADD_SECTION):
            accept(plan, tenant_a, admin_a, item)
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        sections = dossier_sections(dossier_a)
        assert "C" in sections and "C.1" in sections
        assert sections["C.1"].parent_id == sections["C"].pk
        assert sections["C"].parent_id is None

        target_c = v2.sections.get(section_code="C")
        assert sections["C"].required == target_c.required
        # Sequence is preserved where the slot is free and appended where it is
        # not: the blueprint freed C's slot by dropping B, but B is still in this
        # dossier because that retirement was not accepted here. Failing the
        # whole upgrade over an ordering collision would be the wrong trade.
        assert sections["C"].sequence >= target_c.sequence
        assert sections["C"].sequence != sections["B"].sequence

    def test_added_sections_start_at_M9_defaults(self, dossier_a, v2, tenant_a, admin_a):
        from submission_dossiers.models import SectionStatus

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        for item in plan.items.filter(change_type=ChangeType.ADD_SECTION):
            accept(plan, tenant_a, admin_a, item)
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        added = dossier_sections(dossier_a)["C"]
        assert added.status == SectionStatus.NOT_STARTED
        assert added.owner_id is None
        assert not added.blockers.exists()
        assert not added.document_links.exists()

    def test_accepted_retirement_retires_rather_than_deletes(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.RETIRE_SECTION, "B"))
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        assert "B" not in dossier_sections(dossier_a)
        # The row survives -- retirement, never deletion.
        row = DossierSection.objects.get(dossier=dossier_a, section_code="B")
        assert row.retired_at is not None

    def test_a_plan_with_a_blocked_item_cannot_be_applied(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp
        from submission_dossiers import services as ds

        ds.create_blocker(
            section=dossier_sections(dossier_a)["B"],
            tenant=tenant_a,
            actor=admin_a,
            title="Waiting",
        )
        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="B"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        review_rest(plan, tenant_a, admin_a)
        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "blocked" in str(exc.value).lower()
        assert "B" in dossier_sections(dossier_a), "the section survives"

    def test_apply_requires_a_ready_plan(self, dossier_a, v2, tenant_a, admin_a):
        """Generate is not apply. Accept is not apply."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        assert plan.status == PlanStatus.DRAFT

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "ready" in str(exc.value).lower()
        assert dossier_sections(dossier_a)["A"].title != "Section A, revised"

    def test_a_plan_with_nothing_accepted_refuses_to_apply(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        review_rest(plan, tenant_a, admin_a)
        with pytest.raises(services.NothingToApply):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

    def test_readiness_is_recalculated_not_set(self, dossier_a, v2, tenant_a, admin_a):
        from submission_dossiers.models import Readiness

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        for item in plan.items.filter(change_type=ChangeType.ADD_SECTION):
            accept(plan, tenant_a, admin_a, item)
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        sections = dossier_sections(dossier_a)
        # Two different answers from one recalculation is what proves the M9
        # engine ran rather than a default surviving.
        assert sections["C"].readiness == Readiness.PARTIALLY_READY, "has a child"
        assert sections["C.1"].readiness == Readiness.NOT_READY, "leaf, no work"

    def test_a_terminal_dossier_refuses_application(self, dossier_a, v2, tenant_a, admin_a):
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        review_rest(plan, tenant_a, admin_a)

        ds.cancel_dossier(dossier=dossier_a, tenant=tenant_a, actor=admin_a, reason="done")
        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "no longer accepts changes" in str(exc.value).lower()

    def test_a_stale_plan_refuses_to_apply(self, dossier_a, v2, tenant_a, admin_a):
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        review_rest(plan, tenant_a, admin_a)

        ds.create_section(
            dossier=dossier_a, tenant=tenant_a, actor=admin_a, section_code="NEW", title="New"
        )
        with pytest.raises(services.PlanStale) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "regenerate" in str(exc.value).lower()
        assert dossier_sections(dossier_a)["A"].title != "Section A, revised"

    def test_a_plan_can_only_be_applied_once(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept(plan, tenant_a, admin_a, item_for(plan, ChangeType.UPDATE_TITLE, "A"))
        review_rest(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        plan.refresh_from_db()
        assert plan.status == PlanStatus.APPLIED
        with pytest.raises(services.UpgradeLocked):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)


# ---------------------------------------------------------------------------
# Runtime work survives
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRuntimeWorkIsPreserved:
    def test_links_blockers_owner_notes_and_status_all_survive_an_upgrade(
        self, dossier_a, v2, tenant_a, admin_a, doer_a
    ):
        """The difference between a useful upgrade and a destructive one."""
        from documents.models import Document
        from submission_dossiers import services as ds
        from submission_dossiers.models import SectionStatus

        section = dossier_sections(dossier_a)["A.1"]
        document = Document.objects.create(
            tenant=tenant_a, title="Synthetic document", document_type="other"
        )
        ds.link_target(
            kind="document",
            section=section,
            target_public_id=document.public_id,
            actor=admin_a,
            tenant=tenant_a,
        )
        ds.create_blocker(
            section=section, tenant=tenant_a, actor=admin_a, title="Synthetic blocker"
        )
        ds.update_section(
            section=section,
            tenant=tenant_a,
            actor=admin_a,
            status=SectionStatus.IN_PROGRESS,
            owner=doer_a,
            notes="Important working notes",
        )

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        after = dossier_sections(dossier_a)["A.1"]
        assert after.status == SectionStatus.IN_PROGRESS
        assert after.owner_id == doer_a.pk
        assert after.notes == "Important working notes"
        assert after.blockers.count() == 1
        assert after.document_links.count() == 1

    def test_a_manually_set_due_date_is_never_overwritten(self, dossier_a, v1, tenant_a, admin_a):
        """Re-checked at apply time, not just at generation: a date set between
        generate and apply must survive too."""
        from dossier_blueprints import services as bp
        from submission_dossiers import services as ds

        draft = draft_from(v1, tenant_a, admin_a)
        bp.update_section(
            section=draft.sections.get(section_code="A.1"),
            tenant=tenant_a,
            actor=admin_a,
            default_due_offset_days=14,
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        accept_all(plan, tenant_a, admin_a)

        # Set a due date AFTER the plan was generated but before it is applied.
        chosen = date(2026, 12, 25)
        ds.update_section(
            section=dossier_sections(dossier_a)["A.1"],
            tenant=tenant_a,
            actor=admin_a,
            due_date=chosen,
        )
        # That is a runtime change, so the plan is not stale.
        assert services.is_stale(plan) is False
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        assert dossier_sections(dossier_a)["A.1"].due_date == chosen

    def test_work_recorded_after_review_stops_an_accepted_retirement(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """The window between review and apply is the dangerous one.

        A retirement is only ever proposed for a section carrying no work, and
        runtime changes deliberately do not stale a plan. So a blocker opened
        after the reviewer accepted would otherwise ride through: M9's
        retire_section refuses active children and nothing else -- correctly,
        for a human acting deliberately with the section in front of them.
        """
        from dossier_blueprints import services as bp
        from submission_dossiers import services as ds

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = plan.items.get(section_code="A.1")
        assert item.change_type == ChangeType.RETIRE_SECTION
        assert item.status == ItemStatus.PROPOSED, "clean at review time"
        accept_all(plan, tenant_a, admin_a)  # also marks the plan ready

        # Someone starts work on A.1 after the plan was reviewed.
        ds.create_blocker(
            section=dossier_sections(dossier_a)["A.1"],
            tenant=tenant_a,
            actor=admin_a,
            title="Synthetic blocker raised after review",
        )
        assert services.is_stale(plan) is False, "runtime changes do not stale a plan"

        with pytest.raises(services.UpgradeLocked) as exc:
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "A.1" in str(exc.value)

        # Refused whole, not partially applied.
        assert dossier_sections(dossier_a)["A.1"].retired_at is None
        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY

    def test_a_link_added_after_review_also_stops_the_retirement(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        from documents.models import Document
        from dossier_blueprints import services as bp
        from submission_dossiers import services as ds

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        accept_all(plan, tenant_a, admin_a)  # also marks the plan ready

        document = Document.objects.create(
            tenant=tenant_a, title="Synthetic document", document_type="other"
        )
        ds.link_target(
            kind="document",
            section=dossier_sections(dossier_a)["A.1"],
            target_public_id=document.public_id,
            actor=admin_a,
            tenant=tenant_a,
        )

        with pytest.raises(services.UpgradeLocked):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert dossier_sections(dossier_a)["A.1"].retired_at is None

    def test_a_retirement_still_applies_when_the_section_stayed_clean(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """The re-check must not refuse the ordinary case."""
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        accept_all(plan, tenant_a, admin_a)  # also marks the plan ready
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        assert "A.1" not in dossier_sections(dossier_a), "no longer active"
        assert (
            DossierSection.objects.get(dossier=dossier_a, section_code="A.1").retired_at is not None
        )

    def test_manual_sections_are_untouched_by_an_upgrade(self, dossier_a, v2, tenant_a, admin_a):
        from submission_dossiers import services as ds

        manual = ds.create_section(
            dossier=dossier_a,
            tenant=tenant_a,
            actor=admin_a,
            section_code="MANUAL-1",
            title="Mine",
        )
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)

        manual.refresh_from_db()
        assert manual.retired_at is None
        assert manual.title == "Mine"


# ---------------------------------------------------------------------------
# All or nothing
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTransactionalApply:
    def test_a_failure_partway_through_leaves_the_dossier_untouched(
        self, dossier_a, v2, tenant_a, admin_a, monkeypatch
    ):
        """Without one transaction this leaves a dossier that is half-upgraded
        and says nothing about it."""
        from audit.models import AuditEvent
        from dossier_upgrades.fingerprint import fingerprint_for_dossier
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)

        before_fingerprint = fingerprint_for_dossier(dossier_a)
        before_sections = DossierSection.objects.filter(dossier=dossier_a).count()
        before_audits = AuditEvent.objects.count()

        real_retire = ds.retire_section
        calls = {"n": 0}

        def exploding_retire(**kwargs):
            calls["n"] += 1
            raise RuntimeError("injected failure during retirement")

        monkeypatch.setattr(ds, "retire_section", exploding_retire)
        with pytest.raises(RuntimeError):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        monkeypatch.setattr(ds, "retire_section", real_retire)

        assert calls["n"] == 1, "the failure must land after additions and updates"
        # Additions and updates ran before the failure; all of them rolled back.
        assert fingerprint_for_dossier(dossier_a) == before_fingerprint
        assert DossierSection.objects.filter(dossier=dossier_a).count() == before_sections
        assert AuditEvent.objects.count() == before_audits

        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY, "no false APPLIED state"
        assert DossierUpgradeApplication.objects.count() == 0
        assert UpgradeSectionOrigin.objects.count() == 0

    def test_a_failure_at_the_provenance_step_also_rolls_back_the_sections(
        self, dossier_a, v2, tenant_a, admin_a, monkeypatch
    ):
        """The dangerous case: every section write has already succeeded."""
        from dossier_upgrades.fingerprint import fingerprint_for_dossier

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accept_all(plan, tenant_a, admin_a)
        before = fingerprint_for_dossier(dossier_a)

        real_create = DossierUpgradeApplication.objects.create

        def exploding(*args, **kwargs):
            raise RuntimeError("injected failure at provenance")

        monkeypatch.setattr(DossierUpgradeApplication.objects, "create", exploding)
        with pytest.raises(RuntimeError):
            services.apply_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        monkeypatch.setattr(DossierUpgradeApplication.objects, "create", real_create)

        assert fingerprint_for_dossier(dossier_a) == before
        plan.refresh_from_db()
        assert plan.status == PlanStatus.READY


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpgradeProvenance:
    def _apply(self, dossier, tenant, actor, target):
        plan = generate(dossier, tenant, actor, target)
        accept_all(plan, tenant, actor)
        return services.apply_plan(plan=plan, tenant=tenant, actor=actor)

    def test_the_original_instantiation_is_never_rewritten(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """It records how the dossier was CREATED. An upgrade is a later event,
        and rewriting it would erase the fact that the dossier began at v1."""
        from dossier_blueprints.models import BlueprintInstantiation

        original = BlueprintInstantiation.objects.get(dossier=dossier_a)
        before = (original.blueprint_version_id, original.version_number)

        self._apply(dossier_a, tenant_a, admin_a, v2)

        original.refresh_from_db()
        assert (original.blueprint_version_id, original.version_number) == before
        assert original.blueprint_version_id == v1.pk

    def test_upgrade_history_is_appended(self, dossier_a, v1, v2, tenant_a, admin_a):
        application = self._apply(dossier_a, tenant_a, admin_a, v2)
        assert application.source_version_id == v1.pk
        assert application.target_version_id == v2.pk
        assert application.source_version_number == 1
        assert application.target_version_number == 2
        assert application.applied_by_id == admin_a.pk

    def test_new_sections_get_a_target_origin_and_old_ones_keep_theirs(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        from dossier_blueprints.models import BlueprintSectionOrigin

        old_origin = BlueprintSectionOrigin.objects.get(
            dossier_section__section_code="A.1", dossier_section__dossier=dossier_a
        )
        before = old_origin.blueprint_section_id

        application = self._apply(dossier_a, tenant_a, admin_a, v2)

        # Newly added sections get an upgrade origin pointing at v2.
        new_origins = UpgradeSectionOrigin.objects.filter(application=application)
        assert {o.dossier_section.section_code for o in new_origins} == {"C", "C.1"}
        for origin in new_origins:
            assert origin.blueprint_section.blueprint_version_id == v2.pk

        # The pre-existing section's original origin is untouched.
        old_origin.refresh_from_db()
        assert old_origin.blueprint_section_id == before

    def test_several_sequential_upgrades_are_all_retained(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        """v1 instantiated, v2 applied, v3 applied. The whole path stays readable."""
        self._apply(dossier_a, tenant_a, admin_a, v2)

        draft = draft_from(v2, tenant_a, admin_a)
        make_blueprint_section(draft, tenant_a, admin_a, "D")
        v3 = activate(draft, tenant_a, admin_a)

        self._apply(dossier_a, tenant_a, admin_a, v3)

        history = list(
            DossierUpgradeApplication.objects.filter(dossier=dossier_a).order_by("created_at")
        )
        assert [(h.source_version_number, h.target_version_number) for h in history] == [
            (1, 2),
            (2, 3),
        ]

    def test_the_next_plan_sources_from_the_latest_upgrade_not_the_instantiation(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        self._apply(dossier_a, tenant_a, admin_a, v2)

        draft = draft_from(v2, tenant_a, admin_a)
        make_blueprint_section(draft, tenant_a, admin_a, "D")
        v3 = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, v3)
        assert plan.source_version_id == v2.pk

    def test_a_section_added_by_an_upgrade_is_tracked_by_the_next_comparison(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """Without layering upgrade origins over instantiation origins, `C`
        would look manually-added to the next comparison and be ignored."""
        from dossier_blueprints import services as bp

        self._apply(dossier_a, tenant_a, admin_a, v2)

        draft = draft_from(v2, tenant_a, admin_a)
        bp.update_section(
            section=draft.sections.get(section_code="C"),
            tenant=tenant_a,
            actor=admin_a,
            title="Section C, revised",
        )
        v3 = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, v3)
        titles = [
            i
            for i in plan.items.all()
            if i.change_type == ChangeType.UPDATE_TITLE and i.section_code == "C"
        ]
        assert titles, "the upgrade-added section is still blueprint-tracked"
