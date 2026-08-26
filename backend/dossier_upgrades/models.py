"""Blueprint change impact and controlled dossier upgrades.

**BLUEPRINT CHANGE IS NOT DOSSIER CHANGE.**

Milestone 10 made a dossier an independent snapshot: publishing blueprint v2
cannot touch a dossier built from v1, and that is deliberate. This adds the only
sanctioned way to move one forward -- a plan a human generates, reviews item by
item, and explicitly applies. Nothing here ever mutates a dossier as a side
effect of a blueprint changing.

A plan is a **proposal**. Generating one is read-only. Accepting an item changes
nothing. Only `apply` writes, only accepted items are written, and every write
goes through the Milestone 9 sanctioned section services so the `0004` window
and its triggers still hold.

> **READY means the plan has been reviewed internally and may be applied.** It
> is not a regulatory approval, a QA approval, an agency decision, or any claim
> about the submission. There is deliberately no APPROVED state.

**No production regulatory structure and no regulatory judgement.** Nothing here
knows what a submission requires; it compares two tenant-authored outlines and
reports the differences.

---

WHY MATCHING IS DERIVED, NOT LOOKED UP

`dossier_blueprints._clone_sections` creates fresh rows for a new version and
records no pointer back to the section it copied -- it builds a local `mapping`
and discards it. So there is no stored lineage between v1 and v2 sections, and
comparison has to be derived.

Two facts make that safe rather than guesswork:

  * `unique_active_blueprint_section_code` makes `section_code` unique among a
    version's active sections, so a code identifies at most one section per
    version. Blueprint-to-blueprint matching by code is exact, not heuristic.
  * `BlueprintSectionOrigin` (Milestone 10) records exactly which dossier
    section came from which source-version blueprint section, so the dossier
    side is anchored by a stored fact rather than inferred.

The chain is therefore
`dossier section -> (stored origin) -> source section -> (unique code) -> target
section`, and each hop is backed by a constraint or a row.

Where a hop is missing -- a dossier section added by hand after instantiation,
carrying no origin row, whose code collides with a target section -- the
comparison **refuses to guess** and emits `CONFLICT`. See
`services.compare_for_upgrade`.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .governance import UpgradeMutationForbidden

PLAN_FROZEN_MESSAGE = (
    "Upgrade plans are governed; use dossier_upgrades.services rather than writing rows directly."
)
PLAN_DELETE_MESSAGE = "Upgrade plans cannot be deleted; cancel the plan instead."
HISTORY_MESSAGE = "Applied upgrade history is a permanent record and cannot be changed."


class PlanStatus(models.TextChoices):
    """Deliberately four states, and deliberately no APPROVED.

    READY means "reviewed internally, may be applied". `templates_registry` owns
    an APPROVED state backed by a real approval trail tied to the regulatory
    content gate, and borrowing the word here would assert a decision nobody
    made -- the same reasoning that kept it out of `dossier_blueprints`.
    """

    DRAFT = "draft", "Draft"
    READY = "ready", "Ready to apply"
    APPLIED = "applied", "Applied"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_PLAN_STATUSES = frozenset({PlanStatus.APPLIED, PlanStatus.CANCELLED})


class ChangeType(models.TextChoices):
    """What the target version does to one section, relative to the dossier.

    Structural and default-metadata only. Runtime state -- readiness, status,
    blockers, document / workflow / checklist links, owner, notes -- is never
    blueprint-controlled and never appears here. A blueprint has no opinion
    about work in progress.
    """

    ADD_SECTION = "add_section", "Add section"
    RETIRE_SECTION = "retire_section", "Retire section"
    UPDATE_TITLE = "update_title", "Update title"
    UPDATE_DESCRIPTION = "update_description", "Update description"
    UPDATE_REQUIRED = "update_required", "Update required flag"
    MOVE_SECTION = "move_section", "Move under a different parent"
    REORDER_SECTION = "reorder_section", "Reorder within siblings"
    UPDATE_DUE_OFFSET = "update_due_offset", "Update default due offset"
    NO_CHANGE = "no_change", "No change"
    CONFLICT = "conflict", "Conflict -- needs manual review"


#: Change types that write something when applied. `NO_CHANGE` and `CONFLICT`
#: never do, whatever their item status says.
ACTIONABLE_CHANGE_TYPES = frozenset(
    {
        ChangeType.ADD_SECTION,
        ChangeType.RETIRE_SECTION,
        ChangeType.UPDATE_TITLE,
        ChangeType.UPDATE_DESCRIPTION,
        ChangeType.UPDATE_REQUIRED,
        ChangeType.MOVE_SECTION,
        ChangeType.REORDER_SECTION,
        ChangeType.UPDATE_DUE_OFFSET,
    }
)


class ItemStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    BLOCKED = "blocked", "Blocked"
    APPLIED = "applied", "Applied"


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------
class _NoWriteQuerySet(models.QuerySet):
    """Public queryset: reads freely, writes nothing.

    The Milestone 9 finding, applied from the start: leaving `update()` open
    "because a service needs it" is how a governance bypass ships. The service
    layer uses `governed`, and the `0002` triggers hold every statement whatever
    manager issued it.
    """

    delete_message = PLAN_FROZEN_MESSAGE

    def delete(self):
        raise UpgradeMutationForbidden(self.delete_message)

    def update(self, **kwargs):
        raise UpgradeMutationForbidden(PLAN_FROZEN_MESSAGE)

    def bulk_update(self, objs, fields, batch_size=None):
        raise UpgradeMutationForbidden(PLAN_FROZEN_MESSAGE)


class _PlanQuerySet(_NoWriteQuerySet):
    delete_message = PLAN_DELETE_MESSAGE


class _HistoryQuerySet(_NoWriteQuerySet):
    delete_message = HISTORY_MESSAGE


class _GovernedQuerySet(models.QuerySet):
    """Internal queryset for the service layer, for plans and history.

    Permits `update()`. Never permits `delete()`: a plan is cancelled, never
    removed, and applied history is permanent.
    """

    def delete(self):
        raise UpgradeMutationForbidden(PLAN_DELETE_MESSAGE)


class _GovernedItemQuerySet(models.QuerySet):
    """Internal queryset for plan items only.

    Permits `delete()`, because `services.regenerate_plan` legitimately replaces
    an open plan's proposal wholesale. Reaching it is not permission to delete
    anything: the `0002` trigger still refuses removal once the parent plan is
    applied or cancelled, so the permission granted here is exactly "an open
    plan's working items", and the database is what enforces the boundary.
    """


def _manager(queryset_class):
    class _Manager(models.Manager):
        def get_queryset(self):
            return queryset_class(self.model, using=self._db)

    return _Manager


PlanManager = _manager(_PlanQuerySet)
ItemManager = _manager(_NoWriteQuerySet)
HistoryManager = _manager(_HistoryQuerySet)
GovernedManager = _manager(_GovernedQuerySet)
GovernedItemManager = _manager(_GovernedItemQuerySet)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
class DossierUpgradePlan(PublicIDModel, TimeStampedModel):
    """A reviewed proposal to move one dossier from one blueprint version to
    another. Holds no authority of its own: it describes, it does not act."""

    objects = PlanManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_upgrade_plans"
    )
    dossier = models.ForeignKey(
        "submission_dossiers.SubmissionDossier",
        on_delete=models.PROTECT,
        related_name="upgrade_plans",
    )
    blueprint = models.ForeignKey(
        "dossier_blueprints.DossierBlueprint", on_delete=models.PROTECT, related_name="+"
    )
    #: The version the dossier is currently at, taken from its provenance --
    #: never supplied by the caller. See `services.generate_plan`.
    source_version = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintVersion",
        on_delete=models.PROTECT,
        related_name="upgrade_plans_as_source",
    )
    target_version = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintVersion",
        on_delete=models.PROTECT,
        related_name="upgrade_plans_as_target",
    )

    status = models.CharField(
        max_length=12, choices=PlanStatus.choices, default=PlanStatus.DRAFT, db_index=True
    )
    notes = models.TextField(blank=True)

    #: Canonical hash of the dossier's structure at generation time. Recomputed
    #: before apply; a mismatch means the dossier moved underneath the plan and
    #: the plan is stale. See `fingerprint.structural_fingerprint`.
    dossier_fingerprint = models.CharField(max_length=64)

    #: Denormalised counts, so a list view needs no per-plan aggregate.
    total_items = models.PositiveIntegerField(default=0)
    actionable_items = models.PositiveIntegerField(default=0)
    conflict_items = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # At most one open plan per (dossier, target). Two live proposals
            # for the same move are a review hazard, not a feature: a reviewer
            # accepting items on one has no way to see the other. Applied and
            # cancelled plans stay as history, so the partial condition matters.
            models.UniqueConstraint(
                fields=["dossier", "target_version"],
                condition=models.Q(status__in=["draft", "ready"]),
                name="unique_open_upgrade_plan_per_target",
            ),
            # A plan cannot target the version it is coming from.
            models.CheckConstraint(
                condition=~models.Q(source_version=models.F("target_version")),
                name="upgrade_plan_source_differs_from_target",
            ),
            # Lifecycle stamps must agree with the status at any instant. The
            # trigger enforces the transitions; this enforces the state.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=["draft", "ready"],
                        applied_at__isnull=True,
                        cancelled_at__isnull=True,
                    )
                    | models.Q(
                        status="applied", applied_at__isnull=False, cancelled_at__isnull=True
                    )
                    | models.Q(status="cancelled", cancelled_at__isnull=False)
                ),
                name="upgrade_plan_stamps_are_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["dossier", "status"]),
        ]

    def __str__(self):
        return f"upgrade {self.source_version_id}->{self.target_version_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in (PlanStatus.DRAFT, PlanStatus.READY)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PLAN_STATUSES

    def delete(self, using=None, keep_parents=False):
        raise UpgradeMutationForbidden(PLAN_DELETE_MESSAGE)


class DossierUpgradePlanItem(PublicIDModel, TimeStampedModel):
    """One proposed change, reviewed on its own.

    `before_value` / `after_value` are short scalar renderings of the single
    field a metadata change touches -- never a blob of the whole section. A
    reviewer needs "Required: yes -> no", not a JSON dump they will skim.
    """

    objects = ItemManager()
    governed = GovernedItemManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_upgrade_plan_items"
    )
    plan = models.ForeignKey(DossierUpgradePlan, on_delete=models.PROTECT, related_name="items")

    change_type = models.CharField(max_length=24, choices=ChangeType.choices, db_index=True)
    status = models.CharField(
        max_length=12, choices=ItemStatus.choices, default=ItemStatus.PROPOSED, db_index=True
    )

    #: The dossier section this item is about, when one exists. Null for an
    #: addition, which has nothing in the dossier yet.
    dossier_section = models.ForeignKey(
        "submission_dossiers.DossierSection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="upgrade_plan_items",
    )
    #: The target-version blueprint section driving the change, when one exists.
    #: Null for a retirement, which exists only in the source.
    target_section = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintSection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_section = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintSection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    #: Display metadata so an item is readable without joining. Short by design.
    section_code = models.CharField(max_length=100, blank=True)
    field_name = models.CharField(max_length=40, blank=True)
    before_value = models.CharField(max_length=255, blank=True)
    after_value = models.CharField(max_length=255, blank=True)

    #: Why this item cannot be applied, as a coarse enumerated reason. Never
    #: prose describing the submission.
    blocking_reason = models.CharField(max_length=64, blank=True)
    requires_manual_review = models.BooleanField(default=False)

    #: Deterministic apply order within the plan.
    sequence = models.PositiveIntegerField(default=0)

    reviewed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sequence", "id"]
        indexes = [
            models.Index(fields=["plan", "status"]),
            models.Index(fields=["tenant"]),
        ]

    def __str__(self):
        return f"{self.change_type} {self.section_code} ({self.status})"

    @property
    def is_actionable(self) -> bool:
        return self.change_type in ACTIONABLE_CHANGE_TYPES

    def delete(self, using=None, keep_parents=False):
        raise UpgradeMutationForbidden(PLAN_FROZEN_MESSAGE)


# ---------------------------------------------------------------------------
# Upgrade provenance
#
# Separate from `dossier_blueprints.BlueprintInstantiation` on purpose. That row
# records how the dossier was CREATED and stays immutable historical truth; an
# upgrade is a later, additional event. Rewriting the instantiation to say the
# dossier "came from v2" would erase the fact that it was built from v1 and then
# moved -- and Milestone 10's triggers refuse it anyway, correctly.
# ---------------------------------------------------------------------------
class DossierUpgradeApplication(PublicIDModel, TimeStampedModel):
    """The permanent record that one plan was applied to one dossier.

    A dossier may accumulate several: v1 instantiated, v2 applied, v3 applied.
    The sequence is ordered and append-only, so the whole path is readable.
    """

    objects = HistoryManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_upgrade_applications"
    )
    dossier = models.ForeignKey(
        "submission_dossiers.SubmissionDossier",
        on_delete=models.PROTECT,
        related_name="upgrade_applications",
    )
    #: OneToOne: a plan is applied at most once, and the constraint says so
    #: rather than relying on the status check alone.
    plan = models.OneToOneField(
        DossierUpgradePlan, on_delete=models.PROTECT, related_name="application"
    )
    blueprint = models.ForeignKey(
        "dossier_blueprints.DossierBlueprint", on_delete=models.PROTECT, related_name="+"
    )
    source_version = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintVersion", on_delete=models.PROTECT, related_name="+"
    )
    target_version = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintVersion", on_delete=models.PROTECT, related_name="+"
    )

    #: Immutable snapshots, for the same reason Milestone 10 keeps them: the FKs
    #: say which row, these say what it said at the time.
    source_version_number = models.PositiveIntegerField()
    target_version_number = models.PositiveIntegerField()

    sections_added = models.PositiveIntegerField(default=0)
    sections_retired = models.PositiveIntegerField(default=0)
    sections_updated = models.PositiveIntegerField(default=0)

    applied_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["dossier", "created_at"]),
        ]

    def __str__(self):
        return f"v{self.source_version_number}->v{self.target_version_number}"

    def delete(self, using=None, keep_parents=False):
        raise UpgradeMutationForbidden(HISTORY_MESSAGE)


class UpgradeSectionOrigin(PublicIDModel):
    """Which target-version blueprint section produced a section added by an
    upgrade.

    Milestone 10's `BlueprintSectionOrigin` cannot carry this: its INSERT guard
    requires the blueprint section to belong to the instantiation's version, and
    a section added by an upgrade comes from a later one. That refusal is
    correct, so upgrade-added sections get their own origin record here and the
    original creation provenance is left exactly as it was.

    **Nothing reads this to decide behaviour.** A dossier section's meaning never
    depends on the blueprint section it came from; that is what makes the
    snapshot a snapshot.
    """

    objects = HistoryManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="upgrade_section_origins"
    )
    application = models.ForeignKey(
        DossierUpgradeApplication, on_delete=models.PROTECT, related_name="section_origins"
    )
    dossier_section = models.OneToOneField(
        "submission_dossiers.DossierSection",
        on_delete=models.PROTECT,
        related_name="upgrade_origin",
    )
    blueprint_section = models.ForeignKey(
        "dossier_blueprints.DossierBlueprintSection", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["application"])]

    def __str__(self):
        return f"{self.blueprint_section_id} -> {self.dossier_section_id}"

    def delete(self, using=None, keep_parents=False):
        raise UpgradeMutationForbidden(HISTORY_MESSAGE)


__all__ = [
    "ACTIONABLE_CHANGE_TYPES",
    "TERMINAL_PLAN_STATUSES",
    "ChangeType",
    "DossierUpgradeApplication",
    "DossierUpgradePlan",
    "DossierUpgradePlanItem",
    "ItemStatus",
    "PlanStatus",
    "UpgradeMutationForbidden",
    "UpgradeSectionOrigin",
]
