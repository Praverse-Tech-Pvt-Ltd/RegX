import os
from datetime import datetime
from django.db import models
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from ckeditor.fields import RichTextField
from AdminMaster.models import *
from django.core.exceptions import ValidationError
from docx import Document
from PyPDF2 import PdfReader
# Create your models here.

# 483 Database Model here
class Form483Master(models.Model):
    company_name = models.CharField(max_length=200, null=True, blank=True)
    city = models.CharField(max_length=200, null=True, blank=True)
    state = models.CharField(max_length=200, null=True, blank=True)
    type_of_establishment = models.CharField(max_length=200, null=True, blank=True)
    date_of_inspection = models.DateField(null=True,blank=True)
    investigator_name = models.CharField(max_length=200, null=True, blank=True)
    year_of_inspection = models.CharField(max_length=10, null=True, blank=True)

class Form483System(models.Model):
    master = models.ForeignKey(Form483Master, on_delete=models.CASCADE)
    system = models.CharField(max_length=200, null=True, blank=True)

class Form483Observation(models.Model):
    system = models.ForeignKey(Form483System, on_delete=models.CASCADE)
    observation_number = models.IntegerField()

class Form483ObeservationContent(models.Model):
    observation = models.ForeignKey(Form483Observation, on_delete=models.CASCADE)
    content_category = models.CharField(max_length=4)
    content = RichTextField()
    image = models.ImageField()

# ANDA Database Model here
class ANDA(models.Model):
    MAIN_CATEGORY = (
        ('Nasal Spray-Deficiency', 'Nasal Spray-Deficiency'),
        ('Liquid Oral-Deficiency', 'Liquid Oral-Deficiency'),
        ('IUD-Deficiency', 'IUD-Deficiency'),
        ('TDDS-Deficiency', 'TDDS-Deficiency'),
        ('Suppository-Deficiency', 'Suppository-Deficiency'),
        ('Topicals-Deficiency', 'Topicals-Deficiency'),
        ('Solid Oral-Deficiency', 'Solid Oral-Deficiency'),
        ('Otic - Deficiency', 'Otic - Deficiency'),
        (' Ophthalmic - Deficiency', ' Ophthalmic - Deficiency'),
        ('Injectable - Peptide Deficiency', 'Injectable - Peptide Deficiency'),
        ('Injectable - General Deficiency', 'Injectable - General Deficiency'),
    )
    main_cateogry = models.CharField(max_length=1000, choices=MAIN_CATEGORY)
    dosage_form = models.CharField(max_length=1000)
    cmc_section = models.CharField(max_length=1000)
    deficiency_type = models.CharField(max_length=1000)
    category_of_deficiency = models.CharField(max_length=1000)
    deficiency = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.main_cateogry + ' - ' + self.dosage_form + ' - ' + self.cmc_section + ' - ' + self.deficiency_type + ' - ' + self.category_of_deficiency

        # This model is sub type of ANDA with differenct columns

class ANDAeCTD(models.Model):
    dosage = models.CharField(max_length=1000)
    cmc_clinic = models.CharField(max_length=1000)
    deficiency_type = models.CharField(max_length=1000)
    deficiency = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.dosage + ' - ' + self.cmc_clinic + ' - ' + self.deficiency_type


        # This model is sub type of ANDA with differenct columns
class ANDATechnicalAcceptance(models.Model):
    dosage_form = models.CharField(max_length=1000)
    type_of_dosage_form = models.CharField(max_length=1000)
    deficiency_type = models.CharField(max_length=1000)
    deficiency = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.dosage_form + ' - ' + self.type_of_dosage_form + ' - ' + self.deficiency_type

