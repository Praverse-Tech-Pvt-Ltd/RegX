"""Checklist gap analysis.

Rebuilt rather than ported. The legacy iPharmaAI implementation
(`RATools/gap_analysis.py`) computed a score for two hardcoded checklist
families, ANDA and DMF, by reading their bespoke answer tables. It could not see
the other four families because each had its own table shape.

REGX has one checklist engine, so this reads `ChecklistResponse` and works for
any definition. Nothing here is hardcoded to a dosage form or a roadmap.

**No model, no migration.** The legacy version stored each run as an immutable
report row, which meant a score could be read long after the answers behind it
had moved on. This computes on demand from the current responses, so what you
read is what the checklist currently says. Persisting a point-in-time score is a
governance decision -- it needs a reason to exist, an approval trail and a
supersede rule -- and belongs with the review-gate work rather than here.

Definitions, chosen to match the legacy semantics where REGX has an equivalent:

* **gap** - a question answered "no". A "no" is a substantive finding, not a
  missing answer.
* **answered** - a response exists and is neither blank nor marked not
  applicable.
* **not applicable** - excluded from both numerator and denominator. It is
  neither a pass nor a failure.
* **unanswered** - excluded from the score and reported separately, so an
  untouched checklist does not score 100%.

Only `yes_no` and `yes_no_na` questions can produce a gap; everything else is
counted for completeness only.
"""

from .enums import AnswerType
from .models import ChecklistExecution, ChecklistQuestion, ChecklistResponse

#: Question types where "no" is a meaningful finding.
GAPPABLE_ANSWER_TYPES = {AnswerType.YES_NO, AnswerType.YES_NO_NOT_APPLICABLE}


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


def analyse_execution(execution: ChecklistExecution) -> dict:
    """Score one checklist execution.

    Returns a dict rather than a serialiser so the calculation is testable
    without an HTTP layer.
    """
    responses = {
        response.question_id: response
        for response in ChecklistResponse.objects.filter(
            execution=execution
        ).select_related("question", "question__section")
    }
    questions = (
        ChecklistQuestion.objects.filter(section__checklist_version=execution.checklist_version)
        .select_related("section")
        .order_by("section__display_order", "display_order")
    )

    gaps = []
    sections = {}
    answered = not_applicable = unanswered = gap_count = 0

    for question in questions:
        section_name = question.section.title
        bucket = sections.setdefault(
            section_name,
            {"section": section_name, "answered": 0, "gaps": 0, "unanswered": 0,
             "not_applicable": 0, "score_percent": None},
        )

        response = responses.get(question.id)
        if response is None:
            unanswered += 1
            bucket["unanswered"] += 1
            continue
        if response.is_not_applicable:
            not_applicable += 1
            bucket["not_applicable"] += 1
            continue

        value = _normalised(response.raw_value)
        if value is None:
            unanswered += 1
            bucket["unanswered"] += 1
            continue

        answered += 1
        bucket["answered"] += 1

        if question.answer_type in GAPPABLE_ANSWER_TYPES and value == "no":
            gap_count += 1
            bucket["gaps"] += 1
            gaps.append(
                {
                    "question_id": str(question.public_id),
                    "code": question.code,
                    "section": section_name,
                    "question_text": question.question_text,
                    "answer": value,
                }
            )

    for bucket in sections.values():
        bucket["score_percent"] = _score(bucket["answered"], bucket["gaps"])

    total_questions = len(questions)
    return {
        "execution_id": str(execution.public_id),
        "total_questions": total_questions,
        "answered": answered,
        "unanswered": unanswered,
        "not_applicable": not_applicable,
        "gap_count": gap_count,
        "score_percent": _score(answered, gap_count),
        "completeness_percent": _percent(answered + not_applicable, total_questions),
        "sections": sorted(sections.values(), key=lambda s: s["section"]),
        "gaps": gaps,
    }


def _score(answered, gaps):
    """Percentage of answered questions that are not gaps.

    Returns None rather than 100 when nothing is answered: an untouched
    checklist has no score, and reporting 100% would read as complete.
    """
    if answered <= 0:
        return None
    return round((answered - gaps) / answered * 100, 2)


def _percent(part, whole):
    if whole <= 0:
        return None
    return round(part / whole * 100, 2)
