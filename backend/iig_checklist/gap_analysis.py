"""Checklist gap analysis -- one engine, two surfaces.

Rebuilt rather than ported. The legacy iPharmaAI implementation
(`RATools/gap_analysis.py`) computed a score for two hardcoded checklist
families, ANDA and DMF, by reading their bespoke answer tables. It could not see
the other four families because each had its own table shape.

REGX has one checklist engine, so this reads `ChecklistResponse` and works for
any definition. Nothing here is hardcoded to a dosage form or a roadmap.

ONE CLASSIFICATION, TWO CALLERS
-------------------------------
`classify()` is the whole of the rule. It is pure: it takes the collected state
of an execution and returns a `GapAnalysisResult`, touching no database and no
clock. Everything else in this module is a caller of it:

* `analyse_execution()` -- the long-standing on-demand GET, now an adapter that
  projects the same result into the response shape that endpoint has always
  returned;
* `iig_checklist.gap_snapshots` -- persists that same result as an immutable
  snapshot.

That split is the point. Before P7 the GET *was* the rule, so any correction had
to be made in one place and would have been absent from the other. Two surfaces
disagreeing about the same execution is worse than either being wrong on its
own, because nothing tells the reader which one to believe.

WHAT IS NOT DECIDED HERE
------------------------
No score. `score_percent` and `completeness_percent` survive in the legacy
projection for API compatibility only -- see `legacy_projection()`. They are not
persisted, not shown in the P7 UI and not used by any governance decision. The
formula behind them was never approved, and replacing it needs an approved
specification rather than a better guess.

No severity either. `criticality` is carried through exactly as the checklist
definition configured it, or reported as unconfigured. Nothing here ranks,
weights or derives it.

STATUSES
--------
Five, and they are operational rather than regulatory. `gap` means the checklist
recorded a "no"; it does not mean non-compliant, and nothing here concludes
anything about a submission.
"""

from __future__ import annotations

from dataclasses import dataclass

from .applicability_runtime import derive_applicability_outcome
from .enums import AnswerType, ApplicabilityOutcome
from .models import ChecklistQuestion, ChecklistResponse

#: Bump when the classification rules change meaning. Persisted on every
#: snapshot and mixed into the input hash, so a snapshot taken under an older
#: rule set can never be mistaken for one taken under this one, and regenerating
#: after a rule change produces a new snapshot rather than a false cache hit.
ALGORITHM_VERSION = 1

#: Question types where "no" is a meaningful finding.
GAPPABLE_ANSWER_TYPES = frozenset({AnswerType.YES_NO, AnswerType.YES_NO_NOT_APPLICABLE})


class GapStatus:
    """Operational outcomes. Deliberately not `compliant`/`non_compliant`."""

    GAP = "gap"
    NO_GAP = "no_gap"
    UNANSWERED = "unanswered"
    REVIEW_REQUIRED = "review_required"
    NOT_APPLICABLE = "not_applicable"


class ReasonCode:
    """Why a question landed in its status. One code per rule that exists.

    No code is invented for a rule the engine does not actually apply.
    """

    #: Answered "no" on a type where "no" is a finding.
    ANSWER_NO = "ANSWER_NO"
    #: Answered "yes" on such a type.
    ANSWER_YES = "ANSWER_YES"
    #: Answered, but on a type that cannot produce a finding at all. Recorded
    #: rather than folded into ANSWER_YES because "this question passed" and
    #: "this question can never fail" are different facts, and the second one is
    #: what a reader needs in order to know the checklist is not covering it.
    NOT_GAPPABLE_TYPE = "NOT_GAPPABLE_TYPE"
    #: No value recorded.
    ANSWER_MISSING = "ANSWER_MISSING"
    #: Governed applicability said this question does not apply.
    APPLICABILITY_NOT_APPLICABLE = "APPLICABILITY_NOT_APPLICABLE"
    #: Governed applicability could not decide; a person must.
    APPLICABILITY_REVIEW_REQUIRED = "APPLICABILITY_REVIEW_REQUIRED"


