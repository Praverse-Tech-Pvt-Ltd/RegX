from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from ckeditor.fields import RichTextField
from AdminMaster.models import *
import datetime

# ANDA Models Should be below this line
class ANDAReportQuestions(models.Model):
    report_name = models.CharField(max_length=255)
    module_name = models.CharField(max_length=255)
    chapter_name = models.CharField(max_length=255)
    category_name = models.CharField(max_length=100, null=True, blank=True)
    question = RichTextField(null=True, blank=True)

    def __str__(self):
        return f"{self.report_name} ({self.module_name})"

    class Meta:
        verbose_name = "ANDA Report Question"
        verbose_name_plural = "ANDA Report Questions"


class ANDAUserReports(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="created_by"
    )
    report_name = models.ForeignKey(
        ANDAReportQuestions,
        on_delete=models.CASCADE,
        related_name="ANDAReportQuestions",
    )
    product_name = models.CharField(max_length=255)
    # checklist_name = models.CharField(max_length=255)
    is_completed_by_doer = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)

    def __str__(self):
        return f"{self.product_name} -- {self.report_name}"

class ANDAUserAnswers(models.Model):
    ANSWER_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("not_applicable", "Not Applicable"),
    ]
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="CustomUser"
    )
    report_name = models.ForeignKey(
        ANDAUserReports, on_delete=models.CASCADE, related_name="ANDAUserReports"
    )
    report_question = models.ForeignKey(
        ANDAReportQuestions, on_delete=models.CASCADE, default=False
    )
    answer = models.CharField(
        max_length=25, choices=ANSWER_CHOICES, null=True, blank=True
    )


# ANDA Facility Tamplate Models Should be below this line


# Controlled Correspondences Models Should be below this line
class CCBestPractice(models.Model):
    category = models.CharField(max_length=255)
    sub_category = models.CharField(max_length=255,null=True, blank=True)
    question = RichTextField(null=True, blank=True)

    def __str__(self):
        return f"{self.category} -- {self.sub_category}"