# Major CR Database Model here
class MajorCR(models.Model):
    MAIN_CATEGORY = (
        ('Nasal Spray-Deficiency', 'Nasal Spray-Deficiency'),
        ('Liquid Oral-Deficiency', 'Liquid Oral-Deficiency'),
        ('IUD-Deficiency', 'IUD-Deficiency'),
        ('TDDS-Deficiency', 'TDDS-Deficiency'),
        ('Suppository-Deficiency', 'Suppository-Deficiency'),
        ('Topicals-Deficiency', 'Topicals-Deficiency'),
        ('Solid Oral-Deficiency', 'Solid Oral-Deficiency'),
        ('Otic - Deficiency', 'Otic - Deficiency'),
        (' Ophthalmic - Deficiency', ' Ophthalmic - Deficiency'),
        ('Injectable - Peptide Deficiency', 'Injectable - Peptide Deficiency'),
        ('Injectable - General Deficiency', 'Injectable - General Deficiency'),
    )
    main_cateogry = models.CharField(max_length=1000, choices=MAIN_CATEGORY)
    dosage_form = models.CharField(max_length=1000)
    cmc_section = models.CharField(max_length=1000)
    deficiency_type = models.CharField(max_length=1000)
    category_of_deficiency = models.CharField(max_length=1000)
    deficiency = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.main_cateogry + ' - ' + self.dosage_form + ' - ' + self.cmc_section + ' - ' + self.deficiency_type + ' - ' + self.category_of_deficiency



class WarningLetter(models.Model):
    company_name = models.CharField(max_length=2000,blank=True, null=True)
    recipient_name = models.CharField(max_length=2000,blank=True, null=True)
    date_of_issue = models.DateField(blank=True, null=True)
    location = models.CharField(max_length=2000,blank=True, null=True)
    city_state = models.CharField(max_length=2000,blank=True, null=True)
    country = models.CharField(max_length=2000,blank=True, null=True)
    date_of_inspection = models.DateField(blank=True, null=True)
    investigator_names = models.CharField(max_length=2000,blank=True, null=True)

    ai_summary = RichTextField(blank=True, null=True)
    warning_letter = RichTextField(blank=True, null=True)



def observation_image_upload_path(instance, filename):
    """
    Save the uploaded file EXACTLY as instance.image_name
    """
    return f"new_observation_images/{instance.image_name}"


class ExactNameFileSystemStorage(FileSystemStorage):
    """
    Storage backend that keeps filenames intact and overwrites existing files instead
    of generating Django's default suffixes.
    """

    def get_valid_name(self, name):
        return name

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            self.delete(name)
        return name


_default_base_url = (settings.MEDIA_URL or "/media/").rstrip("/") + "/"
observation_image_storage = ExactNameFileSystemStorage(
    location=settings.MEDIA_ROOT,
    base_url=_default_base_url,
)




OBSERVATION_IMAGE_ALLOW_FILE_UPDATE = getattr(
    settings,
    "OBSERVATION_IMAGE_ALLOW_FILE_UPDATE",
    False,
)

OBSERVATION_IMAGE_ALLOW_RECORD_UPDATE = getattr(
    settings,
    "OBSERVATION_IMAGE_ALLOW_RECORD_UPDATE",
    False,
)


