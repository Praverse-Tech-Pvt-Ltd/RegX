"""Comparison, plan generation, review and staleness.

**Generating a plan writes nothing to the dossier.** Several tests assert that
explicitly, because it is the property the whole milestone rests on.

Synthetic data only; generic section codes.
"""

import pytest

from dossier_upgrades import services
from dossier_upgrades.comparison import (
    BLOCK_AMBIGUOUS_CODE,
    BLOCK_HAS_BLOCKERS,
    BLOCK_HAS_CHILDREN,
    BLOCK_HAS_LINKS,
    BLOCK_HAS_PROGRESS,
)
from dossier_upgrades.fingerprint import fingerprint_for_dossier
from dossier_upgrades.models import (
    ChangeType,
    DossierUpgradePlan,
    ItemStatus,
    PlanStatus,
)
from dossier_upgrades.tests.conftest import (
    activate,
    dossier_sections,
    draft_from,
    generate,
    make_blueprint_section,
)


def types_of(plan):
    return {i.change_type for i in plan.items.all()}


def item_for(plan, change_type, code=None):
    for item in plan.items.all():
        if item.change_type == change_type and (code is None or item.section_code == code):
            return item
    return None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestComparison:
    def test_identical_versions_report_no_change(self, dossier_a, v1, tenant_a, admin_a):
        """A republished copy of the same structure must produce nothing to do."""
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        v1_copy = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, v1_copy)
        assert types_of(plan) == {ChangeType.NO_CHANGE}
        assert plan.actionable_items == 0
        assert bp  # imported for the fixture chain; keeps the intent explicit

    def test_the_full_shape_of_a_realistic_upgrade(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        found = types_of(plan)
        assert ChangeType.UPDATE_TITLE in found, "A was renamed"
        assert ChangeType.UPDATE_REQUIRED in found, "A.2 became required"
        assert ChangeType.RETIRE_SECTION in found, "B was dropped"
        assert ChangeType.ADD_SECTION in found, "C and C.1 are new"

        added = {
            i.section_code for i in plan.items.all() if i.change_type == ChangeType.ADD_SECTION
        }
        assert added == {"C", "C.1"}

    def test_additions_are_ordered_parent_before_child(self, dossier_a, v2, tenant_a, admin_a):
        """Apply depends on it: a child cannot be created before its parent."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        adds = [
            i for i in plan.items.order_by("sequence") if i.change_type == ChangeType.ADD_SECTION
        ]
        codes = [i.section_code for i in adds]
        assert codes.index("C") < codes.index("C.1")

    def test_add_root_and_add_child(self, dossier_a, v1, tenant_a, admin_a):
        draft = draft_from(v1, tenant_a, admin_a)
        root = make_blueprint_section(draft, tenant_a, admin_a, "Z")
        make_blueprint_section(draft, tenant_a, admin_a, "Z.1", parent=root)
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        adds = {i.section_code for i in plan.items.all() if i.change_type == ChangeType.ADD_SECTION}
        assert adds == {"Z", "Z.1"}

    def test_remove_child_proposes_a_retirement(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = item_for(plan, ChangeType.RETIRE_SECTION, "A.1")
        assert item is not None
        assert item.status == ItemStatus.PROPOSED, "a clean leaf is not blocked"

    def test_description_change(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.update_section(
            section=draft.sections.get(section_code="A.1"),
            tenant=tenant_a,
            actor=admin_a,
            description="A new description",
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = item_for(plan, ChangeType.UPDATE_DESCRIPTION, "A.1")
        assert item is not None
        assert item.after_value == "A new description"
        assert item.field_name == "description"

    def test_move_to_a_different_parent(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        by_code = {s.section_code: s for s in draft.sections.all()}
        bp.update_section(
            section=by_code["A.2"], tenant=tenant_a, actor=admin_a, parent=by_code["B"]
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = item_for(plan, ChangeType.MOVE_SECTION, "A.2")
        assert item is not None
        assert item.before_value == "A"
        assert item.after_value == "B"
        assert item.status == ItemStatus.PROPOSED, "B exists in the dossier, so it can land"

    def test_reorder_within_siblings(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.reorder_section(
            section=draft.sections.get(section_code="A.2"),
            tenant=tenant_a,
            actor=admin_a,
            sequence=0,
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        assert item_for(plan, ChangeType.REORDER_SECTION) is not None

    def test_due_offset_change_is_proposed_only_where_no_date_is_set(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.update_section(
            section=draft.sections.get(section_code="A.1"),
            tenant=tenant_a,
            actor=admin_a,
            default_due_offset_days=14,
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        assert item_for(plan, ChangeType.UPDATE_DUE_OFFSET, "A.1") is not None

    def test_runtime_fields_never_appear_as_changes(self, dossier_a, v2, tenant_a, admin_a):
        """A blueprint has no opinion about work in progress."""
        from submission_dossiers import services as ds
        from submission_dossiers.models import SectionStatus

        sections = dossier_sections(dossier_a)
        ds.update_section(
            section=sections["A.1"],
            tenant=tenant_a,
            actor=admin_a,
            status=SectionStatus.IN_PROGRESS,
            notes="Work in progress",
        )
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        fields = {i.field_name for i in plan.items.all()}
        for runtime_field in ("status", "readiness", "notes", "owner", "readiness_reason"):
            assert runtime_field not in fields


# ---------------------------------------------------------------------------
# Ambiguity -- where the comparison refuses to guess
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAmbiguity:
    def test_a_manual_section_colliding_with_a_target_code_is_a_conflict(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """The user added `Z` by hand; the next version also introduces `Z`.

        The comparison cannot tell whether they pre-empted the blueprint or
        picked the same code by coincidence. Adding would violate the dossier's
        unique active code; updating would silently adopt work the user owns.
        Both guesses could be wrong, so it refuses to make one.
        """
        from dossier_blueprints import services as bp
        from submission_dossiers import services as ds

        ds.create_section(
            dossier=dossier_a,
            tenant=tenant_a,
            actor=admin_a,
            section_code="Z",
            title="Added by hand",
        )
        draft = draft_from(v1, tenant_a, admin_a)
        make_blueprint_section(draft, tenant_a, admin_a, "Z")
        target = activate(draft, tenant_a, admin_a)
        assert bp

        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = item_for(plan, ChangeType.CONFLICT, "Z")
        assert item is not None
        assert item.status == ItemStatus.BLOCKED
        assert item.blocking_reason == BLOCK_AMBIGUOUS_CODE
        assert item.requires_manual_review is True
        assert plan.conflict_items == 1

        # And no addition was proposed for the same code.
        assert item_for(plan, ChangeType.ADD_SECTION, "Z") is None

    def test_a_manual_section_with_no_collision_is_left_entirely_alone(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """Manual work is not the blueprint's business."""
        from submission_dossiers import services as ds

        ds.create_section(
            dossier=dossier_a,
            tenant=tenant_a,
            actor=admin_a,
            section_code="MANUAL-1",
            title="Mine",
        )
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        assert all(i.section_code != "MANUAL-1" for i in plan.items.all())

    def test_a_renamed_code_is_reported_as_retire_plus_add_not_a_rename(
        self, dossier_a, v1, tenant_a, admin_a
    ):
        """Two truthful statements rather than one inferred one."""
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        make_blueprint_section(draft, tenant_a, admin_a, "A.1-renamed", title="Section A.1")
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        assert item_for(plan, ChangeType.RETIRE_SECTION, "A.1") is not None
        assert item_for(plan, ChangeType.ADD_SECTION, "A.1-renamed") is not None


# ---------------------------------------------------------------------------
# Retirement safety
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRetirementSafety:
    def _drop_b(self, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="B"), tenant=tenant_a, actor=admin_a
        )
        return activate(draft, tenant_a, admin_a)

    def test_a_section_with_an_open_blocker_is_blocked(self, dossier_a, v1, tenant_a, admin_a):
        from submission_dossiers import services as ds

        ds.create_blocker(
            section=dossier_sections(dossier_a)["B"],
            tenant=tenant_a,
            actor=admin_a,
            title="Waiting on something",
        )
        plan = generate(dossier_a, tenant_a, admin_a, self._drop_b(v1, tenant_a, admin_a))
        item = item_for(plan, ChangeType.RETIRE_SECTION, "B")
        assert item.status == ItemStatus.BLOCKED
        assert item.blocking_reason == BLOCK_HAS_BLOCKERS

    def test_a_section_with_a_linked_document_is_blocked(self, dossier_a, v1, tenant_a, admin_a):
        from documents.models import Document
        from submission_dossiers import services as ds

        document = Document.objects.create(
            tenant=tenant_a, title="Synthetic document", document_type="other"
        )
        ds.link_target(
            kind="document",
            section=dossier_sections(dossier_a)["B"],
            target_public_id=document.public_id,
            actor=admin_a,
            tenant=tenant_a,
        )
        plan = generate(dossier_a, tenant_a, admin_a, self._drop_b(v1, tenant_a, admin_a))
        item = item_for(plan, ChangeType.RETIRE_SECTION, "B")
        assert item.status == ItemStatus.BLOCKED
        assert item.blocking_reason == BLOCK_HAS_LINKS

    def test_a_section_with_recorded_progress_is_blocked(self, dossier_a, v1, tenant_a, admin_a):
        from submission_dossiers import services as ds
        from submission_dossiers.models import SectionStatus

        ds.update_section(
            section=dossier_sections(dossier_a)["B"],
            tenant=tenant_a,
            actor=admin_a,
            status=SectionStatus.IN_PROGRESS,
        )
        plan = generate(dossier_a, tenant_a, admin_a, self._drop_b(v1, tenant_a, admin_a))
        item = item_for(plan, ChangeType.RETIRE_SECTION, "B")
        assert item.status == ItemStatus.BLOCKED
        assert item.blocking_reason == BLOCK_HAS_PROGRESS

    def test_a_section_with_an_owner_is_blocked(self, dossier_a, v1, tenant_a, admin_a, doer_a):
        from submission_dossiers import services as ds

        ds.update_section(
            section=dossier_sections(dossier_a)["B"],
            tenant=tenant_a,
            actor=admin_a,
            owner=doer_a,
        )
        plan = generate(dossier_a, tenant_a, admin_a, self._drop_b(v1, tenant_a, admin_a))
        assert item_for(plan, ChangeType.RETIRE_SECTION, "B").status == ItemStatus.BLOCKED

    def test_a_section_with_active_children_is_blocked(self, dossier_a, v1, tenant_a, admin_a):
        from dossier_blueprints import services as bp

        draft = draft_from(v1, tenant_a, admin_a)
        bp.retire_section(
            section=draft.sections.get(section_code="A.1"), tenant=tenant_a, actor=admin_a
        )
        bp.retire_section(
            section=draft.sections.get(section_code="A.2"), tenant=tenant_a, actor=admin_a
        )
        bp.retire_section(
            section=draft.sections.get(section_code="A"), tenant=tenant_a, actor=admin_a
        )
        target = activate(draft, tenant_a, admin_a)

        plan = generate(dossier_a, tenant_a, admin_a, target)
        parent = item_for(plan, ChangeType.RETIRE_SECTION, "A")
        assert parent.status == ItemStatus.BLOCKED
        assert parent.blocking_reason == BLOCK_HAS_CHILDREN

    def test_a_blocked_item_cannot_be_accepted(self, dossier_a, v1, tenant_a, admin_a):
        from submission_dossiers import services as ds

        ds.create_blocker(
            section=dossier_sections(dossier_a)["B"],
            tenant=tenant_a,
            actor=admin_a,
            title="Waiting",
        )
        plan = generate(dossier_a, tenant_a, admin_a, self._drop_b(v1, tenant_a, admin_a))
        item = item_for(plan, ChangeType.RETIRE_SECTION, "B")
        with pytest.raises(services.UpgradeLocked):
            services.set_item_status(item=item, tenant=tenant_a, actor=admin_a, accept=True)


