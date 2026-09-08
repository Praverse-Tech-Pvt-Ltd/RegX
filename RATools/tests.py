from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from AdminMaster.models import CustomUser
from RATools import audit, gap_analysis
from RATools.models import (
    ANDAReportQuestions,
    ANDAUserAnswers,
    ANDAUserReports,
    DMFCAAnswer,
    DMFCATableQuestion,
    DMFChecklistUser,
    RegulatoryAuditTrail,
    RegulatoryGapAnalysisReport,
    RegulatoryReviewGate,
    RegulatoryRole,
)


class RegulatoryRoleTests(TestCase):
    """Doer/Reviewer/VP role assignment, scoped to Regulatory Technical Tools."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="doer_user", password="testpass123", role="company_user"
        )

    def test_role_can_be_assigned(self):
        role = RegulatoryRole.objects.create(user=self.user, role="doer")
        self.assertEqual(role.role, "doer")
        self.assertEqual(role.user, self.user)

    def test_same_user_cannot_have_duplicate_role(self):
        RegulatoryRole.objects.create(user=self.user, role="reviewer")
        with self.assertRaises(IntegrityError):
            RegulatoryRole.objects.create(user=self.user, role="reviewer")

    def test_same_user_can_hold_multiple_distinct_roles(self):
        RegulatoryRole.objects.create(user=self.user, role="doer")
        RegulatoryRole.objects.create(user=self.user, role="reviewer")
        self.assertEqual(self.user.regulatory_roles.count(), 2)


class RegulatoryAuditTrailTests(TestCase):
    """21 CFR Part 11-style audit trail: immutability and generic linking."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="auditor", password="testpass123", role="company_user"
        )

    def test_log_event_creates_immutable_entry(self):
        event = audit.log_event(
            user=self.user,
            action_type="data_upload",
            new_value={"file": "iig_checklist.xlsx"},
            reason="initial upload",
        )
        self.assertIsNotNone(event.pk)
        self.assertEqual(event.action_type, "data_upload")
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.new_value, {"file": "iig_checklist.xlsx"})
        self.assertIsNotNone(event.created_at)

    def test_role_at_time_is_captured_from_user(self):
        self.user.role = "company_checker"
        self.user.save()
        event = audit.log_event(user=self.user, action_type="review_action")
        self.assertEqual(event.role_at_time, "company_checker")

    def test_entry_cannot_be_updated(self):
        event = audit.log_event(user=self.user, action_type="export")
        event.reason = "tampered"
        with self.assertRaises(ValueError):
            event.save()

    def test_entry_cannot_be_deleted(self):
        event = audit.log_event(user=self.user, action_type="export")
        with self.assertRaises(ValueError):
            event.delete()
        self.assertTrue(RegulatoryAuditTrail.objects.filter(pk=event.pk).exists())

    def test_log_event_can_attach_to_an_arbitrary_target(self):
        role = RegulatoryRole.objects.create(user=self.user, role="doer")
        event = audit.log_event(
            user=self.user,
            action_type="role_action",
            target=role,
            reason="role granted",
        )
        self.assertEqual(event.target, role)

    def test_log_event_works_with_no_user_for_system_events(self):
        event = audit.log_event(user=None, action_type="data_upload")
        self.assertIsNone(event.user)
        self.assertEqual(event.role_at_time, "")

    def test_entries_are_ordered_most_recent_first(self):
        first = audit.log_event(user=self.user, action_type="export")
        second = audit.log_event(user=self.user, action_type="export")
        entries = list(RegulatoryAuditTrail.objects.all())
        self.assertEqual(entries[0].pk, second.pk)
        self.assertEqual(entries[1].pk, first.pk)


