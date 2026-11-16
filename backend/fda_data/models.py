"""
FDA source-data governance domain.

Platform-level, tenant-independent reference data ingested from official
FDA sources only (Orange Book, FDA Inactive Ingredient Database, FDA
substance-registration and terminology sources). Never scraped commercial
data. These models hold FDA *precedent and identification* data -- Orange
Book does not supply excipient quantities, and an IID potency/MDE value is
precedent information, never an automatically safe, recommended, or target
formulation amount, and never automatic regulatory acceptance.

No tenant field exists on any model here: this data is platform-wide
reference data, not tenant-owned content. Tenant users get read-only
access via permission (see permissions.py), not queryset scoping.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class FDADatasetType(models.TextChoices):
    ORANGE_BOOK_PRODUCTS = "orange_book_products", "Orange Book Products"
    ORANGE_BOOK_DISCONTINUED = "orange_book_discontinued", "Orange Book Discontinued Products"
    ORANGE_BOOK_PATENTS = "orange_book_patents", "Orange Book Patents"
    ORANGE_BOOK_EXCLUSIVITY = "orange_book_exclusivity", "Orange Book Exclusivity"
    FDA_IID = "fda_iid", "FDA Inactive Ingredient Database"
    FDA_SUBSTANCE_IDENTIFIERS = "fda_substance_identifiers", "FDA Substance Registration (UNII)"
    FDA_ROUTE_TERMINOLOGY = "fda_route_terminology", "FDA Route Terminology"
    FDA_DOSAGE_FORM_TERMINOLOGY = "fda_dosage_form_terminology", "FDA Dosage Form Terminology"


class FDAReleaseStatus(models.TextChoices):
    REGISTERED = "registered", "Registered"
    STAGED = "staged", "Staged"
    VALIDATED = "validated", "Validated"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    REJECTED = "rejected", "Rejected"


# Once a release reaches one of these statuses its content/provenance
# fields are immutable -- only status/superseded_by_release/updated_at may
# still change (the transition itself), matching TemplateVersion's pattern.
IMMUTABLE_RELEASE_STATUSES = frozenset(
    {
        FDAReleaseStatus.APPROVED,
        FDAReleaseStatus.ACTIVE,
        FDAReleaseStatus.SUPERSEDED,
        FDAReleaseStatus.REJECTED,
    }
)


class FDADataSourceRelease(PublicIDModel, TimeStampedModel):
    """One ingested official FDA file. Checksum-immutable, never silently
    replaced -- a new release for the same dataset_type is a new row,
    approved and activated independently; activation supersedes (never
    deletes) the prior active release for that dataset_type."""

    dataset_type = models.CharField(max_length=40, choices=FDADatasetType.choices, db_index=True)
    source_name = models.CharField(max_length=255)
    official_source_reference = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=100, blank=True)
    # Storage key into documents.storage's LocalStorage/S3CompatibleStorage
    # abstraction (platform-level files use a reserved pseudo-tenant id --
    # see fda_data.storage.PLATFORM_STORAGE_TENANT_ID). Never exposed
    # directly in API responses; view_raw-gated like templates_registry's
    # source_path_or_reference.
    storage_key = models.CharField(max_length=500, blank=True)
    #: SHA-256 of the exact bytes that were handed to `register_release`.
    #:
    #: Which bytes those are depends on the caller, and the distinction
    #: matters:
    #:   * `import_fda_release` supplies the original FDA file or ZIP, so this
    #:     is the checksum of the published artifact.
    #:   * `POST /fda-data/releases/` supplies canonical JSON rows, so this is
    #:     the checksum of that payload -- it says nothing about any file.
    #:
    #: Unchanged in meaning by P5: it has always been "the bytes supplied".
    #: `normalized_payload_sha256` below is the new, separate value.
    source_checksum_sha256 = models.CharField(max_length=64, db_index=True)
    #: SHA-256 of the canonical normalized rows, independent of how they
    #: arrived. Two different source files that normalize identically share
    #: this value while keeping distinct `source_checksum_sha256`, so the
    #: provenance stays distinguishable.
    normalized_payload_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    #: Size of the supplied source bytes. Recorded alongside the checksum
    #: because a length mismatch is the cheapest first signal that a file is
    #: not the one somebody believes it is.
    source_file_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    #: Which parser produced the rows, e.g. "orange_book_products_txt:1".
    #: Blank for releases registered through the JSON API, where no parser
    #: ran and the caller normalized the data themselves.
    parser_identifier = models.CharField(max_length=100, blank=True)
    schema_version = models.CharField(max_length=50, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    retrieved_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    imported_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="imported_fda_releases",
    )
    record_count_expected = models.PositiveIntegerField(default=0)
    record_count_extracted = models.PositiveIntegerField(default=0)
    record_count_imported = models.PositiveIntegerField(default=0)
    record_count_failed = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=FDAReleaseStatus.choices, default=FDAReleaseStatus.REGISTERED
    )
    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_fda_releases",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "identity.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_fda_releases",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    superseded_by_release = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )
    notes = models.TextField(blank=True)
    correlation_id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_type", "source_checksum_sha256"],
                name="unique_release_checksum_per_dataset_type",
            ),
            models.UniqueConstraint(
                fields=["dataset_type"],
                condition=models.Q(status=FDAReleaseStatus.ACTIVE),
                name="unique_active_release_per_dataset_type",
            ),
        ]
        indexes = [models.Index(fields=["dataset_type", "status"])]

    def __str__(self):
        return f"{self.dataset_type} release ({self.status})"

    def clean(self):
        if self.pk:
            original = FDADataSourceRelease.objects.filter(pk=self.pk).first()
            if original and original.status in IMMUTABLE_RELEASE_STATUSES:
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in ("status", "superseded_by_release", "updated_at")
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"FDADataSourceRelease {self.pk} is {original.status} and immutable; "
                        f"cannot change {sorted(changed_fields)}. Register a new release instead."
                    )


class MappingStatus(models.TextChoices):
    UNMAPPED = "unmapped", "Unmapped"
    PROPOSED = "proposed", "Proposed"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    REVIEW_REQUIRED = "review_required", "Review Required"


class ControlledRoute(PublicIDModel, TimeStampedModel):
    """A canonical, FDA-sourced route of administration. Never created or
    approved automatically from a fuzzy match -- only via reviewed
    RouteMapping decisions (see below)."""

    code = models.CharField(max_length=50, unique=True)
    canonical_label = models.CharField(max_length=255)
    fda_source = models.CharField(max_length=255, blank=True)
    active_release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.SET_NULL, null=True, blank=True
    )
    aliases = models.JSONField(default=list, blank=True)
    lifecycle = models.CharField(
        max_length=20,
        choices=[("draft", "Draft"), ("active", "Active"), ("retired", "Retired")],
        default="draft",
    )

    def __str__(self):
        return self.canonical_label


class ControlledDosageForm(PublicIDModel, TimeStampedModel):
    code = models.CharField(max_length=50, unique=True)
    canonical_label = models.CharField(max_length=255)
    fda_source = models.CharField(max_length=255, blank=True)
    active_release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.SET_NULL, null=True, blank=True
    )
    aliases = models.JSONField(default=list, blank=True)
    lifecycle = models.CharField(
        max_length=20,
        choices=[("draft", "Draft"), ("active", "Active"), ("retired", "Retired")],
        default="draft",
    )

    def __str__(self):
        return self.canonical_label


class UnitDimension(models.TextChoices):
    MASS = "mass", "Mass"
    VOLUME = "volume", "Volume"
    COUNT = "count", "Count"
    PERCENTAGE = "percentage", "Percentage"
    CONCENTRATION = "concentration", "Concentration"


class ControlledUnit(PublicIDModel, TimeStampedModel):
    """A canonical unit within one dimension. conversion_factor_to_base is
    the multiplier converting one of this unit into the dimension's
    canonical base unit (base mass = microgram, base volume = microlitre,
    base count = 1 unit). Percentage/concentration units have no static
    factor -- they require an explicit basis at calculation time and are
    handled by iid_assessment.unit_conversion, never here."""

    code = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=20)
    dimension = models.CharField(max_length=20, choices=UnitDimension.choices)
    conversion_factor_to_base = models.DecimalField(
        max_digits=30, decimal_places=12, null=True, blank=True
    )
    basis_requirements = models.CharField(max_length=255, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.symbol


class MappingDecisionStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    REVIEWED = "reviewed", "Reviewed"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class _BaseTerminologyMapping(PublicIDModel, TimeStampedModel):
    """Shared shape for Route/DosageForm/Unit mappings. No fuzzy mapping
    may become approved automatically -- exact aliases only create
    candidates (status=proposed); a human reviewer must move a mapping to
    approved before it is used in an active release's normalization.
    is_current distinguishes the currently-authoritative mapping for a raw
    value from superseded prior decisions -- corrections create a new row
    rather than editing an approved one."""

    source_dataset = models.CharField(max_length=40, choices=FDADatasetType.choices)
    source_raw_value = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=MappingDecisionStatus.choices, default=MappingDecisionStatus.PROPOSED
    )
    is_current = models.BooleanField(default=True)
    reviewer = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.TextField(blank=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and original.status == MappingDecisionStatus.APPROVED:
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in ("is_current", "updated_at")
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"{type(self).__name__} {self.pk} is approved and immutable; "
                        f"cannot change {sorted(changed_fields)}. Propose a new mapping instead."
                    )


class RouteMapping(_BaseTerminologyMapping):
    controlled_route = models.ForeignKey(
        ControlledRoute, on_delete=models.SET_NULL, null=True, blank=True, related_name="mappings"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "source_raw_value"],
                condition=models.Q(is_current=True),
                name="unique_current_route_mapping",
            ),
        ]

    def __str__(self):
        return f"{self.source_raw_value} -> {self.controlled_route}"


class DosageFormMapping(_BaseTerminologyMapping):
    controlled_dosage_form = models.ForeignKey(
        ControlledDosageForm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mappings",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "source_raw_value"],
                condition=models.Q(is_current=True),
                name="unique_current_dosage_form_mapping",
            ),
        ]

    def __str__(self):
        return f"{self.source_raw_value} -> {self.controlled_dosage_form}"


class UnitMapping(_BaseTerminologyMapping):
    controlled_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="mappings"
    )
    #: The structured meaning of the raw string (e.g. `mg/5ml` -> mass per 5 mL).
    #: Used only once the mapping is approved.
    quantity_expression = models.ForeignKey(
        "QuantityExpression",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="unit_mappings",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "source_raw_value"],
                condition=models.Q(is_current=True),
                name="unique_current_unit_mapping",
            ),
        ]

    def __str__(self):
        return f"{self.source_raw_value} -> {self.controlled_unit}"


class QuantityFamily(models.TextChoices):
    """What the published number measures."""

    MASS = "mass", "Mass"
    VOLUME = "volume", "Volume"
    PERCENTAGE = "percentage", "Percentage"


class QuantityBasis(models.TextChoices):
    """What the published number is relative to. Part of the unit, never assumed."""

    PER_DOSE_UNIT = "per_dose_unit", "Per dose unit"
    PER_VOLUME = "per_volume", "Per stated volume"
    PER_DAY = "per_day", "Per day (maximum daily exposure)"
    W_W = "w_w", "w/w"
    W_V = "w_v", "w/v"
    V_V = "v_v", "v/v"


#: The only family/basis pairs a quantity can have (also enforced by a CHECK constraint).
QUANTITY_BASES_BY_FAMILY = {
    QuantityFamily.MASS: (
        QuantityBasis.PER_DOSE_UNIT,
        QuantityBasis.PER_VOLUME,
        QuantityBasis.PER_DAY,
    ),
    QuantityFamily.VOLUME: (QuantityBasis.PER_DOSE_UNIT, QuantityBasis.PER_VOLUME),
    QuantityFamily.PERCENTAGE: (QuantityBasis.W_W, QuantityBasis.W_V, QuantityBasis.V_V),
}


class QuantityExpression(PublicIDModel, TimeStampedModel):
    """The structured meaning of a published unit string such as `mg/5ml` or `%w/v`
    (docs/CONTROLLED_UNITS_DESIGN.md section 3B). One row per distinct meaning, shared
    by every record that uses it; the amount stays on the record.

    Two quantities are of the same kind only if family AND basis are equal. Nothing
    here converts between families or bases; that is refused by design.

    - mass/volume: `numerator_unit` is a ControlledUnit of that dimension.
    - percentage: no units; the basis (w/w, w/v, v/v) is the whole meaning.
    - per_volume: `denominator_amount` + `denominator_unit` (a volume) state the
      volume, e.g. mg per **5** mL. Other bases have no denominator.

    Rows are immutable once saved: a different meaning is a new row.
    """

    family = models.CharField(max_length=20, choices=QuantityFamily.choices)
    basis = models.CharField(max_length=20, choices=QuantityBasis.choices)
    numerator_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    denominator_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    denominator_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="quantity_family_basis_allowed",
                condition=(
                    models.Q(
                        family=QuantityFamily.MASS,
                        basis__in=[b.value for b in QUANTITY_BASES_BY_FAMILY[QuantityFamily.MASS]],
                    )
                    | models.Q(
                        family=QuantityFamily.VOLUME,
                        basis__in=[
                            b.value for b in QUANTITY_BASES_BY_FAMILY[QuantityFamily.VOLUME]
                        ],
                    )
                    | models.Q(
                        family=QuantityFamily.PERCENTAGE,
                        basis__in=[
                            b.value for b in QUANTITY_BASES_BY_FAMILY[QuantityFamily.PERCENTAGE]
                        ],
                    )
                ),
            ),
            models.CheckConstraint(
                name="quantity_numerator_unit_matches_family",
                condition=(
                    models.Q(family=QuantityFamily.PERCENTAGE, numerator_unit__isnull=True)
                    | (
                        ~models.Q(family=QuantityFamily.PERCENTAGE)
                        & models.Q(numerator_unit__isnull=False)
                    )
                ),
            ),
            models.CheckConstraint(
                name="quantity_denominator_only_per_volume",
                condition=(
                    models.Q(
                        basis=QuantityBasis.PER_VOLUME,
                        # isnull is explicit: in SQL "NULL > 0" is NULL, which a CHECK accepts.
                        denominator_amount__isnull=False,
                        denominator_amount__gt=0,
                        denominator_unit__isnull=False,
                    )
                    | (
                        ~models.Q(basis=QuantityBasis.PER_VOLUME)
                        & models.Q(denominator_amount__isnull=True, denominator_unit__isnull=True)
                    )
                ),
            ),
            models.UniqueConstraint(
                fields=[
                    "family",
                    "basis",
                    "numerator_unit",
                    "denominator_amount",
                    "denominator_unit",
                ],
                nulls_distinct=False,
                name="unique_quantity_expression",
            ),
        ]

    def clean(self):
        errors = []
        if self.basis not in QUANTITY_BASES_BY_FAMILY.get(self.family, ()):
            errors.append(f"Basis {self.basis!r} is not allowed for family {self.family!r}.")
        if self.family in (QuantityFamily.MASS, QuantityFamily.VOLUME):
            if self.numerator_unit is None:
                errors.append("A mass or volume quantity needs a numerator unit.")
            elif self.numerator_unit.dimension != self.family:
                unit = self.numerator_unit
                errors.append(
                    f"Numerator unit {unit.code!r} is {unit.dimension}, not {self.family}."
                )
        elif self.numerator_unit_id is not None:
            errors.append("A percentage has no numerator unit; its basis is the meaning.")
        if self.basis == QuantityBasis.PER_VOLUME:
            if not self.denominator_amount or self.denominator_amount <= 0:
                errors.append("A per-volume quantity needs a positive denominator amount.")
            if self.denominator_unit is None:
                errors.append("A per-volume quantity needs a denominator unit.")
            elif self.denominator_unit.dimension != UnitDimension.VOLUME:
                errors.append(f"Denominator unit {self.denominator_unit.code!r} is not a volume.")
        elif self.denominator_amount is not None or self.denominator_unit_id is not None:
            errors.append("Only a per-volume quantity has a denominator.")
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and any(
                getattr(original, f) != getattr(self, f)
                for f in (
                    "family",
                    "basis",
                    "numerator_unit_id",
                    "denominator_amount",
                    "denominator_unit_id",
                )
            ):
                errors.append("A quantity expression is immutable; create a new one instead.")
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        if self.family == QuantityFamily.PERCENTAGE:
            return f"%{self.get_basis_display()}"
        num = self.numerator_unit.symbol if self.numerator_unit_id else "?"
        if self.basis == QuantityBasis.PER_VOLUME:
            den = self.denominator_unit.symbol if self.denominator_unit_id else "?"
            return f"{num}/{self.denominator_amount.normalize():f}{den}"
        return f"{num} {self.get_basis_display().lower()}"


class StrengthParseStatus(models.TextChoices):
    PARSED = "parsed", "Parsed"
    REVIEW_REQUIRED = "review_required", "Review Required"


class OrangeBookApplication(PublicIDModel, TimeStampedModel):
    release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.CASCADE, related_name="ob_applications"
    )
    application_type = models.CharField(max_length=10)
    application_number = models.CharField(max_length=50)
    applicant_short_name = models.CharField(max_length=255, blank=True)
    applicant_full_name = models.CharField(max_length=500, blank=True)
    source_row_locator = models.CharField(max_length=255, blank=True)
    raw_row_checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["release", "application_type", "application_number"],
                name="unique_ob_application_per_release",
            ),
        ]

    def __str__(self):
        return f"{self.application_type} {self.application_number}"


class OrangeBookProduct(PublicIDModel, TimeStampedModel):
    release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.CASCADE, related_name="ob_products"
    )
    application = models.ForeignKey(
        OrangeBookApplication, on_delete=models.CASCADE, related_name="products"
    )
    product_number = models.CharField(max_length=50)
    trade_name = models.CharField(max_length=500, blank=True)
    active_ingredient_raw = models.CharField(max_length=1000)
    dosage_form_raw = models.CharField(max_length=255, blank=True)
    route_raw = models.CharField(max_length=255, blank=True)
    dosage_form_normalized = models.ForeignKey(
        ControlledDosageForm, on_delete=models.SET_NULL, null=True, blank=True
    )
    route_normalized = models.ForeignKey(
        ControlledRoute, on_delete=models.SET_NULL, null=True, blank=True
    )
    strength_raw = models.CharField(max_length=500, blank=True)
    strength_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    strength_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    strength_basis = models.CharField(max_length=255, blank=True)
    strength_parse_status = models.CharField(
        max_length=20,
        choices=StrengthParseStatus.choices,
        default=StrengthParseStatus.REVIEW_REQUIRED,
    )
    rld_flag = models.BooleanField(default=False)
    reference_standard_flag = models.BooleanField(default=False)
    te_code = models.CharField(max_length=20, blank=True)
    approval_date = models.DateField(null=True, blank=True)
    approval_date_text = models.CharField(max_length=255, blank=True)
    # The Orange Book `Type` column verbatim: RX, OTC or DISCN. `discontinued`
    # is derived from it (DISCN) at import and never inferred otherwise.
    marketing_category = models.CharField(max_length=20, blank=True, db_index=True)
    discontinued = models.BooleanField(default=False)
    source_row_locator = models.CharField(max_length=255, blank=True)
    raw_row_payload = models.JSONField(default=dict)
    raw_row_checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["release", "application", "product_number"],
                name="unique_ob_product_per_release",
            ),
        ]
        indexes = [models.Index(fields=["release", "route_normalized", "dosage_form_normalized"])]

    def __str__(self):
        return f"{self.trade_name or self.active_ingredient_raw} ({self.product_number})"


class IngredientMappingStatus(models.TextChoices):
    UNMAPPED = "unmapped", "Unmapped"
    PROPOSED = "proposed", "Proposed"
    APPROVED = "approved", "Approved"
    REVIEW_REQUIRED = "review_required", "Review Required"


class OrangeBookProductIngredient(PublicIDModel, TimeStampedModel):
    """Parsed active-ingredient entry within a product row -- supports
    combination products where Orange Book's Ingredient field lists more
    than one active."""

    product = models.ForeignKey(
        OrangeBookProduct, on_delete=models.CASCADE, related_name="ingredients"
    )
    ingredient_raw = models.CharField(max_length=500)
    ingredient_normalized = models.CharField(max_length=500, blank=True)
    unii = models.CharField(max_length=20, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    unit = models.ForeignKey(
        ControlledUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    basis = models.CharField(max_length=255, blank=True)
    mapping_status = models.CharField(
        max_length=20,
        choices=IngredientMappingStatus.choices,
        default=IngredientMappingStatus.UNMAPPED,
    )
    mapping_reference = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.ingredient_raw


class IngredientSynonymStatus(models.TextChoices):
    CANONICAL = "canonical", "Canonical"
    SYNONYM = "synonym", "Synonym"


class IngredientMappingLifecycle(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    REVIEWED = "reviewed", "Reviewed"
    APPROVED = "approved", "Approved"


class IIDIngredient(PublicIDModel, TimeStampedModel):
    """Canonical inactive-ingredient identity. A synonym row points at its
    canonical_ingredient only once a reviewer has approved that mapping --
    never auto-merged from a fuzzy string match."""

    canonical_name = models.CharField(max_length=500)
    normalized_name = models.CharField(max_length=500, db_index=True)
    unii = models.CharField(max_length=20, blank=True, db_index=True)
    cas_number = models.CharField(max_length=50, blank=True)
    synonym_status = models.CharField(
        max_length=20,
        choices=IngredientSynonymStatus.choices,
        default=IngredientSynonymStatus.CANONICAL,
    )
    canonical_ingredient = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="synonyms"
    )
    source_identity = models.CharField(max_length=255, blank=True)
    mapping_lifecycle = models.CharField(
        max_length=20,
        choices=IngredientMappingLifecycle.choices,
        default=IngredientMappingLifecycle.PROPOSED,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unii"],
                condition=~models.Q(unii=""),
                name="unique_iid_ingredient_unii",
            ),
        ]
        indexes = [models.Index(fields=["normalized_name"])]

    def __str__(self):
        return self.canonical_name


class IIDCalculabilityStatus(models.TextChoices):
    CALCULABLE = "calculable", "Calculable"
    POTENCY_MISSING = "potency_missing", "Potency Missing"
    POTENCY_UNIT_MISSING = "potency_unit_missing", "Potency Unit Missing"
    POTENCY_UNPARSEABLE = "potency_unparseable", "Potency Unparseable"
    MDE_UNAVAILABLE = "mde_unavailable", "MDE Unavailable"
    ROUTE_UNMAPPED = "route_unmapped", "Route Unmapped"
    DOSAGE_FORM_UNMAPPED = "dosage_form_unmapped", "Dosage Form Unmapped"
    INGREDIENT_AMBIGUOUS = "ingredient_ambiguous", "Ingredient Ambiguous"
    REVIEW_REQUIRED = "review_required", "Review Required"


class IIDPrecedentRecord(PublicIDModel, TimeStampedModel):
    """One row from an ingested FDA IID release. potency/MDE fields are
    never forced to zero when blank or unparseable -- calculability_status
    records exactly why a value is or isn't usable, and downstream
    calculation code (iid_assessment) must check this status before using
    potency_amount/maximum_daily_exposure for anything."""

    release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.CASCADE, related_name="iid_records"
    )
    ingredient = models.ForeignKey(
        IIDIngredient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="precedent_records",
    )
    ingredient_name_raw = models.CharField(max_length=500)
    route_raw = models.CharField(max_length=255)
    route_normalized = models.ForeignKey(
        ControlledRoute, on_delete=models.SET_NULL, null=True, blank=True
    )
    dosage_form_raw = models.CharField(max_length=255)
    dosage_form_normalized = models.ForeignKey(
        ControlledDosageForm, on_delete=models.SET_NULL, null=True, blank=True
    )
    potency_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    #: The potency amount exactly as the file states it. Kept beside the parsed
    #: number so an unparseable value is never lost.
    potency_amount_raw = models.CharField(max_length=100, blank=True)
    potency_unit_raw = models.CharField(max_length=100, blank=True)
    potency_unit_normalized = models.ForeignKey(
        ControlledUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    potency_basis = models.CharField(max_length=255, blank=True)
    maximum_daily_exposure = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    #: The maximum daily exposure exactly as the file states it
    #: (`MAXIMUM_DAILY_EXPOSURE`); `mde_unit_raw` holds its unit column.
    mde_amount_raw = models.CharField(max_length=100, blank=True)
    mde_unit_raw = models.CharField(max_length=100, blank=True)
    mde_unit_normalized = models.ForeignKey(
        ControlledUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    mde_basis = models.CharField(max_length=255, blank=True)
    #: Structured meaning of potency_unit_raw / mde_unit_raw, set only from an
    #: approved UnitMapping. Null means "not established": never compared.
    potency_expression = models.ForeignKey(
        "QuantityExpression", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    mde_expression = models.ForeignKey(
        "QuantityExpression", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    source_row_locator = models.CharField(max_length=255, blank=True)
    raw_row_payload = models.JSONField(default=dict)
    raw_row_checksum = models.CharField(max_length=64, blank=True)
    calculability_status = models.CharField(
        max_length=30,
        choices=IIDCalculabilityStatus.choices,
        default=IIDCalculabilityStatus.REVIEW_REQUIRED,
        db_index=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["release", "raw_row_checksum"],
                name="unique_iid_row_per_release",
            ),
        ]
        indexes = [
            models.Index(fields=["release", "route_normalized", "dosage_form_normalized"]),
            models.Index(fields=["ingredient", "route_normalized", "dosage_form_normalized"]),
        ]

    def __str__(self):
        return f"{self.ingredient_name_raw} ({self.route_raw}/{self.dosage_form_raw})"


class FdaImportRowResultType(models.TextChoices):
    IMPORTED = "imported", "Imported"
    DUPLICATE = "duplicate", "Duplicate"
    FAILED = "failed", "Failed"
    REVIEW_REQUIRED = "review_required", "Requires Review"


class FdaImportRowResult(PublicIDModel, TimeStampedModel):
    """One result row per source row processed for a release import --
    every extracted row gets exactly one result, never silently dropped."""

    release = models.ForeignKey(
        FDADataSourceRelease, on_delete=models.CASCADE, related_name="import_results"
    )
    row_locator = models.CharField(max_length=255, blank=True)
    target_public_identifier = models.UUIDField(null=True, blank=True)
    result = models.CharField(max_length=20, choices=FdaImportRowResultType.choices, db_index=True)
    reason_code = models.CharField(max_length=100, blank=True)
    safe_detail = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["release", "row_locator"], name="unique_import_result_per_release_row"
            ),
        ]

    def __str__(self):
        return f"{self.release_id}:{self.row_locator} -> {self.result}"


class SubstanceMappingStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    RETURNED = "returned", "Returned"


class SubstanceMappingMethod(models.TextChoices):
    EXACT_NAME = "exact_name", "Exact Normalized Name"
    EXACT_UNII = "exact_unii", "Exact UNII"
    EXACT_CAS = "exact_cas", "Exact CAS Number"
    REVIEWED_SYNONYM = "reviewed_synonym", "Reviewed Synonym"
    MANUAL = "manual", "Manual"


class SubstanceSynonymMapping(PublicIDModel, TimeStampedModel):
    """Governed substance/UNII/CAS identity mapping: a raw ingredient
    identity string (as it appears in an FDA IID/Orange Book row) proposed
    against a canonical IIDIngredient, UNII, and/or CAS number. No fuzzy
    candidate becomes approved automatically -- only an explicit reviewer
    decision moves a row through PROPOSED -> UNDER_REVIEW -> APPROVED (or
    REJECTED / RETURNED). Only an APPROVED, is_current row may be used by
    the IID matching engine to resolve ingredient identity; every other
    status fails closed to REVIEW_REQUIRED/INGREDIENT_AMBIGUOUS.

    release is nullable: a null release means this mapping is scoped as an
    explicit platform-master synonym (not tied to one release's raw rows).
    release uses PROTECT, not CASCADE, so a release with approved mapping
    history can never be silently deleted out from under it."""

    release = models.ForeignKey(
        FDADataSourceRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="substance_synonym_mappings",
    )
    source_dataset = models.CharField(max_length=40, choices=FDADatasetType.choices)

    # Raw source identity -- immutable once created (see clean()). Never
    # rewritten in place even when a correction is needed.
    raw_ingredient_name = models.CharField(max_length=500)
    normalized_ingredient_name = models.CharField(max_length=500, db_index=True)
    raw_unii = models.CharField(max_length=20, blank=True, db_index=True)
    raw_cas_number = models.CharField(max_length=50, blank=True, db_index=True)
    source_row_locator = models.CharField(max_length=255, blank=True)

    # Proposed resolution -- never applied until approved.
    proposed_ingredient = models.ForeignKey(
        IIDIngredient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_synonym_mappings",
    )
    proposed_unii = models.CharField(max_length=20, blank=True)
    proposed_cas_number = models.CharField(max_length=50, blank=True)

    mapping_method = models.CharField(max_length=20, choices=SubstanceMappingMethod.choices)
    evidence_classification = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20,
        choices=SubstanceMappingStatus.choices,
        default=SubstanceMappingStatus.PROPOSED,
        db_index=True,
    )
    is_current = models.BooleanField(default=True)

    # reviewer/reviewed_at record who moved this mapping into review (the
    # submit-review actor) -- never overwritten by a later approve/reject/
    # return action, so the actual reviewer's identity survives the whole
    # lifecycle (see docs/HUMAN_REVIEW_PR5_REMEDIATION.md, HR-03).
    reviewer = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    review_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["release"]),
            models.Index(fields=["normalized_ingredient_name"]),
            models.Index(fields=["raw_unii"]),
            models.Index(fields=["raw_cas_number"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "raw_ingredient_name", "release"],
                condition=models.Q(is_current=True),
                name="unique_current_substance_mapping_per_release_raw_identity",
            ),
        ]

    def __str__(self):
        return f"{self.raw_ingredient_name} -> {self.proposed_ingredient} ({self.status})"

    def clean(self):
        if self.pk:
            original = SubstanceSynonymMapping.objects.filter(pk=self.pk).first()
            if original is None:
                return
            immutable_raw_fields = {
                "release_id",
                "source_dataset",
                "raw_ingredient_name",
                "normalized_ingredient_name",
                "raw_unii",
                "raw_cas_number",
                "source_row_locator",
            }
            changed_raw = {
                f for f in immutable_raw_fields if getattr(original, f) != getattr(self, f)
            }
            if changed_raw:
                raise ValidationError(
                    f"SubstanceSynonymMapping {self.pk} raw source identity is immutable; "
                    f"cannot change {sorted(changed_raw)}. Propose a new mapping instead."
                )
            if original.status == SubstanceMappingStatus.APPROVED:
                mutable_once_approved = {"is_current", "updated_at"}
                changed_fields = {
                    f.name
                    for f in self._meta.fields
                    if f.name not in mutable_once_approved
                    and getattr(original, f.name) != getattr(self, f.name)
                }
                if changed_fields:
                    raise ValidationError(
                        f"SubstanceSynonymMapping {self.pk} is approved and immutable; "
                        f"cannot change {sorted(changed_fields)}. Propose a new mapping instead."
                    )