class ObservationImage(models.Model):
    image_name = models.CharField(max_length=255,unique=True,db_index=True,help_text="Exact filename used in Excel <img:filename>")
    image = models.ImageField(upload_to=observation_image_upload_path, storage=observation_image_storage)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True, editable=False)

    def _debug_log(self, stage, note=None):
        """
        Emit verbose logs to trace when Django attempts to rename image files.
        """
        field_file = getattr(self, "image", None)
        stored_name = None
        committed = None
        if field_file:
            stored_name = os.path.basename(field_file.name)
            committed = getattr(field_file, "_committed", None)

        msg = (
            f"[OBSERVATION_IMAGE][{stage}] "
            f"pk={self.pk} image_name={self.image_name!r} file_field={stored_name!r} committed={committed}"
        )
        if note:
            msg += f" | {note}"
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "backslashreplace").decode("ascii"))

    def clean(self):
        from django.core.exceptions import ValidationError
        import os

        # ?? Prevent updates to locked rows unless override flag is enabled
        if self.pk and not OBSERVATION_IMAGE_ALLOW_RECORD_UPDATE:
            if self._is_locked_in_db():
                self._debug_log("clean-locked", "Record is locked; updates disabled.")
                raise ValidationError({
                    "__all__": (
                        "Observation images are locked after creation. ",
                        "Set OBSERVATION_IMAGE_ALLOW_RECORD_UPDATE=True to allow updates."
                    )
                })

        # 1️⃣ Image must be present
        if not self.image:
            raise ValidationError({"image": "Image file is required."})

        # 2️⃣ Uploaded filename must match image_name
        uploaded_name = os.path.basename(self.image.name)
        self._debug_log("clean", f"uploaded_name={uploaded_name!r}")
        if uploaded_name != self.image_name:
            if self.pk:
                self._debug_log("clean-mismatch-existing", "Detected filename mismatch on update attempt.")
            raise ValidationError({
                "image": f"Uploaded filename must match image_name exactly ({self.image_name})."
            })

        # 3️⃣ BLOCK ONLY duplicate DB records (NOT file existence)
        if ObservationImage.objects.filter(
            image_name=self.image_name
        ).exclude(pk=self.pk).exists():
            raise ValidationError({
                "image_name": "An entry with this image_name already exists."
            })

        if self._should_skip_file_update():
            self._debug_log("skip-update-clean")
            raise ValidationError({
                "image": (
                    "Updating an existing observation image file is disabled. "
                    "Set OBSERVATION_IMAGE_ALLOW_FILE_UPDATE=True if you need to replace the file."
                )
            })

    def _should_skip_file_update(self):
        """
        Detect if a new file upload is pending for an existing record.
        When OBSERVATION_IMAGE_ALLOW_FILE_UPDATE is False (default), we skip the
        update to avoid Django's auto-renaming behaviour and keep filenames in sync
        with Excel tags.
        """
        if OBSERVATION_IMAGE_ALLOW_FILE_UPDATE:
            return False

        if not self.pk:
            return False

        field_file = getattr(self, "image", None)
        if not field_file:
            return False

        return not getattr(field_file, "_committed", True)

    def _is_locked_in_db(self):
        if not self.pk:
            return False
        return ObservationImage.objects.filter(pk=self.pk, is_locked=True).exists()

    def save(self, *args, **kwargs):
        self._debug_log("pre-save")
        if self.pk and not OBSERVATION_IMAGE_ALLOW_RECORD_UPDATE and self._is_locked_in_db():
            self._debug_log("skip-locked-save", "Record is locked; skipping save.")
            return

        if self._should_skip_file_update():
            self._debug_log("skip-update")
            original_path = ObservationImage.objects.filter(pk=self.pk).values_list("image", flat=True).first()
            if original_path:
                # Revert to previously stored path; do not persist the newly uploaded file.
                self.image = original_path
                print(
                    f"[OBSERVATION_IMAGE] Skipped file update for '{self.image_name}'. "
                    "Set OBSERVATION_IMAGE_ALLOW_FILE_UPDATE=True to allow overwrites."
                )

        self.full_clean()  # run validations
        super().save(*args, **kwargs)
        if not self.is_locked:
            ObservationImage.objects.filter(pk=self.pk).update(is_locked=True)
        self._debug_log("post-save")

    def __str__(self):
        return self.image_name

    @property
    def image_url(self):
        return self.image.url

def warning_letter_pdf_upload_path(instance, filename):
    """
    Save the uploaded file EXACTLY as instance.pdf_name
    """
    return f"warning_letter_pdfs/{instance.pdf_name}"


warning_letter_pdf_storage = ExactNameFileSystemStorage(
    location=settings.MEDIA_ROOT,
    base_url=_default_base_url,
)


