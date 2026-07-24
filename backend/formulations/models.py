"""
Tenant-owned product-development and formulation domain.

Every quantity field here is a Decimal, never a float. Approved formulation
versions are immutable -- corrections create a new version, never an edit.
Selection of an Orange Book reference product is always an explicit user
action (never auto-selected), and every selection is snapshotted with the
exact release/product/application identifiers and a timestamp so a later
FDA data refresh can never retroactively change what a formulation
recorded as its reference at selection time.
"""

from django.core.exceptions import ValidationError
from django.db import models

from common.models import PublicIDModel, TimeStampedModel

from .managers import (
    FormulationVersionRelatedManager,
    RelatedTenantScopedManager,
    TenantScopedManager,
)


class ReleaseType(models.TextChoices):
    IMMEDIATE = "immediate", "Immediate Release"
    DELAYED = "delayed", "Delayed Release"
    EXTENDED = "extended", "Extended Release"
    OTHER = "other", "Other"


class ProductRecordStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    RETIRED = "retired", "Retired"


class ProductDevelopmentRecord(PublicIDModel, TimeStampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="product_development_records"
    )
    product_code = models.CharField(max_length=100)
    proposed_product_name = models.CharField(max_length=500)
    active_ingredient = models.CharField(max_length=500)
    is_combination_product = models.BooleanField(default=False)
    release_type = models.CharField(
        max_length=20, choices=ReleaseType.choices, default=ReleaseType.IMMEDIATE
    )
    route = models.CharField(max_length=255, blank=True)
    dosage_form = models.CharField(max_length=255, blank=True)
    proposed_strength_amount = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    proposed_strength_unit = models.CharField(max_length=50, blank=True)
    regulatory_market_context = models.CharField(max_length=255, blank=True)

    # Explicit Orange Book reference-product selection -- never auto-picked,
    # even when only one candidate exists. FK to fda_data.OrangeBookProduct
    # is intentionally NOT used here: selection must be an immutable
    # snapshot of what was selected at the time, independent of whatever
    # that product row looks like after a later FDA data refresh.
    selected_ob_application_number = models.CharField(max_length=50, blank=True)
    selected_ob_product_number = models.CharField(max_length=50, blank=True)
    selected_ob_product_public_id = models.UUIDField(null=True, blank=True)
    selected_ob_release_public_id = models.UUIDField(null=True, blank=True)
    selection_timestamp = models.DateTimeField(null=True, blank=True)
    selecting_user = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_reference_products",
    )
    selection_justification = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=ProductRecordStatus.choices, default=ProductRecordStatus.DRAFT
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_product_records",
    )

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "product_code"], name="unique_product_code_per_tenant"
            ),
        ]

    def __str__(self):
        return f"{self.product_code}: {self.proposed_product_name}"

    @property
    def has_selected_reference_product(self) -> bool:
        return bool(self.selected_ob_product_public_id)


class FormulationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


IMMUTABLE_FORMULATION_STATUSES = frozenset(
    {FormulationStatus.APPROVED, FormulationStatus.SUPERSEDED, FormulationStatus.RETIRED}
)


class FormulationVersion(PublicIDModel, TimeStampedModel):
    product = models.ForeignKey(
        ProductDevelopmentRecord, on_delete=models.CASCADE, related_name="formulation_versions"
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=FormulationStatus.choices, default=FormulationStatus.DRAFT
    )
    total_dosage_unit_weight = models.DecimalField(max_digits=20, decimal_places=6)
    total_dosage_unit_weight_unit = models.CharField(max_length=50)
    batch_size = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    batch_size_unit = models.CharField(max_length=50, blank=True)
    overage_percentage = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    maximum_dosage_units_per_day = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    dosing_basis = models.CharField(max_length=255, blank=True)
    rationale = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_formulation_versions",
    )

    objects = RelatedTenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "version_number"], name="unique_formulation_version_number"
            ),
            models.CheckConstraint(
                check=models.Q(total_dosage_unit_weight__gt=0),
                name="formulation_total_weight_positive",
            ),
        ]

    def __str__(self):
        return f"{self.product.product_code} v{self.version_number} ({self.status})"

    def clean(self):
        if self.pk:
            original = FormulationVersion.objects.filter(pk=self.pk).first()
            if original and original.status in IMMUTABLE_FORMULATION_STATUSES:
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in ("status", "updated_at")
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"FormulationVersion {self.pk} is {original.status} and immutable; "
                        f"cannot change {sorted(changed_fields)}. Create a new version instead."
                    )


class ComponentType(models.TextChoices):
    ACTIVE = "active", "Active Ingredient"
    INACTIVE = "inactive", "Inactive Ingredient"


class FormulationComponent(PublicIDModel, TimeStampedModel):
    formulation_version = models.ForeignKey(
        FormulationVersion, on_delete=models.CASCADE, related_name="components"
    )
    component_type = models.CharField(max_length=10, choices=ComponentType.choices)
    ingredient_name = models.CharField(max_length=500)
    resolved_ingredient_public_id = models.UUIDField(null=True, blank=True)
    resolved_unii = models.CharField(max_length=20, blank=True)
    function = models.CharField(max_length=255, blank=True)
    grade = models.CharField(max_length=255, blank=True)
    quantity_per_dosage_unit = models.DecimalField(max_digits=20, decimal_places=6)
    quantity_unit = models.CharField(max_length=50)
    percentage_w_w_snapshot = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    quantity_per_batch = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    batch_quantity_unit = models.CharField(max_length=50, blank=True)
    overage_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    justification = models.TextField(blank=True)
    specification_reference = models.CharField(max_length=500, blank=True)
    evidence_document_reference = models.UUIDField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    objects = FormulationVersionRelatedManager()

    class Meta:
        ordering = ["display_order"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity_per_dosage_unit__gt=0),
                name="formulation_component_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.ingredient_name} ({self.quantity_per_dosage_unit} {self.quantity_unit})"


class DosingRegimen(PublicIDModel, TimeStampedModel):
    formulation_version = models.ForeignKey(
        FormulationVersion, on_delete=models.CASCADE, related_name="dosing_regimens"
    )
    units_per_administration = models.DecimalField(max_digits=10, decimal_places=4)
    administrations_per_day = models.DecimalField(max_digits=10, decimal_places=4)
    maximum_units_per_day = models.DecimalField(max_digits=10, decimal_places=4)
    patient_population = models.CharField(max_length=255, blank=True)
    basis = models.CharField(max_length=255, blank=True)
    source_justification = models.TextField(blank=True)

    objects = FormulationVersionRelatedManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(maximum_units_per_day__gt=0),
                name="dosing_regimen_max_units_positive",
            ),
        ]

    def __str__(self):
        return f"{self.maximum_units_per_day} units/day max"
