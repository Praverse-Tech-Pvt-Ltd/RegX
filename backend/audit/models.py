"""
Immutable audit event model.

ORM-level immutability: save() and delete() raise after creation.
PostgreSQL trigger-level immutability is applied via a migration RunSQL operation
in the initial migration (see migrations/0001_initial.py).
"""

from django.db import models


class ImmutableManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset()


class AuditEvent(models.Model):
    """
    Append-only audit record.  Never update or delete rows in this table.
    The PostgreSQL trigger enforces this at the database level.
    """

    actor_id = models.BigIntegerField(null=True, blank=True)
    actor_email = models.EmailField(blank=True)
    tenant_id = models.BigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Event"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("AuditEvent records are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditEvent records cannot be deleted.")

    def __str__(self):
        return f"{self.event_type} by {self.actor_email} at {self.created_at}"
