"""FDA inspection outcome corpus: Form 483 observations and Warning Letters.

Ported from the legacy iPharmaAI monolith (`AIDatabase.Form483*`,
`AIDatabase.WarningLetter`).

**Not tenant-scoped**, for the same reason as `deficiencies`: these are published
FDA records. Every tenant reads the same corpus and none can edit it. See
`fda_data.FDADataSourceRelease`, which is likewise platform-level.

**What was deliberately not ported.** The legacy app did not serve this data from
its own tables. It read an .xlsx into a module-level pandas DataFrame, cached it
in-process, persisted `.pkl` snapshots, and rebuilt on a file-signature change --
so the "database" was really a spreadsheet and the models were a partial mirror.
That design cannot survive more than one gunicorn worker: each holds its own copy,
they diverge, and nothing reconciles them. Here the tables are the source of
truth and the spreadsheet is only an import format.
"""

from django.db import models

from common.models import PublicIDModel, TimeStampedModel


class Form483Inspection(PublicIDModel, TimeStampedModel):
    """One FDA Form 483 issued to one site after one inspection."""

    company_name = models.CharField(max_length=500, db_index=True)
    city = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=255, blank=True)
    type_of_establishment = models.CharField(max_length=255, blank=True, db_index=True)

    #: The legacy schema stored the year separately as a CharField alongside the
    #: date, which allowed the two to disagree. Year is derived here instead.
    date_of_inspection = models.DateField(null=True, blank=True, db_index=True)
    investigator_name = models.CharField(max_length=500, blank=True, db_index=True)

    source_release = models.ForeignKey(
        "fda_data.FDADataSourceRelease",
        on_delete=models.PROTECT,
        related_name="form483_inspections",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-date_of_inspection", "company_name", "id"]
        indexes = [models.Index(fields=["company_name", "date_of_inspection"])]

    @property
    def year_of_inspection(self):
        return self.date_of_inspection.year if self.date_of_inspection else None

    def __str__(self):
        return f"{self.company_name} ({self.year_of_inspection or 'undated'})"


class Form483System(PublicIDModel, TimeStampedModel):
    """A quality system cited within an inspection (Quality, Production, ...)."""

    inspection = models.ForeignKey(
        Form483Inspection, on_delete=models.CASCADE, related_name="systems"
    )
    system = models.CharField(max_length=255, db_index=True)

    class Meta:
        ordering = ["inspection_id", "system"]

    def __str__(self):
        return self.system


class Form483Observation(PublicIDModel, TimeStampedModel):
    """A numbered observation under a system."""

    system = models.ForeignKey(Form483System, on_delete=models.CASCADE, related_name="observations")
    observation_number = models.PositiveIntegerField()

    #: Narrative text. Held on the observation rather than in a separate content
    #: table: the legacy split existed to let one observation carry several
    #: paragraph rows, and the reader always concatenated them back together.
    content = models.TextField(blank=True)

    #: LLM-generated abstract, populated by a separate pipeline. Nullable and
    #: never required -- an observation without one is complete, just unsummarised.
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ["system_id", "observation_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "observation_number"],
                name="uniq_observation_number_per_system",
            )
        ]

    def __str__(self):
        return f"Observation {self.observation_number}"


class WarningLetter(PublicIDModel, TimeStampedModel):
    """An FDA Warning Letter."""

    company_name = models.CharField(max_length=500, db_index=True)
    recipient_name = models.CharField(max_length=500, blank=True)
    date_of_issue = models.DateField(null=True, blank=True, db_index=True)
    location = models.CharField(max_length=500, blank=True)
    city_state = models.CharField(max_length=500, blank=True)
    country = models.CharField(max_length=255, blank=True, db_index=True)
    date_of_inspection = models.DateField(null=True, blank=True)
    investigator_names = models.CharField(max_length=1000, blank=True)

    body = models.TextField(blank=True)
    summary = models.TextField(blank=True)

    source_release = models.ForeignKey(
        "fda_data.FDADataSourceRelease",
        on_delete=models.PROTECT,
        related_name="warning_letters",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-date_of_issue", "company_name", "id"]
        indexes = [models.Index(fields=["company_name", "date_of_issue"])]

    def __str__(self):
        return f"{self.company_name} ({self.date_of_issue or 'undated'})"
