"""Dossier blueprints: reusable, versioned, tenant-controlled dossier outlines.

**Blueprints define structure. Dossiers own execution.**

Milestone 9 lets a user build a dossier outline by hand. This lets a tenant
capture that outline once, version it, and stamp it out into as many cases as
they like. What comes out the other side is ordinary `submission_dossiers`
records: once instantiated, a dossier never reads from its blueprint again, and
publishing version 2 cannot silently rewrite a dossier built from version 1.

**ACTIVE means available for internal RegX dossier instantiation.** It is not a
regulatory approval, a QA approval, an agency approval, or a validated status.
There is deliberately no APPROVED state -- see the note on `templates_registry`
below.

**No production regulatory structure ships here.** No CTD modules, no CEP, DMF or
ANDA structures, no country or agency requirements. `section_code` is free text
and the engine must be able to represent those structures without encoding any
of them.

---

RELATIONSHIP TO `templates_registry` (discovery, Milestone 10 section 1)

`templates_registry` already provides a controlled-template system: stable
identity across versions (`RegulatoryTemplate`), numbered versions
(`TemplateVersion` with `unique_template_version_number`), a full
draft/review/approved/active/superseded/retired lifecycle, immutable published
versions, an "only one active version" partial unique index, tenant scoping, a
self-referencing section tree (`TemplateSection.parent_section`), an importer and
an approval trail.

It is **composed with, not reused**, for four reasons:

1. **Semantics.** `TemplateLifecycleStatus` includes `APPROVED`, backed by
   `TemplateApproval` rows carrying reviewer, decision and role-at-time. That is
   the *regulatory content approval* concept tied to the governance gate. A
   blueprint reaching that state would be indistinguishable in the data model
   from an approved regulatory template. A dossier outline is a tenant's
   internal working convenience; calling it "approved" would assert something
   nobody decided.

2. **Content model.** `TemplateSection` carries `raw_title`,
   `normalized_title`, `source_locator` and importer `metadata`, and owns
   `TemplateItem` questions with a `ResponseType`. It is a questionnaire tree,
   not a dossier outline. A blueprint section needs `required` and
   `default_due_offset_days`, which would mean adding columns to a governed,
   approval-gated table for an unrelated purpose.

3. **Deletion governance is the opposite.** `RegulatoryTemplate.tenant` is
   `CASCADE` and nullable for platform-level masters; `TemplateSection`'s FKs are
   `CASCADE`. Milestones 8 and 9 established mandatory tenant, `PROTECT`
   everywhere and retire-never-delete. Hosting blueprints under `CASCADE` would
   regress guarantees that took three review rounds to establish.

4. **Coupling direction.** Instantiation must go blueprint -> submission_dossiers.
   Putting it inside `templates_registry` would make the regulatory content
   registry depend on the execution layer, which the import-linter contracts
   deliberately keep isolated.

What IS reused is its **patterns, verbatim**: `unique(blueprint, version_number)`
from `unique_template_version_number`; the partial unique index on the ACTIVE
status from `unique_active_version_per_template`; an immutable-status frozenset;
and `select_for_update` over the sibling version set during activation, from
`templates_registry.lifecycle.activate`.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .governance import BlueprintMutationForbidden

#: Same operational ceiling as `submission_dossiers.MAX_SECTION_DEPTH`, and for
#: the same reason: it keeps the ancestor walk cheap and stops a hostile payload
#: building a chain that makes instantiation expensive. Operational, not
#: regulatory. A blueprint deeper than a dossier may hold would be useless
#: anyway, so the two are deliberately equal and asserted so in the tests.
MAX_BLUEPRINT_DEPTH = 10

SECTION_DELETE_MESSAGE = "Blueprint sections cannot be deleted; retire the section instead."
VERSION_DELETE_MESSAGE = "Blueprint versions cannot be deleted; retire the version instead."
FROZEN_MESSAGE = (
    "Blueprint structure is governed; use dossier_blueprints.services rather than "
    "writing rows directly."
)
PROVENANCE_MESSAGE = "Blueprint provenance is a permanent record and cannot be changed."


class BlueprintVersionStatus(models.TextChoices):
    """Deliberately three states, and deliberately no APPROVED.

    ACTIVE means "available for internal RegX dossier instantiation" and nothing
    more. `templates_registry` has an APPROVED state with a real approval trail
    attached to the regulatory content gate; borrowing that word here would
    assert a decision nobody made.
    """

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


#: Content of a version in either of these is frozen forever. Mirrors
#: `templates_registry.IMMUTABLE_VERSION_STATUSES` in intent: corrections require
#: a new version, never an edit to a published one.
IMMUTABLE_VERSION_STATUSES = frozenset(
    {BlueprintVersionStatus.ACTIVE, BlueprintVersionStatus.RETIRED}
)


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------
class _NoWriteQuerySet(models.QuerySet):
    """Public queryset for governed blueprint rows: reads freely, writes nothing.

    Following the Milestone 9 finding: leaving `update()`/`bulk_update()` open
    "because a service needs them" is how a governance bypass gets shipped. The
    service layer uses `governed` instead, and the `0002` triggers hold every
    statement regardless of which manager issued it.
    """

    delete_message = FROZEN_MESSAGE

    def delete(self):
        raise BlueprintMutationForbidden(self.delete_message)

    def update(self, **kwargs):
        raise BlueprintMutationForbidden(FROZEN_MESSAGE)

    def bulk_update(self, objs, fields, batch_size=None):
        raise BlueprintMutationForbidden(FROZEN_MESSAGE)


class _VersionQuerySet(_NoWriteQuerySet):
    delete_message = VERSION_DELETE_MESSAGE


class _SectionQuerySet(_NoWriteQuerySet):
    delete_message = SECTION_DELETE_MESSAGE


class _GovernedQuerySet(models.QuerySet):
    """Internal queryset for the service layer.

    Permits `update()`/`bulk_update()` and never `delete()`. Reaching it is not
    permission to write anything: every statement still meets the `0002`
    triggers, which decide what a DRAFT version may change and refuse everything
    on a published one.
    """

    delete_message = FROZEN_MESSAGE

    def delete(self):
        raise BlueprintMutationForbidden(self.delete_message)


def _manager(queryset_class):
    class _Manager(models.Manager):
        def get_queryset(self):
            return queryset_class(self.model, using=self._db)

    return _Manager


BlueprintManager = _manager(_NoWriteQuerySet)
VersionManager = _manager(_VersionQuerySet)
SectionManager = _manager(_SectionQuerySet)
GovernedManager = _manager(_GovernedQuerySet)


# ---------------------------------------------------------------------------
# Blueprint identity
# ---------------------------------------------------------------------------
class DossierBlueprint(PublicIDModel, TimeStampedModel):
    """The stable identity a blueprint keeps across its versions.

    Holds no structure. Everything a dossier is built from lives on a version,
    so renaming a blueprint can never change what an existing dossier was built
    from -- and the instantiation record snapshots the name anyway.
    """

    objects = BlueprintManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_blueprints"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_dossier_blueprints",
    )
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            # Partial on archived_at, so archiving frees the name rather than
            # burning it permanently -- the same reasoning as a retired dossier
            # section freeing its code.
            models.UniqueConstraint(
                fields=["tenant", "name"],
                condition=models.Q(archived_at__isnull=True),
                name="unique_active_blueprint_name_per_tenant",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "archived_at"])]

    def __str__(self):
        return self.name

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def delete(self, using=None, keep_parents=False):
        raise BlueprintMutationForbidden(
            "Blueprints cannot be deleted; archive the blueprint instead."
        )


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
class DossierBlueprintVersion(PublicIDModel, TimeStampedModel):
    """One immutable-once-published revision of a blueprint's structure."""

    objects = VersionManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_blueprint_versions"
    )
    blueprint = models.ForeignKey(
        DossierBlueprint, on_delete=models.PROTECT, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10,
        choices=BlueprintVersionStatus.choices,
        default=BlueprintVersionStatus.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True)

    #: The version this one was cloned from, if any. Kept for provenance only;
    #: nothing reads it to decide behaviour.
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-version_number", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "version_number"],
                name="unique_blueprint_version_number",
            ),
            # Defence in depth, copied from
            # `templates_registry.unique_active_version_per_template`: the
            # service enforces "one ACTIVE version" transactionally with
            # select_for_update, and this makes it impossible even if a future
            # code path skips the service.
            models.UniqueConstraint(
                fields=["blueprint"],
                condition=models.Q(status=BlueprintVersionStatus.ACTIVE),
                name="unique_active_blueprint_version",
            ),
            # The lifecycle stamps must agree with the status at any instant.
            # A trigger enforces the *transitions*; this enforces the *state*.
            models.CheckConstraint(
                condition=(
                    models.Q(status="draft", activated_at__isnull=True, retired_at__isnull=True)
                    | models.Q(status="active", activated_at__isnull=False, retired_at__isnull=True)
                    | models.Q(status="retired", retired_at__isnull=False)
                ),
                name="blueprint_version_stamps_are_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["blueprint", "status"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"{self.blueprint.name} v{self.version_number} ({self.status})"

    @property
    def is_draft(self) -> bool:
        return self.status == BlueprintVersionStatus.DRAFT

    @property
    def is_immutable(self) -> bool:
        return self.status in IMMUTABLE_VERSION_STATUSES

    def delete(self, using=None, keep_parents=False):
        raise BlueprintMutationForbidden(VERSION_DELETE_MESSAGE)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
class DossierBlueprintSection(PublicIDModel, TimeStampedModel):
    """One node of a blueprint version's outline.

    **Structure only.** No status, readiness, blockers, links or evidence: those
    belong to the instantiated `submission_dossiers.DossierSection`, which is the
    governed execution record. A blueprint that carried runtime state would drift
    from the dossiers built out of it the moment either changed.
    """

    objects = SectionManager()
    governed = GovernedManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="dossier_blueprint_sections"
    )
    blueprint_version = models.ForeignKey(
        DossierBlueprintVersion, on_delete=models.PROTECT, related_name="sections"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )

    #: Arbitrary organisational metadata: "1", "1.1", "A", "Response-01". No CTD
    #: parser, no regex requiring regulatory syntax. Hierarchy comes from
    #: `parent`, never from splitting this string.
    section_code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    sequence = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)

    #: Tenant configuration, not a regulatory timeline. When a dossier carries a
    #: target date, an instantiated section's due date is
    #: `target_date - default_due_offset_days`. No default is invented: null
    #: means the section simply has no due date.
    default_due_offset_days = models.PositiveIntegerField(null=True, blank=True)

    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint_version", "section_code"],
                condition=models.Q(retired_at__isnull=True),
                name="unique_active_blueprint_section_code",
            ),
            # Two constraints, because PostgreSQL treats NULLs as distinct and a
            # single (version, parent, sequence) constraint would not constrain
            # root sections at all. Same shape as the M9 dossier section rules.
            models.UniqueConstraint(
                fields=["blueprint_version", "parent", "sequence"],
                condition=models.Q(retired_at__isnull=True, parent__isnull=False),
                name="unique_blueprint_child_sequence",
            ),
            models.UniqueConstraint(
                fields=["blueprint_version", "sequence"],
                condition=models.Q(retired_at__isnull=True, parent__isnull=True),
                name="unique_blueprint_root_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=["blueprint_version", "parent", "sequence"]),
            models.Index(fields=["blueprint_version", "retired_at"]),
            models.Index(fields=["tenant"]),
        ]

    def __str__(self):
        return f"{self.section_code} {self.title}"

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None

    def delete(self, using=None, keep_parents=False):
        raise BlueprintMutationForbidden(SECTION_DELETE_MESSAGE)