class CCTemplate(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    proposed_drug_product_name = models.CharField(max_length=255)
    date = models.DateField(null=True, blank=True)
    anda_applicant_name = models.CharField(max_length=255)
    brand_name_generic_name = models.CharField(max_length=255)
    strength = models.CharField(max_length=100)
    nda_applicant_name = models.CharField(max_length=255)
    nda_number = models.CharField(max_length=50)
    company_logo = models.ImageField(upload_to='logos/', null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    company_name = models.CharField(max_length=255)
    responsible_person_name = models.CharField(max_length=255)
    email_address = models.EmailField()
    telephone = models.CharField(max_length=20)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    fax = models.CharField(max_length=20, blank=True, null=True)
    us_agent_company_name = models.CharField(max_length=255)
    signature = models.ImageField(upload_to='signatures/', null=True, blank=True)
    designation = models.CharField(max_length=255)
    us_regulatory_agent_company_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.proposed_drug_product_name} ({self.anda_applicant_name})"


# DMF Models Should be below this line

class DMFChecklistUser(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    # checklist_name = models.CharField(max_length=100, null=True, blank=True)
    name_of_api = models.CharField(max_length=100, null=True, blank=True)
    name_of_api_vendor = models.CharField(max_length=100, null=True, blank=True)
    dmf_status = models.CharField(max_length=100, null=True, blank=True)
    # 2 new dmf and dmf verstion Add
    dmf = models.CharField(max_length=100, null=True, blank=True)
    dmf_version = models.CharField(max_length=100, null=True, blank=True)
    is_completed_by_doer = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)

class DMFReviewTableQuestion(models.Model):
    module = models.CharField(max_length=100, null=True, blank=True)
    category = models.CharField(max_length=200,null=True, blank=True)
    # sub_category = models.CharField(max_length=200, null=True, blank=True)
    question=RichTextField(null=True,blank=True)

class DMFReviewAnswer(models.Model):
    checklist = models.ForeignKey(DMFChecklistUser, on_delete=models.CASCADE)
    dmf_review = models.ForeignKey(DMFReviewTableQuestion, on_delete=models.CASCADE, related_name="dmf_review_table_ques")
    drf = models.BooleanField(default=False)
    ra = models.BooleanField(default=False)
    ard = models.BooleanField(default=False)

class DMFModuleComment(models.Model):
    checklist = models.ForeignKey(DMFChecklistUser, on_delete=models.CASCADE)
    module = models.CharField(max_length=100, null=True, blank=True)
    comment = models.TextField(null=True,blank=True)
    status = models.CharField(max_length=100,null=True,blank=True)

class DMFCATableQuestion(models.Model):
    module = models.CharField(max_length=100, null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    sub_category = models.CharField(max_length=100, null=True, blank=True)
    ectd_no = models.CharField(max_length=200, null=True, blank=True)
    ectd_sub_category = models.CharField(max_length=200, null=True,blank=True)
    question=RichTextField(null=True,blank=True)
    note = models.TextField(default="",null=True, blank=True)

class DMFCAAnswer(models.Model):
    checklist = models.ForeignKey(DMFChecklistUser, on_delete=models.CASCADE)
    dmf_ca = models.ForeignKey(DMFCATableQuestion, on_delete=models.CASCADE, related_name="dmf_ca_table_ques")
    ANSWER_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("not_applicable", "Not Applicable"),
    ]
    answer = models.CharField(
        max_length=25, choices=ANSWER_CHOICES, null=True, blank=True
    )
    # comment = models.TextField(default="")

# IIG Models Should be below this line

class IIGChecklistUser(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    report = models.CharField(max_length=200)
    # checklist_name = models.CharField(max_length=50, null=True, blank=True)
    product_name = models.CharField(max_length=50, null=True, blank=True)
    is_completed_by_doer = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)

    def __str__(self):
            return f"Object {self.id} -- {self.user} -- ({self.report})"


    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        IIGAnswers.objects.get_or_create(
            checklist_id=self,
        )


class IIGAnswers(models.Model):
    checklist_id = models.ForeignKey(IIGChecklistUser, on_delete=models.CASCADE)
    project_initiation_phase = models.BooleanField(default=False, null=True, blank=True)
    frozen_formulation_phase = models.BooleanField(default=False, null=True, blank=True)
    final_iig_clearance = models.BooleanField(default=False, null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    max_daily_dose_rld = models.CharField(max_length=50, null=True, blank=True, default="")
    max_daily_dose_rs = models.CharField(max_length=50, null=True, blank=True, default="")
    brand_name_rld = models.CharField(max_length=50, null=True, blank=True,default="")
    strength_rld = models.CharField(max_length=50, null=True, blank=True,default="")
    nda_anda_rld = models.CharField(max_length=50, null=True, blank=True,default="")
    brand_name_rs = models.CharField(max_length=50, null=True, blank=True,default="")
    strength_rs = models.CharField(max_length=50, null=True, blank=True,default="")
    nda_anda_rs = models.CharField(max_length=50, null=True, blank=True,default="")
    rld_insert_snapshot = models.CharField(max_length=50, null=True, blank=True,default="")
    total_dose = models.CharField(max_length=50, null=True, blank=True,default="")
    density = models.CharField(max_length=50, null=True, blank=True,default="")
    cmc_1 = models.CharField(max_length=225, null=True, blank=True,default="")
    cmc_1_1 = models.CharField(max_length=225, null=True, blank=True,default="")
    cmc_2 = models.CharField(max_length=225, null=True, blank=True,default="")
    cmc_3 = models.CharField(max_length=225, null=True, blank=True,default="")
    cmc_4 = models.CharField(max_length=225, null=True, blank=True,default="")
    clinical_1 = models.CharField(max_length=225, null=True, blank=True,default="")
    clinical_2 = models.CharField(max_length=225, null=True, blank=True,default="")
    clinical_3 = models.CharField(max_length=225, null=True, blank=True,default="")

    def __str__(self):
        return self.checklist_id.report + str(self.id)

class IIGAnswerSnapshot(models.Model):
    iig_answer = models.ForeignKey(IIGAnswers, on_delete=models.CASCADE, related_name='rld_snapshots')
    snapshot = models.FileField(upload_to="media/iig", blank=True, null=True)

class IIGTableRowsAnswers(models.Model):
    static_rel = models.ForeignKey(IIGAnswers, on_delete=models.CASCADE)
    rm_code = models.CharField(max_length=50, null=True, blank=True)
    ingredients = models.CharField(max_length=50, null=True, blank=True)
    func_of_excpt = models.CharField(max_length=50, null=True, blank=True)
    all_strength_dose = models.CharField(max_length=50, null=True, blank=True)
    all_strength_amount = models.CharField(max_length=50, null=True, blank=True)
    all_strength_w = models.CharField(max_length=50, null=True, blank=True)
    molar_ratio = models.CharField(max_length=50, null=True, blank=True) #New Added
    max_amount = models.CharField(max_length=50, null=True, blank=True)
    route = models.CharField(max_length=50, null=True, blank=True)
    max_potency = models.CharField(max_length=50, null=True, blank=True)
    max_dailyexp = models.CharField(max_length=50, null=True, blank=True)


class IIGSnapshot(models.Model):
    iig_table = models.ForeignKey(IIGTableRowsAnswers, on_delete=models.CASCADE, related_name='snapshots')
    snapshot = models.FileField(upload_to="media/iig", blank=True, null=True)
    date = models.DateField(auto_now_add=True, null=True)

# Size, Shape & Score Models Should be below this line


class ProductComparison(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    PRODUCT_TYPE_CHOICES = [
        ("tablet", "Tablet"),
        ("capsule", "Capsule"),
    ]

    product_name = models.CharField(max_length=255, verbose_name="RLD Product Name")
    product_type = models.CharField(
        max_length=10, choices=PRODUCT_TYPE_CHOICES, verbose_name="Product Type"
    )
    # checklist_name = models.CharField(max_length=100, null=True, blank=True)
    company_product_name = models.CharField(max_length=100, null=True, blank=True)
    is_completed_by_doer = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)


class TabletComparison(models.Model):
    comparison = models.OneToOneField(
        ProductComparison, on_delete=models.CASCADE, related_name="tablet_comparison"
    )
    shape_trld = models.CharField(max_length=255, blank=True, null=True)
    color_trld = models.CharField(max_length=255, blank=True, null=True)
    scoring_trld = models.CharField(max_length=255, blank=True, null=True)
    score_depth_trld = models.CharField(max_length=255, blank=True, null=True)
    avg_thickness_trld = models.CharField(max_length=255, blank=True, null=True)
    avg_width_trld = models.CharField(max_length=255, blank=True, null=True)
    avg_length_trld = models.CharField(max_length=255, blank=True, null=True)
    largest_dimension_trld = models.CharField(max_length=255, blank=True, null=True)
    volume_trld = models.CharField(max_length=255, blank=True, null=True)
    surface_area_trld = models.CharField(max_length=255, blank=True, null=True)
    cross_sectional_area_trld = models.CharField(max_length=255, blank=True, null=True)
    picture_trld = models.FileField(upload_to="media/tablet_picture_rld", blank=True, null=True)
    shape_tcompany = models.CharField(max_length=255, blank=True, null=True)
    color_tcompany = models.CharField(max_length=255, blank=True, null=True)
    scoring_tcompany = models.CharField(max_length=255, blank=True, null=True)
    score_depth_tcompany = models.CharField(max_length=255, blank=True, null=True)
    avg_thickness_tcompany = models.CharField(max_length=255, blank=True, null=True)
    avg_width_tcompany = models.CharField(max_length=255, blank=True, null=True)
    avg_length_tcompany = models.CharField(max_length=255, blank=True, null=True)
    largest_dimension_tcompany = models.CharField(max_length=255, blank=True, null=True)
    volume_tcompany = models.CharField(max_length=255, blank=True, null=True)
    surface_area_tcompany = models.CharField(max_length=255, blank=True, null=True)
    cross_sectional_area_tcompany = models.CharField(
        max_length=255, blank=True, null=True
    )
    picture_tcompany = models.FileField(upload_to="media/tablet_picture_company", blank=True, null=True)
    shape_tdiff = models.CharField(max_length=255, blank=True, null=True)
    color_tdiff = models.CharField(max_length=255, blank=True, null=True)
    scoring_tdiff = models.CharField(max_length=255, blank=True, null=True)
    score_depth_tdiff = models.CharField(max_length=255, blank=True, null=True)
    avg_thickness_tdiff = models.CharField(max_length=255, blank=True, null=True)
    avg_width_tdiff = models.CharField(max_length=255, blank=True, null=True)
    avg_length_tdiff = models.CharField(max_length=255, blank=True, null=True)
    largest_dimension_tdiff = models.CharField(max_length=255, blank=True, null=True)
    volume_tdiff = models.CharField(max_length=255, blank=True, null=True)
    surface_area_tdiff = models.CharField(max_length=255, blank=True, null=True)
    cross_sectional_area_tdiff = models.CharField(max_length=255, blank=True, null=True)
    picture_tdiff = models.FileField(upload_to="media/tablet_picture_diff", blank=True, null=True)
    shape_tfda = models.CharField(max_length=255, blank=True, null=True)
    color_tfda = models.CharField(max_length=255, blank=True, null=True)
    scoring_tfda = models.CharField(max_length=255, blank=True, null=True)
    score_depth_tfda = models.CharField(max_length=255, blank=True, null=True)
    avg_thickness_tfda = models.CharField(max_length=255, blank=True, null=True)
    avg_width_tfda = models.CharField(max_length=255, blank=True, null=True)
    avg_length_tfda = models.CharField(max_length=255, blank=True, null=True)
    largest_dimension_tfda = models.CharField(max_length=255, blank=True, null=True)
    volume_tfda = models.CharField(max_length=255, blank=True, null=True)
    surface_area_tfda = models.CharField(max_length=255, blank=True, null=True)
    cross_sectional_area_tfda = models.CharField(max_length=255, blank=True, null=True)
    picture_tfda = models.FileField(upload_to="media/tablet_picture_fda", blank=True, null=True)


class CapsuleComparison(models.Model):
    comparison = models.OneToOneField(
        ProductComparison, on_delete=models.CASCADE, related_name="capsule_comparison"
    )
    shape_crld = models.CharField(max_length=255, blank=True, null=True)
    color_cap_crld = models.CharField(max_length=255, blank=True, null=True)
    color_body_crld = models.CharField(max_length=255, blank=True, null=True)
    size_crld = models.CharField(max_length=255, blank=True, null=True)
    tolerance_limit_crld = models.CharField(max_length=255, blank=True, null=True)
    dimensions_crld = models.CharField(max_length=255, blank=True, null=True)
    volume_crld = models.CharField(max_length=255, blank=True, null=True)
    bead_size_crld = models.CharField(max_length=255, blank=True, null=True)
    picture_crld = models.ImageField(
        upload_to="media/capsule_pictures_rld/", blank=True, null=True
    )
    shape_company = models.CharField(max_length=255, blank=True, null=True)
    color_cap_company = models.CharField(max_length=255, blank=True, null=True)
    color_body_company = models.CharField(max_length=255, blank=True, null=True)
    size_company = models.CharField(max_length=255, blank=True, null=True)
    tolerance_limit_company = models.CharField(max_length=255, blank=True, null=True)
    dimensions_company = models.CharField(max_length=255, blank=True, null=True)
    volume_company = models.CharField(max_length=255, blank=True, null=True)
    bead_size_company = models.CharField(max_length=255, blank=True, null=True)
    picture_company = models.ImageField(
        upload_to="media/capsule_pictures_company/", blank=True, null=True
    )
    shape_cdiff = models.CharField(max_length=255, blank=True, null=True)
    size_cdiff = models.CharField(max_length=255, blank=True, null=True)
    tolerance_limit_cdiff = models.CharField(max_length=255, blank=True, null=True)
    dimensions_cdiff = models.CharField(max_length=255, blank=True, null=True)
    volume_cdiff = models.CharField(max_length=255, blank=True, null=True)
    bead_size_cdiff = models.CharField(max_length=255, blank=True, null=True)
    picture_cdiff = models.ImageField(
        upload_to="media/capsule_pictures_diff/", blank=True, null=True
    )
    shape_cfda = models.CharField(max_length=255, blank=True, null=True)
    size_cfda = models.CharField(max_length=255, blank=True, null=True)
    tolerance_limit_cfda = models.CharField(max_length=255, blank=True, null=True)
    dimensions_cfda = models.CharField(max_length=255, blank=True, null=True)
    volume_cfda = models.CharField(max_length=255, blank=True, null=True)
    bead_size_cfda = models.CharField(max_length=255, blank=True, null=True)
    picture_cfda = models.ImageField(
        upload_to="media/capsule_pictures_fda/", blank=True, null=True
    )


# API Facility Models Should be below this line


# Validation Models Should be below this line
class ValidationReportQuestions(models.Model):
    report_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    sub_category = models.CharField(max_length=255)
    sub_sub_category = models.CharField(max_length=255, null=True, blank=True)
    question = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.report_name

class ValidationUserReports(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="validation_reports_created"
    )
    report_name = models.ForeignKey(
        ValidationReportQuestions, on_delete=models.CASCADE, related_name="validation_user_reports"
    )
    product_name = models.CharField(max_length=255)
    # checklist_name = models.CharField(max_length=255)
    is_completed_by_doer = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)
    is_completed_by_checker = models.BooleanField(default=False)

class ValidationUserAnswers(models.Model):
    ANSWER_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("not_applicable", "Not Applicable"),
    ]
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="validation_user_answers"
    )
    report_name = models.ForeignKey(
        ValidationUserReports, on_delete=models.CASCADE, related_name="validation_answers"
    )
    report_question = models.ForeignKey(
        ValidationReportQuestions, on_delete=models.CASCADE, related_name="validation_question_answers"
    )
    answer = models.CharField(
        max_length=25, choices=ANSWER_CHOICES, null=True, blank=True
    )
    comment = models.TextField(max_length=1000, default="")