WARNING_LETTER_PDF_ALLOW_FILE_UPDATE = getattr(
    settings,
    "WARNING_LETTER_PDF_ALLOW_FILE_UPDATE",
    False,
)

WARNING_LETTER_PDF_ALLOW_RECORD_UPDATE = getattr(
    settings,
    "WARNING_LETTER_PDF_ALLOW_RECORD_UPDATE",
    False,
)


class WarningLetterPdf(models.Model):
    pdf_name = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Exact PDF filename used in Excel (e.g. Company - Month DD, YYYY.pdf)",
    )
    pdf_file = models.FileField(
        upload_to=warning_letter_pdf_upload_path,
        storage=warning_letter_pdf_storage,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True, editable=False)

    def _debug_log(self, stage, note=None):
        if not getattr(settings, "WARNING_LETTER_PDF_DEBUG_LOG", False):
            return

        field_file = getattr(self, "pdf_file", None)
        stored_name = None
        committed = None
        if field_file:
            stored_name = os.path.basename(field_file.name)
            committed = getattr(field_file, "_committed", None)

        msg = (
            f"[WARNING_LETTER_PDF][{stage}] "
            f"pk={self.pk} pdf_name={self.pdf_name!r} file_field={stored_name!r} committed={committed}"
        )
        if note:
            msg += f" | {note}"
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "backslashreplace").decode("ascii"))

    def clean(self):
        # Prevent updates to locked rows unless override flag is enabled
        if self.pk and not WARNING_LETTER_PDF_ALLOW_RECORD_UPDATE:
            if self._is_locked_in_db():
                self._debug_log("clean-locked", "Record is locked; updates disabled.")
                raise ValidationError({
                    "__all__": (
                        "Warning letter PDFs are locked after creation. ",
                        "Set WARNING_LETTER_PDF_ALLOW_RECORD_UPDATE=True to allow updates.",
                    )
                })

        # 1) PDF must be present
        if not self.pdf_file:
            raise ValidationError({"pdf_file": "PDF file is required."})

        # 2) Uploaded filename must match pdf_name
        uploaded_name = os.path.basename(self.pdf_file.name)
        self._debug_log("clean", f"uploaded_name={uploaded_name!r}")
        if uploaded_name != self.pdf_name:
            if self.pk:
                self._debug_log("clean-mismatch-existing", "Detected filename mismatch on update attempt.")
            raise ValidationError({
                "pdf_file": f"Uploaded filename must match pdf_name exactly ({self.pdf_name})."
            })

        # 3) Block duplicate DB records (not file existence)
        if WarningLetterPdf.objects.filter(
            pdf_name=self.pdf_name
        ).exclude(pk=self.pk).exists():
            raise ValidationError({
                "pdf_name": "An entry with this pdf_name already exists."
            })

        if self._should_skip_file_update():
            self._debug_log("skip-update-clean")
            raise ValidationError({
                "pdf_file": (
                    "Updating an existing warning letter PDF file is disabled. "
                    "Set WARNING_LETTER_PDF_ALLOW_FILE_UPDATE=True if you need to replace the file."
                )
            })

    def _should_skip_file_update(self):
        if WARNING_LETTER_PDF_ALLOW_FILE_UPDATE:
            return False

        if not self.pk:
            return False

        field_file = getattr(self, "pdf_file", None)
        if not field_file:
            return False

        return not getattr(field_file, "_committed", True)

    def _is_locked_in_db(self):
        if not self.pk:
            return False
        return WarningLetterPdf.objects.filter(pk=self.pk, is_locked=True).exists()

    def save(self, *args, **kwargs):
        self._debug_log("pre-save")
        if self.pk and not WARNING_LETTER_PDF_ALLOW_RECORD_UPDATE and self._is_locked_in_db():
            self._debug_log("skip-locked-save", "Record is locked; skipping save.")
            return

        if self._should_skip_file_update():
            self._debug_log("skip-update")
            original_path = WarningLetterPdf.objects.filter(pk=self.pk).values_list("pdf_file", flat=True).first()
            if original_path:
                self.pdf_file = original_path
                print(
                    f"[WARNING_LETTER_PDF] Skipped file update for '{self.pdf_name}'. "
                    "Set WARNING_LETTER_PDF_ALLOW_FILE_UPDATE=True to allow overwrites."
                )

        self.full_clean()
        super().save(*args, **kwargs)
        if not self.is_locked:
            WarningLetterPdf.objects.filter(pk=self.pk).update(is_locked=True)
        self._debug_log("post-save")

    def __str__(self):
        return self.pdf_name

    @property
    def pdf_url(self):
        return self.pdf_file.url