# ---------------------------------------------------------------------------
# Provenance
#
# A separate model rather than columns on `submission_dossiers.SubmissionDossier`
# for two reasons: Milestone 9 is still under review and adding fields to its
# model would entangle the two, and provenance is genuinely its own record with
# its own immutability rules. It also gives the per-section origin mapping
# somewhere natural to hang.
# ---------------------------------------------------------------------------
class BlueprintInstantiation(PublicIDModel, TimeStampedModel):
    """The permanent record that one dossier was stamped out of one version.

    Snapshot fields sit alongside the foreign keys on purpose. The FKs answer
    "which row", and are `PROTECT`ed so the row cannot vanish; the snapshots
    answer "what did it say at the time", which a rename would otherwise destroy.
    Neither is reachable for update: the whole row is immutable.
    """

    objects = BlueprintManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="blueprint_instantiations"
    )
    dossier = models.OneToOneField(
        "submission_dossiers.SubmissionDossier",
        on_delete=models.PROTECT,
        related_name="blueprint_instantiation",
    )
    blueprint = models.ForeignKey(
        DossierBlueprint, on_delete=models.PROTECT, related_name="instantiations"
    )
    blueprint_version = models.ForeignKey(
        DossierBlueprintVersion, on_delete=models.PROTECT, related_name="instantiations"
    )

    #: Immutable snapshots. `version_number` because a reviewer reading an audit
    #: trail should not have to join to learn it; `blueprint_name` because a
    #: blueprint may be renamed and the dossier was built from what it said then.
    version_number = models.PositiveIntegerField()
    blueprint_name = models.CharField(max_length=255)
    section_count = models.PositiveIntegerField()

    instantiated_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["blueprint_version"]),
        ]

    def __str__(self):
        return f"{self.blueprint_name} v{self.version_number} -> {self.dossier_id}"

    def delete(self, using=None, keep_parents=False):
        raise BlueprintMutationForbidden(PROVENANCE_MESSAGE)