# VP Models Should be below this line
class VPReportQuestions(models.Model):
    report_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    sub_category = models.CharField(max_length=255, null=True, blank=True)
    sub_sub_category = models.CharField(max_length=255, null=True, blank=True)
    question = RichTextField(null=True, blank=True)

    def __str__(self):
        return self.report_name


class VPUserReports(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="vp_reports_created"
    )
    report_name = models.ForeignKey(
        VPReportQuestions, on_delete=models.CASCADE, related_name="vp_user_reports"
    )
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    # checklist_name = models.CharField(max_length=255)
    is_completed_by_doer = models.BooleanField(default=False)
    is_completed_by_checker = models.BooleanField(default=False)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)
    statues = models.JSONField(default=dict,null=True,blank=True)

class VPUserAnswers(models.Model):
    ANSWER_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("not_applicable", "Not Applicable"),
    ]
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="vp_user_answers"
    )
    report_name = models.ForeignKey(
        VPUserReports, on_delete=models.CASCADE, related_name="vp_answers"
    )
    report_question = models.ForeignKey(
        VPReportQuestions, on_delete=models.CASCADE, related_name="vp_question_answers"
    )
    answer = models.CharField(
        max_length=25, choices=ANSWER_CHOICES, null=True, blank=True
    )
    comment = models.TextField(max_length=1000, default="")