#: The unconfigured marker for `criticality`. The field is non-null with choices,
#: so in practice it is always set -- but a blank must read as "not configured"
#: rather than silently sorting as the lowest severity.
CRITICALITY_NOT_CONFIGURED = ""


def _normalised(raw_value):
    """Reduce a response's JSON value to a comparable token.

    `raw_value` is a JSONField, so a yes/no answer may arrive as a bool, as the
    string "no", or as {"value": "no"} depending on which client wrote it. All
    three mean the same thing and all three occur in practice.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return "yes" if raw_value else "no"
    if isinstance(raw_value, dict):
        return _normalised(raw_value.get("value"))
    text = str(raw_value).strip().lower()
    if text in {"true", "yes", "y"}:
        return "yes"
    if text in {"false", "no", "n"}:
        return "no"
    return text or None


# ---------------------------------------------------------------------------
# Collected state -- the only part that reads the database
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QuestionState:
    """One question and whatever the execution currently says about it.

    `question_text` and `normalised_value` are carried for the legacy
    projection, which has always returned them. They are deliberately *not*
    part of `GapAnalysisResult`, so nothing that snapshots a result can
    accidentally persist question or answer content.
    """

    question_pk: int
    question_public_id: str
    question_code: str
    question_text: str
    answer_type: str
    criticality: str
    display_order: int
    section_code: str
    section_title: str
    section_display_order: int
    applicability_outcome: str
    is_not_applicable: bool
    normalised_value: str | None
    raw_value: object


def collect_state(execution) -> tuple[QuestionState, ...]:
    """Read one execution into the pure engine's input.

    Ordered by the definition's own ordering, not by title: `display_order` is
    the authored sequence and `code` is the stable identity. See
    `_section_summaries()` for why that matters.
    """
    responses = {
        response.question_id: response
        for response in ChecklistResponse.objects.filter(execution=execution).select_related(
            "question"
        )
    }
    questions = (
        ChecklistQuestion.objects.filter(section__checklist_version=execution.checklist_version)
        .select_related("section")
        .order_by("section__display_order", "section__code", "display_order", "code")
    )

    states = []
    for question in questions:
        response = responses.get(question.id)
        if response is None:
            # `create_execution` pre-creates a slot for every question, so this
            # is defensive: a question added to a version after an execution
            # started would otherwise vanish from the analysis entirely.
            outcome = "no_rule"
            is_na = False
            normalised = None
            raw = None
        else:
            outcome = derive_applicability_outcome(response)
            is_na = response.is_not_applicable
            normalised = _normalised(response.raw_value)
            raw = response.raw_value

        states.append(
            QuestionState(
                question_pk=question.id,
                question_public_id=str(question.public_id),
                question_code=question.code,
                question_text=question.question_text,
                answer_type=question.answer_type,
                criticality=question.criticality or CRITICALITY_NOT_CONFIGURED,
                display_order=question.display_order,
                section_code=question.section.code,
                section_title=question.section.title,
                section_display_order=question.section.display_order,
                applicability_outcome=outcome,
                is_not_applicable=is_na,
                normalised_value=normalised,
                raw_value=raw,
            )
        )
    return tuple(states)


# ---------------------------------------------------------------------------
# The rule -- pure
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GapItem:
    """One classified question. Carries no question or answer text."""

    question_public_id: str
    question_code: str
    section_code: str
    section_display_order: int
    display_order: int
    answer_type: str
    criticality: str
    status: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class SectionSummary:
    section_code: str
    section_title: str
    display_order: int
    counts: dict


@dataclass(frozen=True, slots=True)
class GapAnalysisResult:
    algorithm_version: int
    items: tuple[GapItem, ...]
    sections: tuple[SectionSummary, ...]
    counts: dict


def _classify_one(state: QuestionState) -> tuple[str, str]:
    """(status, reason_code) for one question.

    Order matters, and this is the order the governed applicability vocabulary
    already implies:

    1. `not_applicable` wins outright -- a question that does not apply cannot
       simultaneously be a finding or be awaiting a decision.
    2. `review_required` comes next, ahead of any answer. The rule that decides
       whether this question applies could not be evaluated, so calling it a gap
       would assert it applies and failed, and calling it no_gap would assert it
       applies and passed. Both invent a resolution the platform does not have.
       Reporting it as unanswered -- which is what this did before P7 -- was the
       same mistake in a quieter form: it merged "a person must decide whether
       this applies" into "nobody has typed anything yet".
    3. Then the ordinary answered/unanswered split.
    """
    if state.is_not_applicable:
        return GapStatus.NOT_APPLICABLE, ReasonCode.APPLICABILITY_NOT_APPLICABLE
    if state.applicability_outcome == ApplicabilityOutcome.REVIEW_REQUIRED:
        return GapStatus.REVIEW_REQUIRED, ReasonCode.APPLICABILITY_REVIEW_REQUIRED
    if state.normalised_value is None:
        return GapStatus.UNANSWERED, ReasonCode.ANSWER_MISSING
    if state.answer_type not in GAPPABLE_ANSWER_TYPES:
        # Answered, but this type can never produce a finding. Recorded as its
        # own reason so a reader can see the checklist is not testing it, rather
        # than reading it as a pass.
        return GapStatus.NO_GAP, ReasonCode.NOT_GAPPABLE_TYPE
    if state.normalised_value == "no":
        return GapStatus.GAP, ReasonCode.ANSWER_NO
    return GapStatus.NO_GAP, ReasonCode.ANSWER_YES


def _empty_counts() -> dict:
    return {
        GapStatus.GAP: 0,
        GapStatus.NO_GAP: 0,
        GapStatus.UNANSWERED: 0,
        GapStatus.REVIEW_REQUIRED: 0,
        GapStatus.NOT_APPLICABLE: 0,
    }


def _with_totals(counts: dict) -> dict:
    """Add the two derived totals every counts block carries.

    `applicable` is the denominator a reader actually wants: everything the
    checklist is currently asking this execution to answer. Both the whole
    analysis and each section report them, so a section summary is readable on
    its own without the caller re-adding five numbers.
    """
    total = sum(counts[status] for status in _empty_counts())
    return {
        **counts,
        "total_questions": total,
        "applicable": total - counts[GapStatus.NOT_APPLICABLE],
    }


def classify(states: tuple[QuestionState, ...]) -> GapAnalysisResult:
    """The whole rule. No database, no clock, no randomness.

    Deterministic by construction: the same states in the same order always
    produce the same result, which is what makes the input hash meaningful.
    """
    items = []
    counts = _empty_counts()
    buckets: dict[str, dict] = {}

    for state in states:
        status, reason = _classify_one(state)
        counts[status] += 1

        # Keyed on `code`, which is unique per checklist version.
        # `title` is not unique, so grouping on it silently merged two
        # differently-authored sections that happened to share a name.
        bucket = buckets.setdefault(
            state.section_code,
            {
                "section_code": state.section_code,
                "section_title": state.section_title,
                "display_order": state.section_display_order,
                "counts": _empty_counts(),
            },
        )
        bucket["counts"][status] += 1

        items.append(
            GapItem(
                question_public_id=state.question_public_id,
                question_code=state.question_code,
                section_code=state.section_code,
                section_display_order=state.section_display_order,
                display_order=state.display_order,
                answer_type=state.answer_type,
                criticality=state.criticality,
                status=status,
                reason_code=reason,
            )
        )

    counts = _with_totals(counts)

    sections = tuple(
        SectionSummary(
            section_code=bucket["section_code"],
            section_title=bucket["section_title"],
            display_order=bucket["display_order"],
            counts=_with_totals(bucket["counts"]),
        )
        # Authored order, with `code` breaking ties so the sequence is total and
        # stable even if two sections share a display_order.
        for bucket in sorted(
            buckets.values(), key=lambda b: (b["display_order"], b["section_code"])
        )
    )

    return GapAnalysisResult(
        algorithm_version=ALGORITHM_VERSION,
        items=tuple(items),
        sections=sections,
        counts=counts,
    )


def analyse(execution) -> tuple[tuple[QuestionState, ...], GapAnalysisResult]:
    """Collect and classify. The one entry point every caller should use."""
    states = collect_state(execution)
    return states, classify(states)


# ---------------------------------------------------------------------------
# Legacy projection -- the shape `GET .../gap-analysis/` has always returned
# ---------------------------------------------------------------------------
def _score(answered, gaps):
    """Percentage of answered questions that are not gaps.

    **Legacy output. Not governed.** No approved specification defines this
    formula, and it is not internally coherent: a free-text question answered
    "no" counts as answered but can never be a gap, so answering "no" raises the
    number. It is retained unchanged because removing a field from a live
    response is an API break, and it is deliberately *not* carried into the
    snapshot, the UI, or any readiness decision. Replacing it needs an approved
    scoring specification, not a better guess.

    Returns None rather than 100 when nothing is answered: an untouched
    checklist has no score, and reporting 100% would read as complete.
    """
    if answered <= 0:
        return None
    return round((answered - gaps) / answered * 100, 2)


def _percent(part, whole):
    """Legacy output, on the same terms as `_score`."""
    if whole <= 0:
        return None
    return round(part / whole * 100, 2)


def legacy_projection(states, result) -> dict:
    """Project the canonical result into the original response shape.

    Compatibility rules this obeys:

    * every key the endpoint returned before P7 is still present, and
      `score_percent` / `completeness_percent` are computed by the original
      formulas over the original inputs, so neither moves;
    * `review_required` is *added*, at the top level and per section, rather
      than replacing anything;
    * `sections[].section` still carries the title a client may be displaying,
      with `section_code` added beside it as the stable identity.

    The one deliberate change in an existing number is `unanswered`, which no
    longer absorbs review-required questions. That was the defect; leaving it in
    place to protect a count would be preserving the bug rather than the API.
    """
    by_code = {state.question_code: state for state in states}

    gaps = [
        {
            "question_id": item.question_public_id,
            "code": item.question_code,
            "section": _section_title(result, item.section_code),
            "question_text": by_code[item.question_code].question_text,
            "answer": by_code[item.question_code].normalised_value,
        }
        for item in result.items
        if item.status == GapStatus.GAP
    ]

    answered = result.counts[GapStatus.GAP] + result.counts[GapStatus.NO_GAP]
    gap_count = result.counts[GapStatus.GAP]
    not_applicable = result.counts[GapStatus.NOT_APPLICABLE]
    total_questions = result.counts["total_questions"]

    sections = [
        {
            "section": summary.section_title,
            "section_code": summary.section_code,
            "answered": summary.counts[GapStatus.GAP] + summary.counts[GapStatus.NO_GAP],
            "gaps": summary.counts[GapStatus.GAP],
            "unanswered": summary.counts[GapStatus.UNANSWERED],
            "review_required": summary.counts[GapStatus.REVIEW_REQUIRED],
            "not_applicable": summary.counts[GapStatus.NOT_APPLICABLE],
            "score_percent": _score(
                summary.counts[GapStatus.GAP] + summary.counts[GapStatus.NO_GAP],
                summary.counts[GapStatus.GAP],
            ),
        }
        for summary in result.sections
    ]

    return {
        "total_questions": total_questions,
        "answered": answered,
        "unanswered": result.counts[GapStatus.UNANSWERED],
        "review_required": result.counts[GapStatus.REVIEW_REQUIRED],
        "not_applicable": not_applicable,
        "gap_count": gap_count,
        "score_percent": _score(answered, gap_count),
        "completeness_percent": _percent(answered + not_applicable, total_questions),
        "sections": sections,
        "gaps": gaps,
    }


def _section_title(result, section_code) -> str:
    for summary in result.sections:
        if summary.section_code == section_code:
            return summary.section_title
    return ""


def analyse_execution(execution) -> dict:
    """The on-demand read model, unchanged in route and near-unchanged in shape.

    An adapter over `classify()` rather than a second implementation of it.
    """
    states, result = analyse(execution)
    payload = legacy_projection(states, result)
    # Kept first for readers who match on it; it was the first key before P7.
    return {"execution_id": str(execution.public_id), **payload}
