from django.contrib import admin
from . import models
from .models import ANDAReportQuestions, ANDAUserReports, ANDAUserAnswers,CCTemplate


# Register your models here.
#ANDA
admin.site.register(models.ANDAReportQuestions)
admin.site.register(models.ANDAUserReports)
admin.site.register(models.ANDAUserAnswers)

#  Controlled Correspondences
admin.site.register(models.CCBestPractice)
admin.site.register(models.CCTemplate)

# SSS
admin.site.register(models.ProductComparison)
admin.site.register(models.TabletComparison)
admin.site.register(models.CapsuleComparison)

# IIG
admin.site.register(models.IIGAnswers)
admin.site.register(models.IIGAnswerSnapshot)
admin.site.register(models.IIGTableRowsAnswers)
admin.site.register(models.IIGChecklistUser)
admin.site.register(models.IIGSnapshot)

#Validation Models
admin.site.register(models.ValidationReportQuestions)
admin.site.register(models.ValidationUserReports)
admin.site.register(models.ValidationUserAnswers)

# VP Register Models
admin.site.register(models.VPReportQuestions)
admin.site.register(models.VPUserReports)
admin.site.register(models.VPUserAnswers)

# GeneralWhitePaper
admin.site.register(models.GeneralChecklistUSer)
admin.site.register(models.GeneralAnswer)
admin.site.register(models.GeneralTable13)
admin.site.register(models.GeneralTable14)
admin.site.register(models.GeneralReportQuestions)
admin.site.register(models.GeneralUserAnswers)
# admin.site.register(models.AppendixChecklistUser)
admin.site.register(models.AppendixWhitePaper)
admin.site.register(models.AppendixTableRowsAnswers)

# DMF
admin.site.register(models.DMFChecklistUser)
admin.site.register(models.DMFReviewTableQuestion)
admin.site.register(models.DMFReviewAnswer)
admin.site.register(models.DMFModuleComment)
admin.site.register(models.DMFCATableQuestion)
admin.site.register(models.DMFCAAnswer)


admin.site.register(models.DemoRequest)
