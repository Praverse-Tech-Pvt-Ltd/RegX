"""
Tests for AuditEvent immutability (ORM level).
PostgreSQL trigger-level immutability is verified by the migration itself;
these tests cover the Django ORM guard that prevents accidental mutation.
"""

import pytest

from audit.models import AuditEvent


@pytest.mark.django_db
class TestAuditEventImmutability:
    def test_create_audit_event_succeeds(self):
        event = AuditEvent.objects.create(
            event_type="test.created",
            actor_email="actor@example.com",
            payload={"key": "value"},
        )
        assert event.pk is not None

    def test_update_audit_event_raises(self):
        event = AuditEvent.objects.create(event_type="test.created")
        event.event_type = "tampered"
        with pytest.raises(PermissionError, match="immutable"):
            event.save()

    def test_delete_audit_event_raises(self):
        event = AuditEvent.objects.create(event_type="test.created")
        with pytest.raises(PermissionError, match="cannot be deleted"):
            event.delete()

    def test_queryset_delete_raises(self):
        AuditEvent.objects.create(event_type="test.created")
        with pytest.raises(PermissionError, match="cannot be deleted"):
            # Each object's delete() is called; the override catches it
            for evt in AuditEvent.objects.filter(event_type="test.created"):
                evt.delete()