class RegulatoryReviewGateTests(TestCase):
    """Doer -> Reviewer -> VP review gate."""

    def setUp(self):
        self.doer = CustomUser.objects.create_user(
            username="gate_doer", password="testpass123", role="company_user"
        )
        self.reviewer = CustomUser.objects.create_user(
            username="gate_reviewer", password="testpass123", role="company_checker"
        )
        self.target_role = RegulatoryRole.objects.create(user=self.doer, role="doer")

    def test_review_gate_defaults_to_pending_review(self):
        gate = RegulatoryReviewGate.objects.create(
            content_type=self._content_type(),
            object_id=self.target_role.pk,
            doer=self.doer,
        )
        self.assertEqual(gate.status, "pending_review")
        self.assertIsNone(gate.reviewer)
        self.assertIsNone(gate.vp)

    def test_review_gate_can_be_approved_by_reviewer(self):
        gate = RegulatoryReviewGate.objects.create(
            content_type=self._content_type(),
            object_id=self.target_role.pk,
            doer=self.doer,
        )
        gate.reviewer = self.reviewer
        gate.status = "pending_vp"
        gate.reviewer_comment = "looks correct"
        gate.save()

        refreshed = RegulatoryReviewGate.objects.get(pk=gate.pk)
        self.assertEqual(refreshed.status, "pending_vp")
        self.assertEqual(refreshed.reviewer, self.reviewer)
        self.assertEqual(refreshed.reviewer_comment, "looks correct")

    def _content_type(self):
        from django.contrib.contenttypes.models import ContentType

        return ContentType.objects.get_for_model(RegulatoryRole)


