"""Controlled Correspondence: FDA best-practice guidance and letter drafts.

Ported from the legacy iPharmaAI monolith (`RATools.CCBestPractice`,
`RATools.CCTemplate`).

The two halves have different ownership and are scoped accordingly:

* `BestPractice` is published guidance -- the same category/sub-category/question
  set for everyone. Platform-level, like `deficiencies` and `inspections`.
* `CorrespondenceDraft` is a tenant's own draft letter. Tenant-scoped, and the
  only writable model in this app.

That distinction was not expressible in the legacy app, which had no tenant
concept and simply hung the template off a user.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class BestPractice(PublicIDModel, TimeStampedModel):
    """One published best-practice entry, grouped by category."""

    category = models.CharField(max_length=255, db_index=True)
    sub_category = models.CharField(max_length=255, blank=True, db_index=True)

    #: Rich text in the source; a plain TextField here, as REGX renders in React
    #: and the legacy CKEditor field only added a Django-admin widget.
    guidance = models.TextField(blank=True)

    class Meta:
        ordering = ["category", "sub_category", "id"]

    def __str__(self):
        return f"{self.category} - {self.sub_category}" if self.sub_category else self.category


class DraftStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    WITHDRAWN = "withdrawn", "Withdrawn"


class CorrespondenceDraft(PublicIDModel, TimeStampedModel):
    """A Controlled Correspondence letter in preparation.

    Field names follow the FDA form rather than the legacy column names, which
    mixed conventions (`brand_name_generic_name`, `us_agent_company_name`).
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="correspondence_drafts"
    )
    status = models.CharField(
        max_length=20, choices=DraftStatus.choices, default=DraftStatus.DRAFT, db_index=True
    )

    # Subject product
    proposed_drug_product_name = models.CharField(max_length=255)
    brand_or_generic_name = models.CharField(max_length=255, blank=True)
    strength = models.CharField(max_length=100, blank=True)

    # Applicants
    anda_applicant_name = models.CharField(max_length=255, blank=True)
    nda_applicant_name = models.CharField(max_length=255, blank=True)
    nda_number = models.CharField(max_length=50, blank=True)

    # Submitting party
    company_name = models.CharField(max_length=255, blank=True)
    responsible_person_name = models.CharField(max_length=255, blank=True)
    designation = models.CharField(max_length=255, blank=True)
    email_address = models.EmailField(blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    mobile = models.CharField(max_length=50, blank=True)
    fax = models.CharField(max_length=50, blank=True)
    us_agent_company_name = models.CharField(max_length=255, blank=True)
    us_regulatory_agent_company_name = models.CharField(max_length=255, blank=True)

    correspondence_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    #: Logo and signature point at `documents.Document` public_ids rather than
    #: holding upload paths. The legacy ImageFields wrote loose files into
    #: MEDIA_ROOT, outside the documents app's scanning and versioning.
    company_logo_document = models.UUIDField(null=True, blank=True)
    signature_document = models.UUIDField(null=True, blank=True)

    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["tenant", "status"])]

    def __str__(self):
        return self.proposed_drug_product_name
