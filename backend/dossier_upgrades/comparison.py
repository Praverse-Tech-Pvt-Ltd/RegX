"""Comparing a dossier against a newer blueprint version.

**Read-only.** Nothing in this module writes anything. It produces a list of
proposed changes; `services.generate_plan` persists them and `services.apply`
acts on the accepted ones.

---

HOW SECTIONS ARE MATCHED

M10's `_clone_sections` copies a version's structure into fresh rows and records
no pointer back, so there is no stored v1 -> v2 lineage. Matching is derived, but
each hop is backed by a constraint or a stored row rather than a heuristic:

    dossier section --[BlueprintSectionOrigin, a stored row]--> source section
    source section  --[section_code, unique per version]------> target section

`unique_active_blueprint_section_code` makes a code identify at most one active
section per version, so the second hop is exact.

WHERE IT REFUSES TO GUESS

A dossier section with **no origin row** was added by hand after instantiation.
It is not blueprint-controlled and the comparison has no basis for claiming it
corresponds to anything.

  * If its code matches nothing in the target, it is simply left alone -- no
    item at all. Manual work is not the blueprint's business.
  * If its code **collides** with a target section, the comparison cannot tell
    whether the user pre-empted the blueprint or picked the same code by
    coincidence. Adding the target section would violate
    `unique_active_section_code_per_dossier`; updating the manual one would
    silently adopt work the user owns. Both guesses could be wrong, so it emits
    `CONFLICT` and requires manual review.

A section renamed between versions (code changed) is reported as a retirement
plus an addition, not a rename. That is two truthful statements rather than one
inferred one, and the retirement carries the usual runtime-work protection.

RUNTIME WORK IS NEVER TOUCHED

`status`, `readiness`, blockers, links, `owner`, `notes` and a manually-set
`due_date` are not blueprint-controlled and never appear as a change. A
retirement whose section carries any of them is emitted `BLOCKED` -- see
`_retirement_blocker`.
"""

from .models import ChangeType, ItemStatus

#: Coarse enumerated reasons. Never prose describing the submission.
BLOCK_HAS_CHILDREN = "has_active_children"
BLOCK_HAS_BLOCKERS = "has_open_blockers"
BLOCK_HAS_LINKS = "has_resource_links"
BLOCK_HAS_PROGRESS = "has_recorded_progress"
BLOCK_AMBIGUOUS_CODE = "ambiguous_section_code"
BLOCK_PARENT_UNAVAILABLE = "target_parent_unavailable"
BLOCK_DUPLICATE_CODE = "duplicate_section_code"


class ProposedChange:
    """One proposed change, before it becomes a persisted plan item."""

    __slots__ = (
        "after_value",
        "before_value",
        "blocking_reason",
        "change_type",
        "dossier_section",
        "field_name",
        "requires_manual_review",
        "section_code",
        "source_section",
        "status",
        "target_section",
    )

    def __init__(
        self,
        change_type,
        *,
        status=ItemStatus.PROPOSED,
        dossier_section=None,
        source_section=None,
        target_section=None,
        section_code="",
        field_name="",
        before_value="",
        after_value="",
        blocking_reason="",
        requires_manual_review=False,
    ):
        self.change_type = change_type
        self.status = status
        self.dossier_section = dossier_section
        self.source_section = source_section
        self.target_section = target_section
        self.section_code = section_code
        self.field_name = field_name
        self.before_value = before_value
        self.after_value = after_value
        self.blocking_reason = blocking_reason
        self.requires_manual_review = requires_manual_review


