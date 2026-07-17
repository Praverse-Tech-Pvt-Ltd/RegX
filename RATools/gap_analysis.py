"""
ANDA / DMF automated checklist gap analysis.

A "gap" is a checklist question answered "no" in the yes/no/not_applicable
data already captured by the existing ANDA and DMF checklist flows
(ANDAUserAnswers, DMFCAAnswer). Unanswered questions are excluded from both
the gap count and the answered count -- they're neither a pass nor a fail,
just incomplete.

DMF's DMFReviewAnswer (drf/ra/ard booleans) is deliberately not analyzed
here -- see RegulatoryGapAnalysisReport's docstring for why.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.contrib.contenttypes.models import ContentType
from django.db.models import Max
from django.utils.html import strip_tags

from . import audit
from .models import (
    ANDAReportQuestions,
    ANDAUserAnswers,
    DMFCAAnswer,
    RegulatoryGapAnalysisReport,
    RegulatoryReviewGate,
)


def generate_anda_gap_analysis(anda_user_report, generated_by=None):
    report_type_name = anda_user_report.report_name.report_name
    questions = ANDAReportQuestions.objects.filter(report_name=report_type_name)
    answers_by_question_id = {
        a.report_question_id: a
        for a in ANDAUserAnswers.objects.filter(
            report_name=anda_user_report
        ).select_related("report_question")
    }

    gap_details = []
    answered_count = 0
    gap_count = 0
    for question in questions:
        answer_obj = answers_by_question_id.get(question.id)
        if answer_obj is None or not answer_obj.answer:
            continue
        answered_count += 1
        if answer_obj.answer == "no":
            gap_count += 1
            gap_details.append(
                {
                    "question_id": question.id,
                    "module": question.module_name,
                    "chapter": question.chapter_name,
                    "category": question.category_name,
                    "question": strip_tags(question.question or ""),
                    "answer": answer_obj.answer,
                }
            )

    report = _create_report(
        source_type="anda",
        target=anda_user_report,
        total_questions=questions.count(),
        answered_count=answered_count,
        gap_count=gap_count,
        gap_details=gap_details,
        generated_by=generated_by,
    )

    audit.log_event(
        user=generated_by,
        action_type="gap_analysis_generated",
        target=anda_user_report,
        new_value={
            "gap_count": gap_count,
            "score_percent": str(report.score_percent),
            "version": report.version,
        },
        reason=f"ANDA gap analysis generated for {anda_user_report.product_name}",
    )
    _ensure_review_gate(anda_user_report, doer=anda_user_report.user)
    return report


def generate_dmf_gap_analysis(dmf_checklist_user, generated_by=None):
    answers = DMFCAAnswer.objects.filter(checklist=dmf_checklist_user).select_related("dmf_ca")

    gap_details = []
    answered_count = 0
    gap_count = 0
    for a in answers:
        if not a.answer:
            continue
        answered_count += 1
        if a.answer == "no":
            gap_count += 1
            category = a.dmf_ca.category or ""
            if a.dmf_ca.ectd_no:
                category = f"{category} ({a.dmf_ca.ectd_no})" if category else a.dmf_ca.ectd_no
            gap_details.append(
                {
                    # Same key shape as the ANDA gap dict (question_id, module,
                    # chapter, category, question, answer) so both source
                    # types render through one template without missing-key
                    # lookups. DMF's sub_category is the closest analog to
                    # ANDA's chapter; ectd_no is folded into category instead
                    # of adding a DMF-only key.
                    "question_id": a.dmf_ca_id,
                    "module": a.dmf_ca.module,
                    "chapter": a.dmf_ca.sub_category,
                    "category": category,
                    "question": strip_tags(a.dmf_ca.question or ""),
                    "answer": a.answer,
                }
            )

    report = _create_report(
        source_type="dmf",
        target=dmf_checklist_user,
        total_questions=answers.count(),
        answered_count=answered_count,
        gap_count=gap_count,
        gap_details=gap_details,
        generated_by=generated_by,
    )

    audit.log_event(
        user=generated_by,
        action_type="gap_analysis_generated",
        target=dmf_checklist_user,
        new_value={
            "gap_count": gap_count,
            "score_percent": str(report.score_percent),
            "version": report.version,
        },
        reason=f"DMF gap analysis generated for {dmf_checklist_user.name_of_api}",
    )
    _ensure_review_gate(dmf_checklist_user, doer=dmf_checklist_user.user)
    return report


def _create_report(*, source_type, target, total_questions, answered_count, gap_count, gap_details, generated_by):
    content_type = ContentType.objects.get_for_model(target)
    previous_max_version = RegulatoryGapAnalysisReport.objects.filter(
        content_type=content_type, object_id=target.pk
    ).aggregate(Max("version"))["version__max"]
    next_version = (previous_max_version or 0) + 1

    return RegulatoryGapAnalysisReport.objects.create(
        source_type=source_type,
        content_type=content_type,
        object_id=target.pk,
        total_questions=total_questions,
        answered_count=answered_count,
        gap_count=gap_count,
        score_percent=_score(answered_count, gap_count),
        gap_details=gap_details,
        generated_by=generated_by,
        version=next_version,
    )


def _score(answered_count, gap_count):
    if answered_count == 0:
        return Decimal("0.00")
    compliant = answered_count - gap_count
    percent = (Decimal(compliant) / Decimal(answered_count)) * Decimal(100)
    return percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ensure_review_gate(target, doer):
    """Open a review gate for this checklist submission if one doesn't already exist."""
    content_type = ContentType.objects.get_for_model(target)
    RegulatoryReviewGate.objects.get_or_create(
        content_type=content_type,
        object_id=target.pk,
        defaults={"doer": doer, "status": "pending_review"},
    )