class ObservationImageExcelMaster(models.Model):
    file = models.FileField(upload_to="excel_files/")
    display_name = models.CharField(max_length=255, help_text="Human readable name of file")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Only ONE file can be active (used by system)
    is_active = models.BooleanField(default=False)
    excel_processing_flag = models.BooleanField(
        default=False,
        help_text="True after the background Excel processing finishes successfully.",
    )

    def save(self, *args, **kwargs):
        # Ensure only ONE active file
        if self.is_active:
            ObservationImageExcelMaster.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name

class WarningLetterExcelMaster(models.Model):
    file = models.FileField(upload_to="excel_files/")
    display_name = models.CharField(max_length=255, help_text="Human readable name of file")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Only ONE file can be active (used by system)
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Ensure only ONE active file
        if self.is_active:
            WarningLetterExcelMaster.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name


class Form483ExcelNewData(models.Model):
    reload_batch_id = models.CharField(max_length=64, db_index=True)
    source_excel_path = models.TextField(blank=True, null=True)

    sr_no = models.CharField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=500, blank=True, null=True)
    organization_name = models.CharField(max_length=500, blank=True, null=True)
    fei_number = models.CharField(max_length=100, blank=True, null=True)
    city_country = models.CharField(max_length=500, blank=True, null=True)
    type_of_establishment = models.CharField(max_length=300, blank=True, null=True)
    month_of_inspection = models.CharField(max_length=100, blank=True, null=True)
    investigator_name = models.CharField(max_length=500, blank=True, null=True)
    year_of_inspection = models.CharField(max_length=50, blank=True, null=True)
    system = models.CharField(max_length=300, blank=True, null=True)
    form_483_observation = models.CharField(max_length=100, blank=True, null=True)
    observation_details = models.TextField(blank=True, null=True)

    row_fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    raw_row = models.JSONField(blank=True, null=True)
    detected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name or 'Unknown'} ({self.year_of_inspection or '-'})"


class WarningLetterExcelNewData(models.Model):
    reload_batch_id = models.CharField(max_length=64, db_index=True)
    source_excel_path = models.TextField(blank=True, null=True)

    company_name = models.CharField(max_length=500, blank=True, null=True)
    letter_issue_date = models.CharField(max_length=100, blank=True, null=True)
    year = models.CharField(max_length=50, blank=True, null=True)
    issuing_office = models.CharField(max_length=300, blank=True, null=True)
    subject = models.TextField(blank=True, null=True)
    filename = models.CharField(max_length=500, blank=True, null=True)

    row_fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    raw_row = models.JSONField(blank=True, null=True)
    detected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name or 'Unknown'} ({self.letter_issue_date or '-'})"

class UserCheckedUpdate(models.Model):
    user = models.OneToOneField(CustomUser,on_delete=models.CASCADE,related_name='checked_update_flag')
    checked_updates = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.checked_updates}"

# class Announcement(models.Model):
#     title = models.CharField(max_length=255)
#     content = RichTextField()
#     till_date = models.DateField()
#     created_at = models.DateTimeField(auto_now_add=True)
#     active = models.BooleanField(default=True)

#     def __str__(self):
#         return self.title


