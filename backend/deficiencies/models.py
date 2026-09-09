"""FDA deficiency reference corpus.

Ported from the legacy iPharmaAI monolith, where it lived as two structurally
identical models -- `AIDatabase.ANDA` (6,306 rows) and `AIDatabase.MajorCR`
(1,152 rows). Both carried the same five classification columns and one rich-text
body, differing only in which roadmap the row came from. They are unified here as
one model with a `corpus` discriminator rather than reproducing the duplication.

**Not tenant-scoped, deliberately.** This is published FDA reference material, the
same category as `fda_data.FDADataSourceRelease`, which is likewise platform-level.
Every tenant reads the same corpus; a tenant cannot own or edit a deficiency
precedent. Tenant-specific interpretation belongs on whatever cites a row, not on
the row.

The legacy `main_cateogry` spelling is corrected to `main_category` here; the
importer maps it.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class DeficiencyCorpus(models.TextChoices):
    """Which FDA roadmap a record was published in."""

    ANDA = "anda", "ANDA Deficiency Roadmap"
    MAJOR_CR = "major_cr", "Major CR Roadmap"


class DeficiencyRecord(PublicIDModel, TimeStampedModel):
    """One published deficiency precedent.

    Classification is stored as free text rather than foreign keys. The legacy
    source is uncontrolled vocabulary -- 80+ distinct `cmc_section` spellings
    including near-duplicates that differ only by whitespace or bracket style --
    and normalising it is a data-governance exercise with an approval trail, not
    something to do silently during a port. `fda_data.RouteMapping` and its
    siblings are the sanctioned mechanism when that work happens.
    """

    corpus = models.CharField(max_length=20, choices=DeficiencyCorpus.choices, db_index=True)
    main_category = models.CharField(max_length=500, db_index=True)
    dosage_form = models.CharField(max_length=500, db_index=True)
    cmc_section = models.CharField(max_length=500, db_index=True)
    deficiency_type = models.CharField(max_length=500, blank=True)
    category_of_deficiency = models.CharField(max_length=500, blank=True)

    #: Rich text in the source. Stored as TextField: the legacy CKEditor field
    #: added an editor widget, not a column type, and REGX renders in React.
    deficiency = models.TextField(blank=True)

    #: Provenance. Which import produced this row, so a corpus can be traced to a
    #: source file and superseded wholesale when a newer roadmap is published.
    source_release = models.ForeignKey(
        "fda_data.FDADataSourceRelease",
        on_delete=models.PROTECT,
        related_name="deficiency_records",
        null=True,
        blank=True,
    )
    source_row_number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["corpus", "main_category", "cmc_section", "id"]
        indexes = [
            models.Index(fields=["corpus", "main_category"]),
            models.Index(fields=["corpus", "dosage_form"]),
        ]

    def __str__(self):
        return f"[{self.get_corpus_display()}] {self.main_category} / {self.cmc_section}"
