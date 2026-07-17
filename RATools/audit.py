"""
Audit-trail helper for Regulatory Technical Tools AI.

Any future RATools feature (calculators, gap analysis, document versioning,
review actions, exports, ...) should call log_event() instead of writing to
RegulatoryAuditTrail directly, so the immutability/serialization rules stay
in one place.
"""

from .models import RegulatoryAuditTrail


def log_event(
    *,
    user,
    action_type,
    target=None,
    previous_value=None,
    new_value=None,
    reason="",
):
    """
    Create one immutable RegulatoryAuditTrail entry.

    user: the CustomUser performing the action (may be None for system events).
    action_type: one of RegulatoryAuditTrail.ACTION_CHOICES.
    target: an optional model instance the event relates to (e.g. a
        checklist row, a future calculator result). Stored via a generic FK.
    previous_value / new_value: JSON-serializable snapshots, e.g.
        {"field": "old"} / {"field": "new"}.
    reason: free-text justification (e.g. "rejected: missing dissolution data").
    """
    return RegulatoryAuditTrail.objects.create(
        user=user,
        role_at_time=getattr(user, "role", "") or "",
        action_type=action_type,
        content_type=None if target is None else _content_type_for(target),
        object_id=None if target is None else target.pk,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
    )


def _content_type_for(instance):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(instance)