class SystemChecklist(models.Model):
    SYSTEM_CHOICES = [
        ("Quality System", "Quality System"),
        ("Facilities & Equipment System", "Facilities & Equipment System"),
        ("Materials System", "Materials System"),
        ("Production System", "Production System"),
        ("Packaging & Labeling System", "Packaging & Labeling System"),
        ("Laboratory Control System", "Laboratory Control System"),
    ]

    FILE_TYPE_CHOICES = [
        ("pdf", "PDF"),
        ("doc", "Word"),
    ]

    # System Info
    system_name = models.CharField(max_length=100, choices=SYSTEM_CHOICES)
    description = models.TextField(max_length=500)
    icon = models.ImageField(upload_to="system_icons/", null=True, blank=True)

    # File Info
    file = models.FileField(upload_to="checklists/")
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    version = models.CharField(max_length=20, default="v1")
    uploaded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    page_len = models.IntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # First save → ensures file is stored
        super().save(*args, **kwargs)

        if self.file:
            try:
                file_path = os.path.join(settings.MEDIA_ROOT, str(self.file))

                if self.file_type == "pdf":
                    reader = PdfReader(file_path)
                    page_len = len(reader.pages)

                elif self.file_type == "doc":
                    doc = Document(file_path)
                    word_count = sum(len(p.text.split()) for p in doc.paragraphs)
                    page_len = max(1, word_count // 250)

                else:
                    page_len = 0

                # Update only if changed (prevents loop)
                if self.page_len != page_len:
                    self.page_len = page_len
                    super().save(update_fields=["page_len"])

            except Exception as e:
                print("Page count error:", e)
                self.page_len = 0
                super().save(update_fields=["page_len"])

    def file_name(self):
        return f"{self.system_name}_Checklist_{self.version}.{self.file_type}"

    def __str__(self):
        return f"{self.system_name} - {self.file_type} - {self.version}"
class GMPCExcelMaster(models.Model):
    file = models.FileField(upload_to="excel_files/")
    active_excel_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, help_text="Human readable name.")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    excel_processing_flag = models.BooleanField(
        default=False,
        help_text="True after background Excel processing finishes successfully.",
    )
    dashboard_metrics = models.JSONField(
        blank=True,
        null=True,
        help_text="Cached dashboard metrics and comparison results",
    )

    def save(self, *args, **kwargs):
        active_excel_name_value = (self.active_excel_name or "").strip()
        self.active_excel_name = active_excel_name_value or None
        if self.is_active:
            active_queryset = GMPCExcelMaster.objects.exclude(pk=self.pk).filter(is_active=True)
            if active_excel_name_value:
                active_queryset = active_queryset.filter(active_excel_name__iexact=active_excel_name_value)
            else:
                active_queryset = active_queryset.filter(
                    models.Q(active_excel_name__isnull=True) | models.Q(active_excel_name__exact="")
                )
            active_queryset.update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.display_name:
            return f"{self.active_excel_name} - {self.display_name}"
        return f"{self.active_excel_name}"

class GMPCExcelFilter(models.Model):
    gmpc_excel_master = models.OneToOneField(GMPCExcelMaster,on_delete=models.CASCADE,related_name="filters")
    dynamic_filter = models.JSONField(default=list, blank=True)
    static_filter = models.JSONField(default=dict, blank=True)
    title_field_name = models.CharField(max_length=255, blank=True, null=True)
    layout_config = models.JSONField(default=dict, blank=True)
    key_url = models.CharField(max_length=2000, blank=True, null=True)
    url_type = models.CharField(max_length=50,choices=[("simple", "Simple"),("mhra", "MHRA Format"),],default="simple")
    key_field_name = models.CharField(max_length=255, blank=True, null=True)
    combined_fields = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Filters for {self.gmpc_excel_master.active_excel_name}"


class InvestigatorThemedKeywords(models.Model):
    system_name = models.CharField(max_length=100,choices=SystemChecklist.SYSTEM_CHOICES)
    keyword = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.system_name} - {self.keyword}"