def _short(value, limit=255) -> str:
    """Render a value for a reviewer, not for a machine.

    Truncated because these land in a `CharField` a human reads in a diff table;
    a full description belongs on the section, not in the change list.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _retirement_blocker(section, runtime) -> str:
    """Why this section must not be retired automatically, if it must not.

    A blueprint dropping a section is a statement about the template. It is not
    a statement that the work someone has done under that section is worthless,
    and this is the difference between a useful upgrade and a destructive one.
    """
    if runtime["children"].get(section.pk):
        return BLOCK_HAS_CHILDREN
    if runtime["blockers"].get(section.pk):
        return BLOCK_HAS_BLOCKERS
    if runtime["links"].get(section.pk):
        return BLOCK_HAS_LINKS
    if runtime["progressed"].get(section.pk):
        return BLOCK_HAS_PROGRESS
    return ""


def compare(*, dossier_sections, source_sections, target_sections, origins, runtime):
    """Return an ordered list of `ProposedChange`.

    `origins` maps dossier section pk -> source blueprint section pk, from the
    stored `BlueprintSectionOrigin` rows (and any later upgrade origins).
    `runtime` carries the pre-computed per-section facts that decide whether a
    retirement is safe -- passed in rather than queried here so this stays free
    of database access and the caller can batch.
    """
    source_by_pk = {s.pk: s for s in source_sections}
    target_by_code = {s.section_code: s for s in target_sections}
    dossier_by_pk = {s.pk: s for s in dossier_sections}

    # Dossier sections that came from the blueprint, keyed by the target section
    # they correspond to. Built through the origin row, never by guessing.
    matched_target_pks = set()
    changes = []

    for section in dossier_sections:
        source_pk = origins.get(section.pk)

        if source_pk is None:
            # Added by hand. Not blueprint-controlled.
            collision = target_by_code.get(section.section_code)
            if collision is not None:
                changes.append(
                    ProposedChange(
                        ChangeType.CONFLICT,
                        status=ItemStatus.BLOCKED,
                        dossier_section=section,
                        target_section=collision,
                        section_code=section.section_code,
                        blocking_reason=BLOCK_AMBIGUOUS_CODE,
                        requires_manual_review=True,
                    )
                )
                matched_target_pks.add(collision.pk)
            # Otherwise: left entirely alone, deliberately, with no item.
            continue

        source = source_by_pk.get(source_pk)
        if source is None:
            # The origin points at a section retired from the source version
            # after the dossier was built. Nothing to compare against.
            continue

        target = target_by_code.get(source.section_code)
        if target is None:
            reason = _retirement_blocker(section, runtime)
            changes.append(
                ProposedChange(
                    ChangeType.RETIRE_SECTION,
                    status=ItemStatus.BLOCKED if reason else ItemStatus.PROPOSED,
                    dossier_section=section,
                    source_section=source,
                    section_code=section.section_code,
                    blocking_reason=reason,
                    requires_manual_review=bool(reason),
                )
            )
            continue

        matched_target_pks.add(target.pk)
        changes.extend(
            _metadata_changes(
                section=section,
                source=source,
                target=target,
                dossier_by_pk=dossier_by_pk,
                origins=origins,
                source_by_pk=source_by_pk,
                target_by_code=target_by_code,
                runtime=runtime,
            )
        )

    # Anything in the target nothing matched is an addition. Ordered by depth so
    # a parent is proposed before its children -- apply relies on it.
    existing_codes = {s.section_code for s in dossier_sections}
    for target in _by_depth(target_sections):
        if target.pk in matched_target_pks:
            continue
        if target.section_code in existing_codes:
            # A manual section already holds this code; the CONFLICT above
            # already covers it, and adding would violate the dossier's unique
            # active code constraint.
            continue
        changes.append(
            ProposedChange(
                ChangeType.ADD_SECTION,
                dossier_section=None,
                target_section=target,
                section_code=target.section_code,
                after_value=_short(target.title),
            )
        )

    if not changes:
        changes.append(ProposedChange(ChangeType.NO_CHANGE, status=ItemStatus.PROPOSED))
    return changes


def _by_depth(sections):
    """Target sections, shallowest first, siblings in sequence order."""
    by_pk = {s.pk: s for s in sections}

    def depth(section):
        d, walker, guard = 0, section, 0
        while walker is not None and walker.parent_id and guard < 32:
            walker = by_pk.get(walker.parent_id)
            d += 1
            guard += 1
        return d

    return sorted(sections, key=lambda s: (depth(s), s.sequence, s.pk))


def _metadata_changes(
    *,
    section,
    source,
    target,
    dossier_by_pk,
    origins,
    source_by_pk,
    target_by_code,
    runtime,
):
    """Field-level changes for one matched section.

    One item per field, so a reviewer accepts a title change without also
    accepting a reparent they did not want. Bundling them would make "accept"
    mean something different per row.
    """
    out = []

    if target.title != section.title:
        out.append(
            ProposedChange(
                ChangeType.UPDATE_TITLE,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="title",
                before_value=_short(section.title),
                after_value=_short(target.title),
            )
        )

    if target.description != section.description:
        out.append(
            ProposedChange(
                ChangeType.UPDATE_DESCRIPTION,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="description",
                before_value=_short(section.description),
                after_value=_short(target.description),
            )
        )

    if bool(target.required) != bool(section.required):
        out.append(
            ProposedChange(
                ChangeType.UPDATE_REQUIRED,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="required",
                before_value=_short(section.required),
                after_value=_short(target.required),
            )
        )

    # Parent: compare by the code of the parent on each side, because the two
    # sides are different tables. A missing counterpart in the dossier means the
    # move has nowhere to land yet.
    target_parent_code = _parent_code(target, target_by_code)
    current_parent_code = section.parent.section_code if section.parent_id else None
    if target_parent_code != current_parent_code:
        landing = _dossier_section_for_code(target_parent_code, dossier_by_pk)
        blocked = target_parent_code is not None and landing is None
        out.append(
            ProposedChange(
                ChangeType.MOVE_SECTION,
                status=ItemStatus.BLOCKED if blocked else ItemStatus.PROPOSED,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="parent",
                before_value=_short(current_parent_code or "(top level)"),
                after_value=_short(target_parent_code or "(top level)"),
                blocking_reason=BLOCK_PARENT_UNAVAILABLE if blocked else "",
                requires_manual_review=blocked,
            )
        )
    elif target.sequence != section.sequence:
        # Only meaningful when the parent is unchanged; a move renumbers anyway.
        out.append(
            ProposedChange(
                ChangeType.REORDER_SECTION,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="sequence",
                before_value=_short(section.sequence),
                after_value=_short(target.sequence),
            )
        )

    # Due offset drives a DEFAULT due date. It is proposed only where the
    # dossier has not recorded a due date of its own -- see `services` for the
    # apply-side rule, which re-checks rather than trusting this.
    if target.default_due_offset_days is not None and section.due_date is None:
        out.append(
            ProposedChange(
                ChangeType.UPDATE_DUE_OFFSET,
                dossier_section=section,
                source_section=source,
                target_section=target,
                section_code=section.section_code,
                field_name="due_date",
                before_value="(none)",
                after_value=f"target date - {target.default_due_offset_days}d",
            )
        )

    return out


def _parent_code(target_section, target_by_code):
    if not target_section.parent_id:
        return None
    for code, candidate in target_by_code.items():
        if candidate.pk == target_section.parent_id:
            return code
    return None


def _dossier_section_for_code(code, dossier_by_pk):
    if code is None:
        return None
    for section in dossier_by_pk.values():
        if section.section_code == code:
            return section
    return None