class ANDAGapAnalysisTests(TestCase):
    """Automated gap analysis over existing ANDA checklist answer data."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="anda_doer", password="testpass123", role="company_user"
        )
        self.report_type = "Solid Oral Dosage"
        self.q_pass = ANDAReportQuestions.objects.create(
            report_name=self.report_type, module_name="Module 1", chapter_name="1.1",
            category_name="Administrative", question="Is the cover letter present?",
        )
        self.q_fail = ANDAReportQuestions.objects.create(
            report_name=self.report_type, module_name="Module 3", chapter_name="3.2",
            category_name="Quality", question="Is the stability data complete?",
        )
        self.q_unanswered = ANDAReportQuestions.objects.create(
            report_name=self.report_type, module_name="Module 5", chapter_name="5.3",
            category_name="Clinical", question="Is the bioequivalence study attached?",
        )
        self.submission = ANDAUserReports.objects.create(
            user=self.user, report_name=self.q_pass, product_name="TestDrug 10mg",
        )
        ANDAUserAnswers.objects.create(
            user=self.user, report_name=self.submission, report_question=self.q_pass, answer="yes",
        )
        ANDAUserAnswers.objects.create(
            user=self.user, report_name=self.submission, report_question=self.q_fail, answer="no",
        )
        # q_unanswered deliberately has no ANDAUserAnswers row.

    def test_gap_analysis_counts_no_answer_as_a_gap(self):
        report = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        self.assertEqual(report.source_type, "anda")
        self.assertEqual(report.total_questions, 3)
        self.assertEqual(report.answered_count, 2)
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(len(report.gap_details), 1)
        self.assertEqual(report.gap_details[0]["question_id"], self.q_fail.pk)

    def test_score_percent_is_compliant_fraction_of_answered_questions(self):
        report = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        # 1 compliant (yes) out of 2 answered = 50.00%
        self.assertEqual(report.score_percent, Decimal("50.00"))

    def test_unanswered_question_is_not_counted_as_a_gap(self):
        report = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        gap_question_ids = [g["question_id"] for g in report.gap_details]
        self.assertNotIn(self.q_unanswered.pk, gap_question_ids)

    def test_generating_creates_pending_review_gate(self):
        gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        gate = RegulatoryReviewGate.objects.get(
            content_type__model="andauserreports", object_id=self.submission.pk
        )
        self.assertEqual(gate.status, "pending_review")
        self.assertEqual(gate.doer, self.user)

    def test_generating_logs_an_audit_event(self):
        gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        event = RegulatoryAuditTrail.objects.get(action_type="gap_analysis_generated")
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.new_value["gap_count"], 1)

    def test_regenerating_creates_a_new_version_and_keeps_the_old_one(self):
        first = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        second = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertEqual(RegulatoryGapAnalysisReport.objects.count(), 2)

    def test_regenerating_does_not_duplicate_the_review_gate(self):
        gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        gate_count = RegulatoryReviewGate.objects.filter(
            content_type__model="andauserreports", object_id=self.submission.pk
        ).count()
        self.assertEqual(gate_count, 1)

    def test_report_is_immutable(self):
        report = gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.user)
        report.gap_count = 99
        with self.assertRaises(ValueError):
            report.save()
        with self.assertRaises(ValueError):
            report.delete()


class DMFGapAnalysisTests(TestCase):
    """Automated gap analysis over DMFCAAnswer data only (see model docstring)."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="dmf_doer", password="testpass123", role="company_user"
        )
        self.checklist = DMFChecklistUser.objects.create(
            user=self.user, name_of_api="TestAPI", name_of_api_vendor="TestVendor", dmf="12345",
        )
        self.q_pass = DMFCATableQuestion.objects.create(
            module="Quality", category="CMC", sub_category="Manufacturing",
            ectd_no="3.2.S.2", question="Is the manufacturing process described?",
        )
        self.q_fail = DMFCATableQuestion.objects.create(
            module="Quality", category="CMC", sub_category="Impurities",
            ectd_no="3.2.S.3", question="Are impurity limits justified?",
        )
        DMFCAAnswer.objects.create(checklist=self.checklist, dmf_ca=self.q_pass, answer="yes")
        DMFCAAnswer.objects.create(checklist=self.checklist, dmf_ca=self.q_fail, answer="no")

    def test_gap_analysis_counts_no_answer_as_a_gap(self):
        report = gap_analysis.generate_dmf_gap_analysis(self.checklist, generated_by=self.user)
        self.assertEqual(report.source_type, "dmf")
        self.assertEqual(report.total_questions, 2)
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(report.gap_details[0]["question_id"], self.q_fail.pk)

    def test_not_applicable_answer_is_not_a_gap(self):
        DMFCAAnswer.objects.create(
            checklist=self.checklist,
            dmf_ca=DMFCATableQuestion.objects.create(module="Quality", question="N/A question"),
            answer="not_applicable",
        )
        report = gap_analysis.generate_dmf_gap_analysis(self.checklist, generated_by=self.user)
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(report.answered_count, 3)

    def test_generating_logs_an_audit_event_and_review_gate(self):
        gap_analysis.generate_dmf_gap_analysis(self.checklist, generated_by=self.user)
        self.assertTrue(
            RegulatoryAuditTrail.objects.filter(action_type="gap_analysis_generated").exists()
        )
        self.assertTrue(
            RegulatoryReviewGate.objects.filter(
                content_type__model="dmfchecklistuser", object_id=self.checklist.pk
            ).exists()
        )


