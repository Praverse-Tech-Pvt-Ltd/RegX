from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from multiselectfield import MultiSelectField
from django.utils import timezone
# Create your models here.

# User model
class CustomUser(AbstractUser):
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    address_line = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    designation = models.CharField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=500, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    reports = models.CharField(max_length=15, blank=True, null=True)
    subscription_end_date = models.DateField(default=timezone.now)
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("company_user", "Company User"),
        ("company_checker", "Company Checker"),
    ]
    logo = models.ImageField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    footprint_ID = models.CharField(max_length=100, null=True, blank=True, default="No")
    groups = models.ManyToManyField(Group, related_name="custom_user_set", blank=True)
    user_permissions = models.ManyToManyField(
        Permission, related_name="custom_user_set", blank=True
    )
    login_token = models.CharField(max_length=100, default="No", blank=True)
    internal_team = models.BooleanField(default=False)
    fda_deficiency_database = models.BooleanField(default=False)
    complete_response_database = models.BooleanField(default=False)

    def __str__(self):
        return self.username

    class Meta:
        verbose_name = "CustomUser"

class AssignChecker(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    REPORT_CHOICES = [
        ('Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form','Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form'),
        ('Nasal Spray  & Inhalation Dosage','Nasal Spray  & Inhalation Dosage'),
        ('Parenteral Dosage','Parenteral Dosage'),
        ('Transdermal','Transdermal'),
        ('General ANDA','General ANDA'),
        ('Ophthalmic Dosage','Ophthalmic Dosage'),
        ('Semi Solid Dosage Form','Semi Solid Dosage Form'),
        ('Solid Oral Dosage','Solid Oral Dosage'),
        ('Liposome Dosage Form', 'Liposome Dosage Form'),
        ('Microsphere Dosage Form', 'Microsphere Dosage Form'),

        ('DMFChecklist','DMFChecklist'),

        ("IIG Proportionality Clearance - DPIs", "IIG Proportionality Clearance - DPIs"),
        ("IIG Proportionality Clearance - Inhalation","IIG Proportionality Clearance - Inhalation"),
        ("IIG Proportionality Clearance - Liquid Orals","IIG Proportionality Clearance - Liquid Orals"),
        ("IIG Proportionality Clearance - Injection-Otic-Ophthalmic","IIG Proportionality Clearance - Injection-Otic-Ophthalmic"),
        ("IIG Proportionality Clearance - MDIs", "IIG Proportionality Clearance - MDIs"),
        ("IIG Proportionality Clearance - Nasals", "IIG Proportionality Clearance - Nasals"),
        ("IIG Proportionality Clearance - Semisolids","IIG Proportionality Clearance - Semisolids"),
        ("IIG Proportionality Clearance - Tablets & Capsules","IIG Proportionality Clearance - Tablets & Capsules"),
        ("IIG Proportionality Clearance - Topical Solutions & Lotions","IIG Proportionality Clearance - Topical Solutions & Lotions"),
        ("IIG Proportionality Clearance - Transdermal","IIG Proportionality Clearance - Transdermal"),
        ("IIG Proportionality Clearance - Liposomes", "IIG Proportionality Clearance - Liposomes"),
        ("IIG Proportionality Clearance - Microspheres", "IIG Proportionality Clearance - Microspheres"),

        ('Size Shape and Score Comparison','Size Shape and Score Comparison'),
        ('API-VALIDATION','API-VALIDATION'),
        ('API-VERIFICATION','API-VERIFICATION'),
        ('DRUG PRODUCT VALIDATION','DRUG PRODUCT VALIDATION'),

        ('VP MDI and DPI Report','VP MDI and DPI Report'),
        ('VP Nasal and Inhalation Report','VP Nasal and Inhalation Report'),
        ('VP Ophthalmic Report','VP Ophthalmic Report'),
        ('VP - Oral Liquids Report','VP - Oral Liquids Report'),
        ('VP - Parenteral Report','VP - Parenteral Report'),
        ('VP - Solid Oral Report','VP - Solid Oral Report'),
        ('VP - Topical Report','VP - Topical Report'),
        ('VP - Transdermal Report','VP - Transdermal Report'),
        ('VP Liposome Report','VP Liposome Report'),
        ('VP Microsphere Report','VP Microsphere Report'),


        ('General White Paper','General White Paper'),
        ('Appendix White Paper','Appendix White Paper'),

        ('Controlled Correspondence Best Practices','Controlled Correspondence Best Practices'),
        ('Controlled Correspondences Templates','Controlled Correspondences Templates'),
        ('ANDA Facility Template','ANDA Facility Template'),
        ('Template for API Facility details','Template for API Facility details'),
        ('Form 483','Form 483'),
        ('ANDA ECTD','ANDA ECTD'),
        ('ANDA Technical Acceptance','ANDA Technical Acceptance'),
        ('ANDA Nasal Spary-Deficiency','ANDA Nasal Spary-Deficiency'),
        ('ANDA Liquid Oral-Deficiency','ANDA Liquid Oral-Deficiency'),
        ('ANDA IUD-Deficiency','ANDA IUD-Deficiency'),
        ('ANDA TDDS-Deficiency','ANDA TDDS-Deficiency'),
        ('ANDA Suppository-Deficiency','ANDA Suppository-Deficiency'),
        ('ANDA Topicals-Deficiency','ANDA Topicals-Deficiency'),
        ('ANDA Solid Oral-Deficiency','ANDA Solid Oral-Deficiency'),
        ('ANDA Otic - Deficiency','ANDA Otic - Deficiency'),
        ('ANDA Ophthalmic - Deficiency','ANDA Ophthalmic - Deficiency'),
        ('ANDA Injectable - Peptide Deficiency','ANDA Injectable - Peptide Deficiency'),
        ('ANDA Injectable - General Deficiency','ANDA Injectable - General Deficiency'),
        ('Major CR Nasal Spray-Deficiency', 'Major CR Nasal Spray-Deficiency'),
        ('Major CR Liquid Oral-Deficiency','Major CR Liquid Oral-Deficiency'),
        ('Major CR IUD-Deficiency','Major CR IUD-Deficiency'),
        ('Major CR TDDS-Deficiency','Major CR TDDS-Deficiency'),
        ('Major CR Suppository-Deficiency','Major CR Suppository-Deficiency'),
        ('Major CR Topicals-Deficiency','Major CR Topicals-Deficiency'),
        ('Major CR Solid Oral-Deficiency','Major CR Solid Oral-Deficiency'),
        ('Major CR Otic - Deficiency','Major CR Otic - Deficiency'),
        ('Major CR Ophthalmic - Deficiency','Major CR Ophthalmic - Deficiency'),
        ('Major CR Injectable - Peptide Deficiency','Major CR Injectable - Peptide Deficiency'),
        ('Major CR Injectable - General Deficiency','Major CR Injectable - General Deficiency'),
        ('Warning Latter','Warning Latter'),
        ('Module Simplifiacation','Module Simplifiacation'),
        ('Solid Oral Dosage Form','Solid Oral Dosage Form'),
        ('Sterile Dosage Form','Sterile Dosage Form'),




    ]
    assigned_report = MultiSelectField(max_length=5000, choices=REPORT_CHOICES, max_choices=100,null=True,blank=True)
    level_report_1 = models.IntegerField(default=0, null=True, blank=True)
    level_report_2 = models.IntegerField(default=0, null=True, blank=True)
    level_report_3 = models.IntegerField(default=0, null=True, blank=True)
    level_report_4 = models.IntegerField(default=0, null=True, blank=True)
    level_report_5 = models.IntegerField(default=0, null=True, blank=True)
    level_report_6 = models.IntegerField(default=0, null=True, blank=True)
    level_report_7 = models.IntegerField(default=0, null=True, blank=True)
    level_report_8 = models.IntegerField(default=0, null=True, blank=True)
    level_report_9 = models.IntegerField(default=0, null=True, blank=True)
    level_report_10 = models.IntegerField(default=0, null=True, blank=True)
    level_report_11 = models.IntegerField(default=0, null=True, blank=True)
    level_report_12 = models.IntegerField(default=0, null=True, blank=True)
    level_report_13 = models.IntegerField(default=0, null=True, blank=True)
    level_report_14 = models.IntegerField(default=0, null=True, blank=True)
    level_report_15 = models.IntegerField(default=0, null=True, blank=True)
    level_report_16 = models.IntegerField(default=0, null=True, blank=True)
    level_report_17 = models.IntegerField(default=0, null=True, blank=True)
    level_report_18 = models.IntegerField(default=0, null=True, blank=True)
    level_report_19 = models.IntegerField(default=0, null=True, blank=True)
    level_report_20 = models.IntegerField(default=0, null=True, blank=True)
    level_report_21 = models.IntegerField(default=0, null=True, blank=True)
    level_report_22 = models.IntegerField(default=0, null=True, blank=True)
    level_report_23 = models.IntegerField(default=0, null=True, blank=True)
    level_report_24 = models.IntegerField(default=0, null=True, blank=True)
    level_report_25 = models.IntegerField(default=0, null=True, blank=True)
    level_report_26 = models.IntegerField(default=0, null=True, blank=True)
    level_report_27 = models.IntegerField(default=0, null=True, blank=True)
    level_report_28 = models.IntegerField(default=0, null=True, blank=True)
    level_report_29 = models.IntegerField(default=0, null=True, blank=True)
    level_report_30 = models.IntegerField(default=0, null=True, blank=True)
    level_report_31 = models.IntegerField(default=0, null=True, blank=True)
    level_report_32 = models.IntegerField(default=0, null=True, blank=True)
    level_report_33 = models.IntegerField(default=0, null=True, blank=True)
    level_report_34 = models.IntegerField(default=0, null=True, blank=True)
    level_report_35 = models.IntegerField(default=0, null=True, blank=True)
    level_report_36 = models.IntegerField(default=0, null=True, blank=True)
    level_report_37 = models.IntegerField(default=0, null=True, blank=True)
    level_report_38 = models.IntegerField(default=0, null=True, blank=True)
    level_report_39 = models.IntegerField(default=0, null=True, blank=True)


    assigned_checker_level_1 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_2 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel_level_2",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_3 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel_level_3",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_4 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel_level_4",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_5 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel_level_5",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_6 = models.ManyToManyField(CustomUser, related_name="multi_assign_user_rel_level_6",limit_choices_to={'role': 'company_checker'},blank=True)
    assigned_checker_level_7 = models.ManyToManyField(CustomUser, related_name="multi_assign_head_rel",limit_choices_to={'role': 'company_checker'},blank=True)

    report_level_json = models.JSONField(default=dict, null=True, blank=True)
    checkers_json = models.JSONField(default=dict, null=True, blank=True)

    VIEW_SAMPLE_CHOICES = [
        ('Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form','Metered Dose Inhaler (MDI) and Dry Powder Inhaler (DPI) Dosage Form'),
        ('Nasal Spray  & Inhalation Dosage','Nasal Spray  & Inhalation Dosage'),
        ('Parenteral Dosage','Parenteral Dosage'),
        ('Transdermal','Transdermal'),
        ('General ANDA','General ANDA'),
        ('Ophthalmic Dosage','Ophthalmic Dosage'),
        ('Semi Solid Dosage Form','Semi Solid Dosage Form'),
        ('Solid Oral Dosage','Solid Oral Dosage'),
        ('Liposome Dosage Form', 'Liposome Dosage Form'),
        ('Microsphere Dosage Form', 'Microsphere Dosage Form'),


        ('DMFChecklist','DMFChecklist'),


        ("IIG Proportionality Clearance - DPIs", "IIG Proportionality Clearance - DPIs"),
        ("IIG Proportionality Clearance - Inhalation","IIG Proportionality Clearance - Inhalation"),
        ("IIG Proportionality Clearance - Liquid Orals","IIG Proportionality Clearance - Liquid Orals"),
        ("IIG Proportionality Clearance - Injection-Otic-Ophthalmic","IIG Proportionality Clearance - Injection-Otic-Ophthalmic"),
        ("IIG Proportionality Clearance - MDIs", "IIG Proportionality Clearance - MDIs"),
        ("IIG Proportionality Clearance - Nasals", "IIG Proportionality Clearance - Nasals"),
        ("IIG Proportionality Clearance - Semisolids","IIG Proportionality Clearance - Semisolids"),
        ("IIG Proportionality Clearance - Tablets & Capsules","IIG Proportionality Clearance - Tablets & Capsules"),
        ("IIG Proportionality Clearance - Topical Solutions & Lotions","IIG Proportionality Clearance - Topical Solutions & Lotions"),
        ("IIG Proportionality Clearance - Transdermal","IIG Proportionality Clearance - Transdermal"),
        ("IIG Proportionality Clearance - Liposomes", "IIG Proportionality Clearance - Liposomes"),
        ("IIG Proportionality Clearance - Microspheres", "IIG Proportionality Clearance - Microspheres"),

        ('Size Shape and Score Comparison','Size Shape and Score Comparison'),
        ('API-VALIDATION','API-VALIDATION'),
        ('API-VERIFICATION','API-VERIFICATION'),
        ('DRUG PRODUCT VALIDATION','DRUG PRODUCT VALIDATION'),

        ('VP MDI and DPI Report','VP MDI and DPI Report'),
        ('VP Nasal and Inhalation Report','VP Nasal and Inhalation Report'),
        ('VP Ophthalmic Report','VP Ophthalmic Report'),
        ('VP - Oral Liquids Report','VP - Oral Liquids Report'),
        ('VP - Parenteral Report','VP - Parenteral Report'),
        ('VP - Solid Oral Report','VP - Solid Oral Report'),
        ('VP - Topical Report','VP - Topical Report'),
        ('VP - Transdermal Report','VP - Transdermal Report'),
        ('VP Liposome Report','VP Liposome Report'),
        ('VP Microsphere Report','VP Microsphere Report'),


        ('General White Paper','General White Paper'),
        ('Appendix White Paper','Appendix White Paper'),


    ]
    view_sample_reports = MultiSelectField(max_length=2000, choices=VIEW_SAMPLE_CHOICES, max_choices=100,null=True,blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.checkers_json = {
            "level_1": list(self.assigned_checker_level_1.values_list('id', flat=True)) if self.id else [],
            "level_2": list(self.assigned_checker_level_2.values_list('id', flat=True)) if self.id else [],
            "level_3": list(self.assigned_checker_level_3.values_list('id', flat=True)) if self.id else [],
            "level_4": list(self.assigned_checker_level_4.values_list('id', flat=True)) if self.id else [],
            "level_5": list(self.assigned_checker_level_5.values_list('id', flat=True)) if self.id else [],
            "level_6": list(self.assigned_checker_level_6.values_list('id', flat=True)) if self.id else [],
            "level_7": list(self.assigned_checker_level_7.values_list('id', flat=True)) if self.id else [],
        }

        report_levels = [
            self.level_report_1, self.level_report_2, self.level_report_3, self.level_report_4, self.level_report_5,
            self.level_report_6, self.level_report_7, self.level_report_8, self.level_report_9, self.level_report_10,
            self.level_report_11, self.level_report_12, self.level_report_13, self.level_report_14, self.level_report_15,
            self.level_report_16, self.level_report_17, self.level_report_18, self.level_report_19, self.level_report_20,
            self.level_report_21, self.level_report_22, self.level_report_23, self.level_report_24, self.level_report_25,
            self.level_report_26, self.level_report_27, self.level_report_28, self.level_report_29, self.level_report_30,
            self.level_report_31, self.level_report_32, self.level_report_33,
            self.level_report_34,
            self.level_report_35,
            self.level_report_36,
            self.level_report_37,
            self.level_report_38,
            self.level_report_39,
        ]

        self.report_level_json = {
            report: level for report, level in zip([choice[0] for choice in self.REPORT_CHOICES[:-4]], report_levels)
        }
        # super(AssignChecker, self).save(*args, **kwargs)
        super().save(update_fields=['checkers_json','report_level_json'])

    def __str__(self):
        return self.user.username
