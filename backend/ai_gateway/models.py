"""The platform AI switch and one metrics row per AI call.

`AICallRecord` has **no text column**: no prompt, no response, no error body.
It cannot store client content because there is nowhere to put it.
"""

from django.conf import settings
from django.db import models

from common.models import PublicIDModel


class AISwitch(models.Model):
    """Platform-level on/off switch, a single row (pk=1).

    Off by default. AI runs only when this is on AND the REGX_AI_ENABLED setting
    is true, so an operator can stop every AI call at once without a redeploy.
    Only a platform administrator (superuser) may change it.
    """

    SINGLETON_PK = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_PK, editable=False)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="ai_switch_is_a_single_row"),
        ]

    @classmethod
    def is_on(cls) -> bool:
        return cls.objects.filter(pk=cls.SINGLETON_PK, enabled=True).exists()


class CallOutcome(models.TextChoices):
    OK = "OK", "Answered"
    DISABLED = "DISABLED", "AI is turned off"
    NOT_CONFIGURED = "NOT_CONFIGURED", "AI is not configured"
    TENANT_REFUSED = "TENANT_REFUSED", "No tenant, or the user is not a member"
    CIRCUIT_OPEN = "CIRCUIT_OPEN", "Provider paused after repeated failures"
    PROVIDER_ERROR = "PROVIDER_ERROR", "Provider failed"


class AICallRecord(PublicIDModel):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128, blank=True)
    prompt_id = models.CharField(max_length=64)
    prompt_version = models.PositiveIntegerField()
    outcome = models.CharField(max_length=20, choices=CallOutcome.choices)
    #: The enumerated provider/config/tenant reason, or "" on success.
    reason_code = models.CharField(max_length=32, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["outcome", "created_at"])]