class BlueprintSectionOrigin(PublicIDModel):
    """Which blueprint section produced which dossier section.

    Recorded for future template comparison. **Nothing reads it to decide
    behaviour** -- a dossier section's meaning never depends on the blueprint
    section it came from, which is the whole point of instantiating a snapshot
    rather than a live reference.
    """

    objects = BlueprintManager()

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, related_name="blueprint_section_origins"
    )
    instantiation = models.ForeignKey(
        BlueprintInstantiation, on_delete=models.PROTECT, related_name="section_origins"
    )
    dossier_section = models.OneToOneField(
        "submission_dossiers.DossierSection",
        on_delete=models.PROTECT,
        related_name="blueprint_origin",
    )
    blueprint_section = models.ForeignKey(
        DossierBlueprintSection, on_delete=models.PROTECT, related_name="origins"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["instantiation"])]

    def __str__(self):
        return f"{self.blueprint_section_id} -> {self.dossier_section_id}"

    def delete(self, using=None, keep_parents=False):
        raise BlueprintMutationForbidden(PROVENANCE_MESSAGE)


__all__ = [
    "IMMUTABLE_VERSION_STATUSES",
    "MAX_BLUEPRINT_DEPTH",
    "BlueprintInstantiation",
    "BlueprintMutationForbidden",
    "BlueprintSectionOrigin",
    "BlueprintVersionStatus",
    "DossierBlueprint",
    "DossierBlueprintSection",
    "DossierBlueprintVersion",
]