# White Paper Models Should be below this line
# class AppendixChecklistUser(models.Model):
#     user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
#     checklist_name = models.CharField(max_length=200, null=True, blank=True)
class GeneralChecklistUSer(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    # checklist_name = models.CharField(max_length=200, null=True, blank=True)
    product_name = models.CharField(max_length=200, null=True, blank=True)
    is_completed_by_doer = models.BooleanField(default=False)
    statues = models.JSONField(default=dict,null=True,blank=True)
    APPROVAL_CHOICES = [('False','False'),('True','True'),('Done','Done')]
    approved_by_checkers_level_1 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_2 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_3 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_4 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_5 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_6 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    approved_by_checkers_level_7 = models.CharField(max_length=5,choices=APPROVAL_CHOICES,default='False')
    show_buttons_doer = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        GeneralAnswer.objects.get_or_create(
            checklist=self,
        )
        AppendixWhitePaper.objects.get_or_create(
            checklist_user=self,
        )


class AppendixWhitePaper(models.Model):
    # user = models.ForeignKey(GeneralChecklistUSer, on_delete=models.CASCADE)
    checklist_user = models.ForeignKey(GeneralChecklistUSer, on_delete=models.CASCADE)
    # checklist= models.ForeignKey(AppendixChecklistUser, on_delete=models.CASCADE)

    #Combination Product Assessment Form
    product_strength = models.TextField(null=True, blank=True)
    anda_nda = models.CharField(max_length=200, null=True, blank=True)
    applicant = models.CharField(max_length=200, null=True, blank=True)
    pr_manu_site = models.CharField(max_length=200, null=True, blank=True)
    package_type = models.CharField(max_length=200, null=True, blank=True)
    ir_tablet = models.BooleanField(default=False)
    ir_capsule = models.BooleanField(default=False)
    er_tablet = models.BooleanField(default=False)
    er_capsule = models.BooleanField(default=False)
    topical = models.BooleanField(default=False)
    sub_tablets = models.BooleanField(default=False)
    top_trans_gel = models.BooleanField(default=False)
    nasal_sp = models.BooleanField(default=False)
    oral_sss = models.BooleanField(default=False)
    ointment = models.BooleanField(default=False)
    inhalation = models.BooleanField(default=False)
    inj_pep_com = models.BooleanField(default=False)
    tdds = models.BooleanField(default=False)
    ophthalmic = models.BooleanField(default=False)
    other_1 = models.BooleanField(default=False)
    other_2 = models.BooleanField(default=False)
    other_3 = models.BooleanField(default=False)

    other_name_1 = models.CharField(max_length=200, null=True, blank=True)
    other_name_2 = models.CharField(max_length=200, null=True, blank=True)
    other_name_3 = models.CharField(max_length=200, null=True, blank=True)

    # Basis of Submission
    rld_product = models.CharField(max_length=200, null=True, blank=True)
    basis_anda = models.CharField(max_length=200, null=True, blank=True)
    basis_anda_applicant = models.CharField(max_length=200, null=True, blank=True)
    market_avail_rx = models.BooleanField(default=False)
    market_avail_otc = models.BooleanField(default=False)

    # Combination Product Assessment Form
    com_product_name = models.CharField(max_length=200, null=True, blank=True)
    com_anda = models.CharField(max_length=200, null=True, blank=True)
    date_anda = models.DateField(null=True, blank=True)
    current_status_literature = models.BooleanField(default=False)
    current_status_development = models.BooleanField(default=False)
    current_status_execution = models.BooleanField(default=False)
    current_status_submission = models.BooleanField(default=False)
    current_status_fda = models.BooleanField(default=False)
    current_status_approved = models.BooleanField(default=False)
    reference_list_drug = models.CharField(max_length=200, null=True, blank=True)
    nda_anda_form = models.CharField(max_length=200, null=True, blank=True)
    applicant_rld = models.CharField(max_length=200, null=True, blank=True)
    rld_package_config = models.ImageField(upload_to="media/appendix_white_paper/rld_package",null=True,blank=True)
    company_package_config = models.ImageField(upload_to="media/appendix_white_paper/company_package",null=True,blank=True)
    description_device_1 = models.TextField(null=True, blank=True)
    description_device_2 = models.TextField(null=True, blank=True)
    description_device_3 = models.TextField(null=True, blank=True)
    company_anda_form = models.CharField(max_length=200, null=True, blank=True)
    IF_YES_CHOICES = [
        ('Yes','Yes'),
        ('No','No')
    ]
    rld_cross_labeled = models.CharField(max_length=3, choices=IF_YES_CHOICES, null=True, blank=True)
    type_comb_pro_single = models.BooleanField(default=False)
    type_comb_pro_co_packaged = models.BooleanField(default=False)
    type_comb_pro_cross_labeled = models.BooleanField(default=False)
    category_1_device = models.BooleanField(default=False)
    category_2_device = models.BooleanField(default=False)
    category_3_device = models.BooleanField(default=False)
    category_convenience = models.BooleanField(default=False)
    category_prefilled_drug = models.BooleanField(default=False)
    category_prefilled_biologic = models.BooleanField(default=False)
    category_device_coated_drug = models.BooleanField(default=False)
    category_device_coated_biologic = models.BooleanField(default=False)
    category_drug_biologic_combination = models.BooleanField(default=False)
    category_separate_product = models.BooleanField(default=False)
    category_possible_combination = models.BooleanField(default=False)
    category_other_type = models.BooleanField(default=False)
    plan_device_assembly = models.TextField(null=True, blank=True)
    instruction_of_use = models.CharField(max_length=3,choices=IF_YES_CHOICES,null=True, blank=True)
    diff_com_rld = models.CharField(max_length=3,choices=IF_YES_CHOICES,null=True, blank=True)
    if_yes_diff_device = models.CharField(max_length=3,choices=IF_YES_CHOICES,null=True, blank=True)
    other_attr_specific= models.TextField(null=True, blank=True)
    CONCLUSION_CHOICES = [
        ('Yes','Yes'),
        ('No','No'),
        ('Not sure','Not sure')
    ]
    conclusion = models.CharField(max_length=8,choices=CONCLUSION_CHOICES,null=True, blank=True)
    # Appendix 1: List of Item
    threshold_analysis_shared_by = models.CharField(max_length=200, null=True, blank=True)
    threshold_analysis_review_completion = models.CharField(max_length=200, null=True, blank=True)
    threshold_analysis_final_review = models.CharField(max_length=200, null=True, blank=True)

    threshold_finding_shared_by = models.CharField(max_length=200, null=True, blank=True)
    threshold_finding_review_completion = models.CharField(max_length=200, null=True, blank=True)
    threshold_finding_final_review = models.CharField(max_length=200, null=True, blank=True)

    design_dev_shared_by = models.CharField(max_length=200, null=True, blank=True)
    design_dev_review_completion = models.CharField(max_length=200, null=True, blank=True)
    design_dev_final_review = models.CharField(max_length=200, null=True, blank=True)

    dhf_shared_by = models.CharField(max_length=200, null=True, blank=True)
    dhf_review_completion = models.CharField(max_length=200, null=True, blank=True)
    dhf_final_review = models.CharField(max_length=200, null=True, blank=True)


    risk_analysis_shared_by = models.CharField(max_length=200, null=True, blank=True)
    risk_analysis_review_completion = models.CharField(max_length=200, null=True, blank=True)
    risk_analysis_final_review = models.CharField(max_length=200, null=True, blank=True)


    qsr_design_shared_by = models.CharField(max_length=200, null=True, blank=True)
    qsr_design_review_completion = models.CharField(max_length=200, null=True, blank=True)
    qsr_design_final_review = models.CharField(max_length=200, null=True, blank=True)


    cgmp_qsr_shared_by = models.CharField(max_length=200, null=True, blank=True)
    cgmp_qsr_review_completion = models.CharField(max_length=200, null=True, blank=True)
    cgmp_qsr_final_review = models.CharField(max_length=200, null=True, blank=True)


    vendor_docs_shared_by = models.CharField(max_length=200, null=True, blank=True)
    vendor_docs_review_completion = models.CharField(max_length=200, null=True, blank=True)
    vendor_docs_final_review = models.CharField(max_length=200, null=True, blank=True)


class AppendixTableRowsAnswers(models.Model):
    appendix = models.ForeignKey(AppendixWhitePaper, on_delete=models.CASCADE, related_name='apx_items')
    QSR_list = models.TextField(blank=True, null=True)
    ownership = models.TextField(blank=True, null=True)
    initial_template = models.TextField(blank=True, null=True)
    responsibility_review = models.TextField(blank=True, null=True)
    review_completion = models.TextField(blank=True, null=True)
    final_review = models.TextField(blank=True, null=True)


# General White Paper


class GeneralAnswer(models.Model):
    checklist = models.ForeignKey(GeneralChecklistUSer, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200, null=True, blank=True)
    strength = models.CharField(max_length=200, null=True, blank=True)
    dosage_form = models.CharField(max_length=200, null=True, blank=True)
    filing_category = models.CharField(max_length=200, null=True, blank=True)
    product_manu_site = models.CharField(max_length=200, null=True, blank=True)
    anda_holder_name = models.CharField(max_length=200, null=True, blank=True)
    dmf_holder = models.CharField(max_length=200, null=True, blank=True)
    dmf_manu_site = models.CharField(max_length=200, null=True, blank=True)
    proprietary_name_rld = models.CharField(max_length=200, null=True, blank=True)
    rld_rs_strength_rld = models.CharField(max_length=200, null=True, blank=True)
    nda_anda_rld = models.CharField(max_length=200, null=True, blank=True)
    approval_date_rld = models.DateField(null=True, blank=True)
    nda_holder_rld = models.CharField(max_length=200, null=True, blank=True)
    te_code_rld = models.CharField(max_length=200, null=True, blank=True)
    max_daily_dose_rld = models.CharField(max_length=200, null=True, blank=True)
    rems_requirement_rld = models.CharField(max_length=200, null=True, blank=True)
    proprietary_name_rs = models.CharField(max_length=200, null=True, blank=True)
    rld_rs_strength_rs = models.CharField(max_length=200, null=True, blank=True)
    nda_anda_rs = models.CharField(max_length=200, null=True, blank=True)
    approval_date_rs = models.DateField(null=True, blank=True)
    nda_holder_rs = models.CharField(max_length=200, null=True, blank=True)
    te_code_rs = models.CharField(max_length=200, null=True, blank=True)
    max_daily_dose_rs = models.CharField(max_length=200, null=True, blank=True)
    rems_requirement_rs = models.CharField(max_length=200, null=True, blank=True)
    patent_snapshot = models.ImageField(upload_to='media/GeneralWhitePaper/patent', null=True, blank=True)
    exclusivity_snapshot = models.ImageField(upload_to='media/GeneralWhitePaper/exclusivity', null=True, blank=True)
    dosing_regimen_rld = models.CharField(max_length=200, null=True, blank=True)
    dosing_regimen_proposed = models.CharField(max_length=200, null=True, blank=True)
    indication_rld = models.CharField(max_length=200, null=True, blank=True)
    indication_proposed = models.CharField(max_length=200, null=True, blank=True)
    proposed_mdd = models.CharField(max_length=200, null=True, blank=True)
    basis_mdd = models.CharField(max_length=200, null=True, blank=True)
    control_mdd = models.CharField(max_length=200, null=True, blank=True)
    drug_shortage_status = models.CharField(max_length=200, null=True, blank=True)
    date_first_period = models.DateField(null=True, blank=True)
    drug_shortage_snap = models.ImageField(upload_to="media/GeneralWhitePaper/snapshots", null=True, blank=True)
    IS_API_CHOICES = [
        ('Yes','Yes'),
        ('No','No')
    ]
    is_api = models.CharField(max_length=3,choices=IS_API_CHOICES, null=True, blank=True)
    have_potential = models.CharField(max_length=3, choices=IS_API_CHOICES, null=True, blank=True)
    snapshot_7 =models.ImageField(upload_to="media/GeneralWhitePaper/snapshots", null=True, blank=True)
    pre_assign_anda_number = models.CharField(max_length=200, null=True, blank=True)
    if_yes_9 = models.CharField(max_length=3, choices=IS_API_CHOICES, null=True, blank=True)
    detail_9 = models.TextField(null=True, blank=True)
    regular_history = models.CharField(max_length=255, null=True, blank=True)
    drug_sub_dmf_status = models.CharField(max_length=255, null=True, blank=True)
    detail_12 = models.TextField(null=True,blank=True)
    detail_13 = models.TextField(null=True, blank=True)
    detail_15 = models.CharField(max_length=255, null=True, blank=True)
    detail_16 = models.CharField(max_length=255, null=True, blank=True)
    detail_17 = models.TextField(null=True, blank=True)
    detail_18 = models.TextField(null=True, blank=True)
    detail_19 = models.TextField(null=True, blank=True)
    detail_20 = models.TextField(null=True, blank=True)
    detail_21 = models.TextField(null=True, blank=True)
    detail_22 = models.TextField(null=True, blank=True)
    detail_23 = models.TextField(null=True, blank=True)
    snapshot_23 = models.ImageField(upload_to='media/GeneralWhitePaper/snapshots', null=True, blank=True)
    detail_24 = models.TextField(null=True, blank=True)
    detail_25_1 = models.TextField(null=True, blank=True)
    detail_25_2 = models.TextField(null=True, blank=True)
    detail_25_3 = models.TextField(null=True, blank=True)
    checker_comment = models.JSONField(null=True,blank=True,default=dict)

class GeneralCheckerComments(models.Model):
    checklist = models.ForeignKey(GeneralChecklistUSer, on_delete=models.CASCADE)
    checker = models.CharField(max_length=200, null=True, blank=True)
    comment = models.TextField(null=True,blank=True)

class GeneralTable13(models.Model):
    ans_rel = models.ForeignKey(GeneralAnswer, on_delete=models.CASCADE)
    ingredients = models.CharField(max_length=100, null=True, blank=True)
    salt = models.CharField(max_length=100, null=True, blank=True)
    rld_formation = models.CharField(max_length=100, null=True, blank=True)
    proposed_generic = models.CharField(max_length=100, null=True, blank=True)
    function = models.CharField(max_length=100, null=True, blank=True)

class GeneralTable14(models.Model):
    ans_rel = models.ForeignKey(GeneralAnswer, on_delete=models.CASCADE)
    ingredients = models.CharField(max_length=100, null=True, blank=True)
    qty_ml = models.CharField(max_length=100, null=True, blank=True)
    w_v = models.CharField(max_length=100, null=True, blank=True)
    total_daily_intake = models.CharField(max_length=100, null=True, blank=True)
    max_potency = models.CharField(max_length=100, null=True, blank=True)

class GeneralReportQuestions(models.Model):
    category = models.CharField(max_length=255)
    sub_category = models.CharField(max_length=255)
    question = RichTextField(null=True, blank=True)

class GeneralUserAnswers(models.Model):
    ans_rel = models.ForeignKey(GeneralAnswer, on_delete=models.CASCADE)
    ANSWER_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("not_applicable", "Not Applicable"),
    ]
    report_question = models.ForeignKey(
        GeneralReportQuestions, on_delete=models.CASCADE, related_name="gen_question_answers"
    )
    answer = models.CharField(
        max_length=25, choices=ANSWER_CHOICES, null=True, blank=True
    )
    comment = models.TextField(default="")



