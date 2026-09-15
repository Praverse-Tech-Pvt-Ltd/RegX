"""P7 -- generating and reading immutable gap-analysis snapshots.

The rule itself is not here. `gap_analysis.classify()` is the single engine, and
this module is one of its two callers: it persists exactly what the on-demand
endpoint projects, so the two surfaces cannot drift into disagreeing about the
same execution.

WHAT THE HASH IS FOR
--------------------
`input_hash` is a SHA-256 over a canonical description of everything the
classification depended on. It does three jobs:

1. **Provenance.** A snapshot can prove which state produced it, years later,
   without trusting a timestamp.
2. **Idempotency.** Generating twice from unchanged inputs returns the existing
   snapshot instead of creating a second identical one.
3. **Staleness.** Hashing the execution now and comparing tells a reader whether
   the latest snapshot still reflects the current answers, without recomputing
   a diff.

**No answer content goes into the payload that is hashed.** Each response
contributes a `answer_digest` -- itself a SHA-256 of the canonical raw value --
rather than the value, so a free-text answer containing personal data never
enters the structure even in memory. The digest still changes whenever the
answer does, which is all the hash needs.

The canonicaliser is `controlled_export.canonical_bytes`, the one the governed
export artifact already uses. A second canonicalisation would be a second
definition of "the same inputs", and the two would eventually disagree.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from .audit import IigChecklistEvent, emit
from .controlled_export import canonical_bytes, checksum_for
from .gap_analysis import GapStatus, analyse
from .models import GapAnalysis, GapAnalysisItem


def _answer_digest(raw_value) -> str:
    """A fingerprint of one answer, never the answer.

    `None` is given its own constant rather than being hashed, so "unanswered"
    is distinguishable from "answered with the JSON literal null" at a glance in
    a debugging session.
    """
    if raw_value is None:
        return "absent"
    return checksum_for({"v": raw_value})


def canonical_inputs(execution, states, result) -> dict:
    """The exact structure `input_hash` is taken over.

    Deliberately explicit rather than serialising objects: every field here is
    one somebody chose, so a column added to `ChecklistResponse` later cannot
    silently change the identity of every existing snapshot.
    """
    return {
        "algorithm_version": result.algorithm_version,
        "execution_public_id": str(execution.public_id),
        "checklist_version_public_id": str(execution.checklist_version.public_id),
        "checklist_version_number": execution.checklist_version.version_number,
        "formulation_version_public_id": (
            str(execution.formulation_version.public_id)
            if execution.formulation_version_id
            else None
        ),
        "subject_component_public_id": (
            str(execution.subject_component.public_id) if execution.subject_component_id else None
        ),
        # Sorted by the question's stable public id, so the hash does not depend
        # on the ordering the collector happened to use.
        "questions": sorted(
            (
                {
                    "question_public_id": state.question_public_id,
                    "question_code": state.question_code,
                    "answer_type": state.answer_type,
                    "criticality": state.criticality,
                    "section_code": state.section_code,
                    "section_display_order": state.section_display_order,
                    "display_order": state.display_order,
                    # The governed applicability outcome, not the free-text
                    # reason behind it.
                    "applicability_outcome": str(state.applicability_outcome),
                    "is_not_applicable": state.is_not_applicable,
                    "answer_digest": _answer_digest(state.raw_value),
                    "status": item.status,
                    "reason_code": item.reason_code,
                }
                for state, item in zip(states, result.items, strict=True)
            ),
            key=lambda entry: entry["question_public_id"],
        ),
    }


def input_hash(execution, states, result) -> str:
    """SHA-256 over the canonical inputs, as lowercase hex."""
    import hashlib

    return hashlib.sha256(canonical_bytes(canonical_inputs(execution, states, result))).hexdigest()


def current_input_hash(execution) -> str:
    """The hash the execution would produce if analysed right now.

    Used to tell a reader whether the latest snapshot is still current without
    writing anything.
    """
    states, result = analyse(execution)
    return input_hash(execution, states, result)


@transaction.atomic
def generate(*, execution, tenant, actor):
    """Snapshot this execution, or return the snapshot that already says this.

    Returns `(analysis, created)`. When `created` is False nothing was written
    and nothing is audited: re-asking a question that has already been answered
    is not an event.
    """
    states, result = analyse(execution)
    digest = input_hash(execution, states, result)

    existing = GapAnalysis.objects.filter(
        tenant=tenant,
        execution=execution,
        input_hash=digest,
        algorithm_version=result.algorithm_version,
    ).first()
    if existing is not None:
        return existing, False

    counts = result.counts
    try:
        with transaction.atomic():
            analysis = GapAnalysis.objects.create(
                tenant=tenant,
                execution=execution,
                checklist_version=execution.checklist_version,
                input_hash=digest,
                algorithm_version=result.algorithm_version,
                generated_by=actor if actor is not None and actor.is_authenticated else None,
                generated_at=timezone.now(),
                total_questions=counts["total_questions"],
                applicable_count=counts["applicable"],
                gap_count=counts[GapStatus.GAP],
                no_gap_count=counts[GapStatus.NO_GAP],
                unanswered_count=counts[GapStatus.UNANSWERED],
                review_required_count=counts[GapStatus.REVIEW_REQUIRED],
                not_applicable_count=counts[GapStatus.NOT_APPLICABLE],
            )
    except IntegrityError:
        # Lost the race against a concurrent generation with identical inputs.
        # The unique constraint is the arbiter; the loser reads the winner's row
        # rather than retrying, because both would have written the same thing.
        existing = GapAnalysis.objects.get(
            tenant=tenant,
            execution=execution,
            input_hash=digest,
            algorithm_version=result.algorithm_version,
        )
        return existing, False

    by_public_id = {state.question_public_id: state for state in states}
    GapAnalysisItem.objects.bulk_create(
        [
            GapAnalysisItem(
                analysis=analysis,
                question_id=by_public_id[item.question_public_id].question_pk,
                section_code=item.section_code,
                section_display_order=item.section_display_order,
                display_order=item.display_order,
                status=item.status,
                reason_code=item.reason_code,
                configured_criticality=item.criticality,
            )
            for item in result.items
        ]
    )

    # Centralized audit, payload built explicitly at the call site. Ids,
    # counts, a hash and an algorithm version -- no question text, no answer,
    # no narrative. Nothing is emitted when generation fails, because the
    # write and this emit share one transaction.
    emit(
        event_type=IigChecklistEvent.GAP_ANALYSIS_GENERATED,
        resource_id=str(analysis.public_id),
        actor_id=analysis.generated_by_id,
        actor_email=(actor.email if actor is not None and actor.is_authenticated else ""),
        tenant_id=tenant.pk,
        payload={
            "analysis_public_id": str(analysis.public_id),
            "execution_public_id": str(execution.public_id),
            "checklist_version_public_id": str(execution.checklist_version.public_id),
            "input_hash": digest,
            "algorithm_version": analysis.algorithm_version,
            "total_questions": analysis.total_questions,
            "applicable": analysis.applicable_count,
            "gap": analysis.gap_count,
            "no_gap": analysis.no_gap_count,
            "unanswered": analysis.unanswered_count,
            "review_required": analysis.review_required_count,
            "not_applicable": analysis.not_applicable_count,
        },
    )
    return analysis, True


def analyses_for(execution, tenant):
    """Every snapshot of one execution, newest first."""
    return GapAnalysis.objects.filter(tenant=tenant, execution=execution)


def latest_for(execution, tenant):
    return analyses_for(execution, tenant).first()