# ---------------------------------------------------------------------------
# Generation rules
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGenerationRules:
    def test_generation_writes_nothing_to_the_dossier(self, dossier_a, v2, tenant_a, admin_a):
        """The property the whole milestone rests on."""
        before = fingerprint_for_dossier(dossier_a)
        generate(dossier_a, tenant_a, admin_a, v2)
        assert fingerprint_for_dossier(dossier_a) == before

    def test_the_source_version_comes_from_provenance_not_the_caller(
        self, dossier_a, v1, v2, tenant_a, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        assert plan.source_version_id == v1.pk

    def test_a_draft_target_is_refused(self, dossier_a, v1, tenant_a, admin_a):
        draft = draft_from(v1, tenant_a, admin_a)
        with pytest.raises(services.UpgradeLocked) as exc:
            generate(dossier_a, tenant_a, admin_a, draft)
        assert "active" in str(exc.value).lower()

    def test_a_retired_target_is_refused(self, dossier_a, v1, v2, tenant_a, admin_a):
        """v1 was retired when v2 was published; it must not seed a new plan."""
        v1.refresh_from_db()
        assert v1.status == "retired"
        with pytest.raises(services.UpgradeLocked):
            generate(dossier_a, tenant_a, admin_a, v1)

    def test_the_current_version_cannot_be_the_target(self, dossier_a, v1, tenant_a, admin_a):
        with pytest.raises(services.UpgradeLocked) as exc:
            generate(dossier_a, tenant_a, admin_a, v1)
        assert "already at that version" in str(exc.value).lower()

    def test_a_target_from_a_different_blueprint_is_refused(self, dossier_a, tenant_a, admin_a):
        """Cross-blueprint upgrade is meaningless: no section correspondence
        exists between two unrelated outlines."""
        from dossier_blueprints import services as bp
        from dossier_upgrades.tests.conftest import publish

        other = bp.create_blueprint(tenant=tenant_a, actor=admin_a, name="Unrelated outline")
        other_v1 = publish(other, tenant_a, admin_a, [("Q", None, {})])

        with pytest.raises(services.InvalidTarget):
            generate(dossier_a, tenant_a, admin_a, other_v1)

    def test_a_dossier_with_no_blueprint_provenance_is_refused(self, tenant_a, admin_a, case_a, v2):
        from submission_dossiers import services as ds

        manual = ds.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Built by hand"
        )
        with pytest.raises(services.UpgradeLocked) as exc:
            generate(manual, tenant_a, admin_a, v2)
        assert "not created from a blueprint" in str(exc.value).lower()

    def test_only_one_open_plan_per_target(self, dossier_a, v2, tenant_a, admin_a):
        """Two live proposals for the same move are a review hazard: a reviewer
        accepting items on one cannot see the other."""
        generate(dossier_a, tenant_a, admin_a, v2)
        with pytest.raises(services.UpgradeLocked) as exc:
            generate(dossier_a, tenant_a, admin_a, v2)
        assert "already exists" in str(exc.value).lower()

    def test_a_cancelled_plan_frees_the_slot(self, dossier_a, v2, tenant_a, admin_a):
        first = generate(dossier_a, tenant_a, admin_a, v2)
        services.cancel_plan(plan=first, tenant=tenant_a, actor=admin_a)
        second = generate(dossier_a, tenant_a, admin_a, v2)
        assert second.pk != first.pk
        assert DossierUpgradePlan.objects.filter(dossier=dossier_a).count() == 2


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReview:
    def test_accepting_an_item_writes_nothing_to_the_dossier(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        """Accept is a decision, not an action."""
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        before = fingerprint_for_dossier(dossier_a)
        item = item_for(plan, ChangeType.UPDATE_TITLE)
        services.set_item_status(item=item, tenant=tenant_a, actor=admin_a, accept=True)
        assert fingerprint_for_dossier(dossier_a) == before

    def test_accept_and_reject_are_recorded_with_the_reviewer(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        accepted = services.set_item_status(
            item=item_for(plan, ChangeType.UPDATE_TITLE),
            tenant=tenant_a,
            actor=admin_a,
            accept=True,
        )
        rejected = services.set_item_status(
            item=item_for(plan, ChangeType.UPDATE_REQUIRED),
            tenant=tenant_a,
            actor=admin_a,
            accept=False,
        )
        assert accepted.status == ItemStatus.ACCEPTED
        assert accepted.reviewed_by_id == admin_a.pk
        assert rejected.status == ItemStatus.REJECTED

    def test_a_no_change_item_cannot_be_accepted(self, dossier_a, v1, tenant_a, admin_a):
        draft = draft_from(v1, tenant_a, admin_a)
        target = activate(draft, tenant_a, admin_a)
        plan = generate(dossier_a, tenant_a, admin_a, target)
        item = item_for(plan, ChangeType.NO_CHANGE)
        with pytest.raises(services.UpgradeLocked):
            services.set_item_status(item=item, tenant=tenant_a, actor=admin_a, accept=True)

    def test_ready_requires_every_actionable_item_reviewed(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        with pytest.raises(services.UpgradeLocked) as exc:
            services.mark_ready(plan=plan, tenant=tenant_a, actor=admin_a)
        assert "accepted or rejected" in str(exc.value).lower()

    def test_ready_is_not_an_approval(self, dossier_a, v2, tenant_a, admin_a):
        """Pins the vocabulary: there is no APPROVED state to reach."""
        assert set(PlanStatus.values) == {"draft", "ready", "applied", "cancelled"}
        assert "approved" not in PlanStatus.values

    def test_items_of_a_cancelled_plan_are_final(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        services.cancel_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.UpgradeLocked):
            services.set_item_status(
                item=item_for(plan, ChangeType.UPDATE_TITLE),
                tenant=tenant_a,
                actor=admin_a,
                accept=True,
            )


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStaleness:
    def test_a_fresh_plan_is_not_stale(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        assert services.is_stale(plan) is False

    @pytest.mark.parametrize("mutation", ["add", "retire", "rename", "reorder"])
    def test_any_structural_change_makes_the_plan_stale(
        self, dossier_a, v2, tenant_a, admin_a, mutation
    ):
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        sections = dossier_sections(dossier_a)

        if mutation == "add":
            ds.create_section(
                dossier=dossier_a,
                tenant=tenant_a,
                actor=admin_a,
                section_code="NEW",
                title="New",
            )
        elif mutation == "retire":
            ds.retire_section(section=sections["A.1"], tenant=tenant_a, actor=admin_a)
        elif mutation == "rename":
            ds.update_section(
                section=sections["A.1"], tenant=tenant_a, actor=admin_a, title="Renamed"
            )
        elif mutation == "reorder":
            ds.reorder_section(section=sections["A.2"], tenant=tenant_a, actor=admin_a, sequence=0)

        plan.refresh_from_db()
        assert services.is_stale(plan) is True

    def test_a_runtime_change_does_NOT_make_the_plan_stale(
        self, dossier_a, v2, tenant_a, admin_a, doer_a
    ):
        """Deliberate. If ticking a status or taking ownership invalidated every
        open plan, users would learn to regenerate reflexively and stop reading
        the guard at all."""
        from submission_dossiers import services as ds
        from submission_dossiers.models import SectionStatus

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        ds.update_section(
            section=dossier_sections(dossier_a)["A.1"],
            tenant=tenant_a,
            actor=admin_a,
            status=SectionStatus.IN_PROGRESS,
            owner=doer_a,
            notes="Some notes",
        )
        plan.refresh_from_db()
        assert services.is_stale(plan) is False

    def test_regenerate_refreshes_the_fingerprint_and_resets_review(
        self, dossier_a, v2, tenant_a, admin_a
    ):
        from submission_dossiers import services as ds

        plan = generate(dossier_a, tenant_a, admin_a, v2)
        services.set_item_status(
            item=item_for(plan, ChangeType.UPDATE_TITLE),
            tenant=tenant_a,
            actor=admin_a,
            accept=True,
        )
        ds.create_section(
            dossier=dossier_a, tenant=tenant_a, actor=admin_a, section_code="NEW", title="New"
        )
        assert services.is_stale(plan) is True

        regenerated = services.regenerate_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert services.is_stale(regenerated) is False
        assert regenerated.status == PlanStatus.DRAFT
        # Review decisions are deliberately not carried over: an accept was a
        # judgement about a dossier that has since moved.
        assert not regenerated.items.filter(status=ItemStatus.ACCEPTED).exists()

    def test_the_plan_public_id_survives_a_regenerate(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        original = plan.public_id
        regenerated = services.regenerate_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        assert regenerated.public_id == original

    def test_a_terminal_plan_cannot_be_regenerated(self, dossier_a, v2, tenant_a, admin_a):
        plan = generate(dossier_a, tenant_a, admin_a, v2)
        services.cancel_plan(plan=plan, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.UpgradeLocked):
            services.regenerate_plan(plan=plan, tenant=tenant_a, actor=admin_a)
