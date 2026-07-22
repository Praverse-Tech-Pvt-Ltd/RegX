"""Shared abstract base models for REGX."""

import uuid
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base providing created_at / updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIDModel(models.Model):
    """Abstract base adding a UUID public identifier.

    Internal BigAutoField PK is never exposed in API responses.
    Callers use public_id (UUID) for all external references.
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True