class DemoRequest(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    country = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    company_name = models.CharField(max_length=255)
    company_domain = models.CharField(max_length=255)
    service = models.CharField(max_length=255)
    question = models.TextField(null=True, blank=True)
    # Slot is stored as IST (Asia/Kolkata) wall-clock time — the business's
    # reference timezone. The booking widget shows this alongside the
    # visitor's local timezone but always books against IST.
    slot_date = models.DateField(null=True, blank=True)
    slot_time = models.TimeField(null=True, blank=True)


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slot_date", "slot_time"],
                condition=models.Q(slot_date__isnull=False, slot_time__isnull=False),
                name="unique_demo_request_slot",
            )
        ]

    def __str__(self):
        return f"{self.full_name} - {self.service}"


# ---------------------------------------------------------------------------
# Regulatory Technical Tools AI — workflow/audit foundation.
#
# Scoped entirely to RATools (Regulatory Technical Tools), deliberately kept
# separate from AIDatabase/483 workflow state and from AdminMaster.CustomUser
# .role / AdminMaster.AssignChecker (which already mix both product domains
# in one REPORT_CHOICES list — see REGULATORY_TECHNICAL_TOOLS_BASELINE_REPORT.md
# section 6). Existing per-checklist doer/checker-level fields (e.g.
# DMFChecklistUser.is_completed_by_doer / approved_by_checkers_level_N) are
# untouched by this addition.
#
# Note: "VP" here means the Doer -> Reviewer -> VP approval-role chain from
# the SOW, a personnel role. It is unrelated to the existing VPReportQuestions
# / VPUserReports / VPUserAnswers models, which represent a "Verification
# Protocol" report *type*, not a role. The two are different Django models
# in different namespaces and do not collide in code, but the naming overlap
# is worth remembering when reading the codebase.
# ---------------------------------------------------------------------------


