"""
Deterministic duplicate-candidate generation. Every match here is either an
exact match on a specific field (checksum, code, identifier, normalized
text) or, for fuzzy similarity, a review-only candidate. Nothing in this
module ever merges, deletes, or overwrites a record -- it only creates
TemplateDuplicateCandidate rows for a human reviewer to resolve.
"""

from django.db.models import Q

from .models import DuplicateMatchType, TemplateDuplicateCandidate, TemplateItem


def find_duplicate_candidates_for_item(
    subject_item: TemplateItem, *, exclude_pk: int | None = None
) -> list[TemplateDuplicateCandidate]:
    """Scan existing TemplateItem rows in the same tenant scope for
    deterministic matches against `subject_item`, and persist any found as
    pending TemplateDuplicateCandidate rows (idempotent -- reruns do not
    create duplicate candidate rows for the same pair+match_type)."""
    tenant = subject_item.template_section.template_version.template.tenant
    candidates_qs = TemplateItem.objects.for_tenant_including_platform(tenant)
    candidates_qs = candidates_qs.exclude(pk=subject_item.pk)
    if exclude_pk:
        candidates_qs = candidates_qs.exclude(pk=exclude_pk)

    created: list[TemplateDuplicateCandidate] = []

    match_queries = [
        (
            DuplicateMatchType.CANONICAL_CODE,
            Q(canonical_item_code=subject_item.canonical_item_code),
        ),
        (
            DuplicateMatchType.LEGACY_IDENTIFIER,
            Q(legacy_identifier=subject_item.legacy_identifier)
            if subject_item.legacy_identifier
            else None,
        ),
        (
            DuplicateMatchType.NORMALIZED_TEXT,
            Q(normalized_text=subject_item.normalized_text)
            if subject_item.normalized_text
            else None,
        ),
    ]

    for match_type, query in match_queries:
        if query is None:
            continue
        for match in candidates_qs.filter(query):
            candidate, was_created = TemplateDuplicateCandidate.objects.get_or_create(
                subject_template_item=subject_item,
                suspected_match_item=match,
                match_type=match_type,
                defaults={
                    "similarity_evidence": {
                        "subject_id": str(subject_item.public_id),
                        "match_id": str(match.public_id),
                        "field": match_type,
                    }
                },
            )
            if was_created:
                created.append(candidate)

    return created
