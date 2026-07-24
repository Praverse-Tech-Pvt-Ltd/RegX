"""
Persisted IID assessment snapshots.

An AssessmentSnapshot freezes the exact FDA precedent record, formulation
inputs, calculation results, and decision produced at one point in time.
It is created once and never mutated -- a later FDA data refresh, or a
correction to the underlying formulation, can never retroactively change
what a completed assessment displayed. This is the reproducibility
guarantee: a regulatory submission that references an assessment years
later must see exactly what was shown at the time.
"""

from django.core.exceptions import ValidationError
from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class AssessmentSnapshot(PublicIDModel, TimeStampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="iid_assessment_snapshots"
    )
    formulation_component_public_id = models.UUIDField()
    formulation_version_public_id = models.UUIDField()

    # Frozen FDA precedent identity -- public UUIDs only, never a live FK
    # into fda_data, so this row's meaning cannot drift if the underlying
    # IID/Orange Book row is later superseded or its mapping changes.
    iid_release_public_id = models.UUIDField(null=True, blank=True)
    iid_precedent_record_public_id = models.UUIDField(null=True, blank=True)
    iid_ingredient_name = models.CharField(max_length=500, blank=True)
    iid_route = models.CharField(max_length=255, blank=True)
    iid_dosage_form = models.CharField(max_length=255, blank=True)
    iid_potency_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    iid_potency_unit = models.CharField(max_length=50, blank=True)
    iid_mde = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    iid_mde_unit = models.CharField(max_length=50, blank=True)

    proposed_quantity_per_unit = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    proposed_quantity_unit = models.CharField(max_length=50, blank=True)
    proposed_daily_exposure = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )

    calculation_results = models.JSONField(default=dict)
    match_status = models.CharField(max_length=40, blank=True)
    decision_status = models.CharField(max_length=40, blank=True)
    decision_note = models.TextField(blank=True)

    reviewer_confirmed_match = models.BooleanField(default=False)
    reviewer = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    override_applied = models.BooleanField(default=False)
    override_justification = models.TextField(blank=True)
    final_conclusion = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_iid_assessment_snapshots",
    )

    class Meta:
        indexes = [models.Index(fields=["tenant", "formulation_component_public_id"])]

    def __str__(self):
        return f"Assessment {self.public_id} ({self.decision_status})"

    def clean(self):
        # Immutable once created -- a correction requires a new snapshot,
        # never an edit, so a completed assessment can never be altered
        # retroactively by a later FDA data refresh or formulation change.
        if self.pk:
            original = AssessmentSnapshot.objects.filter(pk=self.pk).first()
            if original:
                mutable_fields = {"reviewer_confirmed_match", "reviewer", "updated_at"}
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in mutable_fields
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"AssessmentSnapshot {self.pk} is immutable once created; "
                        f"cannot change {sorted(changed_fields)}. Create a new snapshot instead."
                    )