class RegulatoryRole(models.Model):
    """Doer / Reviewer / VP role assignment, scoped to Regulatory Technical Tools only."""

    ROLE_CHOICES = [
        ("doer", "Doer"),
        ("reviewer", "Reviewer"),
        ("vp", "VP"),
    ]
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="regulatory_roles"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


class RegulatoryReviewGate(models.Model):
    """
    Traceable review gate for a Regulatory Technical Tools artifact (a
    calculator result, a gap-analysis report, a checklist submission, etc.).

    Attached generically via content_type/object_id so it can be linked to
    any existing or future RATools model without requiring a schema change
    on that model.
    """

    STATUS_CHOICES = [
        ("pending_review", "Pending Review"),
        ("pending_vp", "Pending VP Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    doer = models.ForeignKey(
        CustomUser, on_delete=models.PROTECT, related_name="regulatory_doer_gates"
    )
    reviewer = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulatory_reviewer_gates",
    )
    vp = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulatory_vp_gates",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending_review")
    reviewer_comment = models.TextField(blank=True)
    vp_comment = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    version = models.PositiveIntegerField(default=1)
    version_locked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"ReviewGate({self.content_type}:{self.object_id}) - {self.status}"


class RegulatoryAuditTrail(models.Model):
    """
    21 CFR Part 11-style audit trail for Regulatory Technical Tools actions.

    Entries are immutable once written: save() rejects updates to an
    existing row, and delete() is disabled. Attach to any object via the
    generic content_type/object_id pair, or leave target blank for
    account-level events (e.g. role_action).
    """

    ACTION_CHOICES = [
        ("calculator_input", "Calculator Input"),
        ("calculator_output", "Calculator Output"),
        ("data_upload", "Data Upload"),
        ("document_version_upload", "Document Version Upload"),
        ("gap_analysis_generated", "Gap Analysis Generated"),
        ("ai_response_generated", "AI Response Generated"),
        ("review_action", "Review Action"),
        ("approval", "Approval"),
        ("rejection", "Rejection"),
        ("export", "Export"),
        ("role_action", "User Role Action"),
        ("version_change", "Version Change"),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="regulatory_audit_events",
    )
    role_at_time = models.CharField(max_length=20, blank=True)
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES)

    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    previous_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["action_type", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "RegulatoryAuditTrail entries are immutable and cannot be updated."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("RegulatoryAuditTrail entries cannot be deleted.")

    def __str__(self):
        return f"{self.get_action_type_display()} by {self.user} @ {self.created_at:%Y-%m-%d %H:%M}"