class ReviewGateApprovalWorkflowTests(TestCase):
    """Doer -> Reviewer -> VP progression via the review_gate_action view logic path."""

    def setUp(self):
        self.doer = CustomUser.objects.create_user(
            username="workflow_doer", password="testpass123", role="company_user"
        )
        self.reviewer = CustomUser.objects.create_user(
            username="workflow_reviewer", password="testpass123", role="company_checker"
        )
        self.vp_user = CustomUser.objects.create_user(
            username="workflow_vp", password="testpass123", role="company_checker"
        )
        RegulatoryRole.objects.create(user=self.vp_user, role="vp")

        self.report_type = "Solid Oral Dosage"
        question = ANDAReportQuestions.objects.create(
            report_name=self.report_type, module_name="Module 1", chapter_name="1.1",
            category_name="Administrative", question="Q",
        )
        self.submission = ANDAUserReports.objects.create(
            user=self.doer, report_name=question, product_name="Drug",
        )
        ANDAUserAnswers.objects.create(
            user=self.doer, report_name=self.submission, report_question=question, answer="no",
        )
        gap_analysis.generate_anda_gap_analysis(self.submission, generated_by=self.doer)
        self.gate = RegulatoryReviewGate.objects.get(
            content_type__model="andauserreports", object_id=self.submission.pk
        )

    def test_reviewer_approval_moves_to_pending_vp(self):
        self.gate.reviewer = self.reviewer
        self.gate.reviewer_comment = "ok"
        self.gate.status = "pending_vp"
        self.gate.save()

        refreshed = RegulatoryReviewGate.objects.get(pk=self.gate.pk)
        self.assertEqual(refreshed.status, "pending_vp")

    def test_vp_approval_after_reviewer_marks_fully_approved(self):
        self.gate.reviewer = self.reviewer
        self.gate.status = "pending_vp"
        self.gate.save()

        self.gate.vp = self.vp_user
        self.gate.vp_comment = "approved"
        self.gate.status = "approved"
        self.gate.save()

        refreshed = RegulatoryReviewGate.objects.get(pk=self.gate.pk)
        self.assertEqual(refreshed.status, "approved")
        self.assertEqual(refreshed.vp, self.vp_user)

    def test_rejection_records_reason(self):
        self.gate.status = "rejected"
        self.gate.rejection_reason = "missing stability data"
        self.gate.save()

        refreshed = RegulatoryReviewGate.objects.get(pk=self.gate.pk)
        self.assertEqual(refreshed.status, "rejected")
        self.assertEqual(refreshed.rejection_reason, "missing stability data")


