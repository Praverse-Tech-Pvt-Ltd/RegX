"""A canonical fingerprint of a dossier's structure, for plan staleness.

A plan is a proposal about a dossier as it stood when the plan was generated. If
someone adds, retires, renames, moves or reorders a section afterwards, the plan
is describing a dossier that no longer exists -- and applying it would write
changes computed against stale facts. "Add a child under section B" is a
different act if B has since been retired.

So a plan carries a hash of the structure it was computed from, and `apply`
recomputes it. A mismatch refuses the apply and asks for a regenerate. It fails
**closed**: a plan that cannot prove the dossier is unchanged is not applied.

WHAT IS IN THE HASH, AND WHY

Only what the comparison actually reads:

    public_id · parent public_id · section_code · title · description
    · required · sequence

`public_id` rather than the internal PK, so the value is stable and safe to
expose. Retired sections are excluded, because the comparison only ever looks at
active structure -- and including them would make an unrelated retirement
invalidate every open plan.

WHAT IS DELIBERATELY NOT IN IT

Runtime state: `status`, `readiness`, `readiness_reason`, `owner`, `notes`,
`due_date`, blockers and resource links. None of it is blueprint-controlled, none
of it is read by the comparison, and including it would make a plan go stale
because somebody ticked a checkbox or linked a document. That would train users
to regenerate reflexively, which is exactly how a staleness guard stops being
read.

`updated_at` is excluded for the same reason: it moves when runtime fields move.
"""

import hashlib
import json

#: Bumped if the hashed field set ever changes, so old fingerprints compare
#: unequal instead of colliding with a differently-computed value.
FINGERPRINT_VERSION = 1


def structural_fingerprint(sections) -> str:
    """Order-independent SHA-256 over the active structure.

    `sections` is any iterable of `DossierSection`. Rows are sorted by
    `public_id` before hashing so the value does not depend on query order --
    two callers reading the same dossier through different querysets must get
    the same fingerprint.
    """
    rows = []
    for section in sections:
        if section.retired_at is not None:
            continue
        rows.append(
            [
                str(section.public_id),
                str(section.parent.public_id) if section.parent_id else None,
                section.section_code,
                section.title,
                section.description,
                bool(section.required),
                int(section.sequence),
            ]
        )
    rows.sort(key=lambda row: row[0])

    payload = json.dumps(
        {"v": FINGERPRINT_VERSION, "rows": rows},
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_for_dossier(dossier) -> str:
    """Load the dossier's active sections and fingerprint them.

    `select_related("parent")` matters: the hash reads `parent.public_id`, so
    without it this is one query per section.
    """
    from submission_dossiers.models import DossierSection

    sections = (
        DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
        .select_related("parent")
        .order_by("id")
    )
    return structural_fingerprint(sections)
