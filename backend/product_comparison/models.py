"""Physical product comparison: RLD versus the company's product.

Ported from the legacy iPharmaAI monolith (`RATools.ProductComparison`,
`TabletComparison`, `CapsuleComparison`).

**Normalised on the way across.** The legacy design was a wide table per dosage
form: `TabletComparison` carried 49 columns and `CapsuleComparison` 33, being the
same twelve (or eight) physical attributes repeated with four suffixes -- `_trld`,
`_tcompany`, `_tdiff`, `_tfda` -- one per source. Adding an attribute meant four
new columns and a migration; adding a dosage form meant a new table and a new set
of views. Here an attribute is a row, so both problems disappear and tablet and
capsule share one model.

**The legacy approval columns are not ported.** `ProductComparison` carried
`approved_by_checkers_level_1..7` and a `statues` JSON blob, which is the legacy
seven-level checker workflow. REGX supersedes that with the `workflows` app;
a comparison that needs review links to a `WorkflowItem` rather than growing
seven more columns.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class ProductType(models.TextChoices):
    TABLET = "tablet", "Tablet"
    CAPSULE = "capsule", "Capsule"


class AttributeSource(models.TextChoices):
    """Who or what the value came from.

    The legacy suffixes map directly: `_trld` -> RLD, `_tcompany` -> COMPANY,
    `_tdiff` -> DIFFERENCE, `_tfda` -> FDA_LIMIT.
    """

    RLD = "rld", "Reference Listed Drug"
    COMPANY = "company", "Company Product"
    DIFFERENCE = "difference", "Difference"
    FDA_LIMIT = "fda_limit", "FDA Limit"


#: The attributes the legacy tablet and capsule tables carried, as a controlled
#: vocabulary rather than column names. Storing the key rather than a foreign key
#: keeps a comparison readable without a join and lets a tenant record an
#: attribute this list does not yet name.
TABLET_ATTRIBUTES = [
    "shape",
    "color",
    "scoring",
    "score_depth",
    "avg_thickness",
    "avg_width",
    "avg_length",
    "largest_dimension",
    "volume",
    "surface_area",
    "cross_sectional_area",
    "picture",
]
CAPSULE_ATTRIBUTES = [
    "shape",
    "color",
    "size",
    "length",
    "external_diameter",
    "volume",
    "surface_area",
    "picture",
]


class ProductComparison(PublicIDModel, TimeStampedModel):
    """One comparison of a company product against its RLD.

    Tenant-scoped: unlike the FDA reference corpora, this is a tenant's own work
    product.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="product_comparisons"
    )
    product_type = models.CharField(max_length=20, choices=ProductType.choices)
    rld_product_name = models.CharField(max_length=255)
    company_product_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["tenant", "product_type"])]

    @property
    def known_attributes(self):
        return TABLET_ATTRIBUTES if self.product_type == ProductType.TABLET else CAPSULE_ATTRIBUTES

    def __str__(self):
        return f"{self.rld_product_name} vs {self.company_product_name or 'company product'}"


class ComparisonAttribute(PublicIDModel, TimeStampedModel):
    """One measured attribute from one source.

    Values are text. The legacy columns were `CharField` throughout -- shape and
    colour are not numeric, and thickness was recorded with its unit inline -- so
    typing them numerically here would reject data the source already holds.
    """

    comparison = models.ForeignKey(
        ProductComparison, on_delete=models.CASCADE, related_name="attributes"
    )
    attribute = models.CharField(max_length=100, db_index=True)
    source = models.CharField(max_length=20, choices=AttributeSource.choices)
    value = models.TextField(blank=True)

    #: Set when the attribute is an image (the legacy `picture_*` FileFields).
    #: Points at a `documents.Document` public_id rather than holding a path, so
    #: uploads go through the documents app and inherit its scanning and
    #: versioning instead of writing loose files into MEDIA_ROOT.
    document_reference = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["comparison_id", "attribute", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["comparison", "attribute", "source"],
                name="uniq_attribute_source_per_comparison",
            )
        ]

    def __str__(self):
        return f"{self.attribute} ({self.get_source_display()})"