class GapAnalysisHttpTests(TestCase):
    """
    Full HTTP request/response/template-render cycle for every new route,
    via Django's test Client against the clean, migration-built test
    database (this sidesteps the local dev db.sqlite3 snapshot's
    pre-existing, unrelated schema drift entirely).
    """

    def setUp(self):
        self.doer = CustomUser.objects.create_user(
            username="http_doer", password="testpass123", role="company_user"
        )
        self.reviewer = CustomUser.objects.create_user(
            username="http_reviewer", password="testpass123", role="company_checker"
        )

        question = ANDAReportQuestions.objects.create(
            report_name="Solid Oral Dosage", module_name="Module 1", chapter_name="1.1",
            category_name="Administrative", question="Is the cover letter present?",
        )
        self.submission = ANDAUserReports.objects.create(
            user=self.doer, report_name=question, product_name="HttpTestDrug", is_completed_by_doer=True,
        )
        ANDAUserAnswers.objects.create(
            user=self.doer, report_name=self.submission, report_question=question, answer="no",
        )

        self.dmf_checklist = DMFChecklistUser.objects.create(
            user=self.doer, name_of_api="HttpTestAPI", is_completed_by_doer=True,
        )
        dmf_question = DMFCATableQuestion.objects.create(module="Quality", question="Q1")
        DMFCAAnswer.objects.create(checklist=self.dmf_checklist, dmf_ca=dmf_question, answer="no")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get("/ratools/gap-analysis/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/adminmaster/login/", response.url)

    def test_doer_sees_only_their_own_submissions_in_list(self):
        self.client.login(username="http_doer", password="testpass123")
        response = self.client.get("/ratools/gap-analysis/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HttpTestDrug")
        self.assertContains(response, "HttpTestAPI")
        self.assertContains(response, "Not yet analyzed")

    def test_generate_anda_gap_analysis_redirects_to_detail_and_renders_gap(self):
        self.client.login(username="http_doer", password="testpass123")
        response = self.client.post(
            f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/", follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Is the cover letter present?")
        self.assertContains(response, "0.00%")  # single answered question, answered "no"

    def test_generate_dmf_gap_analysis_redirects_to_detail_and_renders_gap(self):
        self.client.login(username="http_doer", password="testpass123")
        response = self.client.post(
            f"/ratools/gap-analysis/dmf/{self.dmf_checklist.pk}/generate/", follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DMF")

    def test_other_users_checklist_cannot_be_generated_by_a_plain_company_user(self):
        other_user = CustomUser.objects.create_user(
            username="http_other", password="testpass123", role="company_user"
        )
        self.client.login(username="http_other", password="testpass123")
        response = self.client.post(f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/")
        self.assertEqual(response.status_code, 403)

    def test_checker_can_generate_gap_analysis_for_any_completed_submission(self):
        self.client.login(username="http_reviewer", password="testpass123")
        response = self.client.post(
            f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/", follow=True
        )
        self.assertEqual(response.status_code, 200)

    def test_export_csv_returns_attachment(self):
        self.client.login(username="http_doer", password="testpass123")
        gen_response = self.client.post(
            f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/", follow=True
        )
        report = RegulatoryGapAnalysisReport.objects.filter(source_type="anda").latest("created_at")
        response = self.client.get(f"/ratools/gap-analysis/{report.pk}/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])
        content = response.content.decode()
        self.assertIn("Is the cover letter present?", content)

    def test_reviewer_can_approve_via_http(self):
        self.client.login(username="http_doer", password="testpass123")
        self.client.post(f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/")
        gate = RegulatoryReviewGate.objects.get(
            content_type__model="andauserreports", object_id=self.submission.pk
        )
        self.client.logout()

        self.client.login(username="http_reviewer", password="testpass123")
        response = self.client.post(
            f"/ratools/gap-analysis/review-gate/{gate.pk}/action/",
            {"action": "approve", "comment": "looks fine"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        gate.refresh_from_db()
        self.assertEqual(gate.status, "pending_vp")
        self.assertEqual(gate.reviewer_comment, "looks fine")

    def test_non_reviewer_cannot_approve(self):
        self.client.login(username="http_doer", password="testpass123")
        self.client.post(f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/")
        gate = RegulatoryReviewGate.objects.get(
            content_type__model="andauserreports", object_id=self.submission.pk
        )
        response = self.client.post(
            f"/ratools/gap-analysis/review-gate/{gate.pk}/action/",
            {"action": "approve", "comment": "self-approving"},
        )
        self.assertEqual(response.status_code, 403)

    def test_audit_trail_page_shows_the_gap_analysis_event(self):
        self.client.login(username="http_doer", password="testpass123")
        self.client.post(f"/ratools/gap-analysis/anda/{self.submission.pk}/generate/")
        response = self.client.get("/ratools/audit-trail/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gap Analysis Generated")


class CheckerHasOpenReviewTests(TestCase):
    """
    Guard around the workflow-status lookup in the checker branch.

    `statues` is None until the doer submits, and the per-level / per-user keys
    appear only as the workflow reaches them, so the original chained lookup
    raised TypeError/KeyError for a checker opening an unsubmitted checklist.
    """

    class _Record:
        def __init__(self, statues):
            self.statues = statues

    class _User:
        id = 7
        first_name = "Asha"

    def _check(self, statues, level):
        from RATools.views import checker_has_open_review
        return checker_has_open_review(self._Record(statues), self._User(), level)

    def test_open_review_at_the_users_level_is_true(self):
        self.assertTrue(self._check({"Checker Level 1 Status": {"7": {"Asha": "In Review"}}}, 1))
        self.assertTrue(self._check({"Checker Level 3 Status": {"7": {"Asha": "In Review"}}}, 3))

    def test_unsubmitted_checklist_has_no_statuses(self):
        self.assertFalse(self._check(None, 1))
        self.assertFalse(self._check({}, 1))

    def test_level_not_yet_reached(self):
        self.assertFalse(self._check({"Your Status": {}}, 1))

    def test_user_is_not_a_checker_on_this_report(self):
        # get_checker_level() returns None in that case.
        self.assertFalse(self._check({"Checker Level 1 Status": {"7": {"Asha": "In Review"}}}, None))

    def test_a_different_checker_holds_the_level(self):
        self.assertFalse(self._check({"Checker Level 1 Status": {"9": {"Asha": "In Review"}}}, 1))

    def test_already_actioned_is_not_an_open_review(self):
        self.assertFalse(self._check({"Checker Level 1 Status": {"7": {"Asha": "Approved"}}}, 1))
