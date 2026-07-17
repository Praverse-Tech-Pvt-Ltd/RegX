from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from AdminMaster.models import CustomUser
from RATools import audit
from RATools.models import RegulatoryAuditTrail, RegulatoryReviewGate, RegulatoryRole


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
