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


# Regulatory Technical Tools AI
# RegulatoryRole had no admin registration, so there was no way to grant anyone
# the doer/reviewer/vp role -- which left the whole review-gate flow unreachable.
@admin.register(models.RegulatoryRole)
class RegulatoryRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")


class _ReadOnlyModelAdmin(admin.ModelAdmin):
    """
    View-only admin, used here for two distinct reasons:

    1. The model rejects mutation outright (RegulatoryAuditTrail,
       RegulatoryGapAnalysisReport raise from save()/delete()), so editable
       controls would only ever produce a ValueError.
    2. The model must only be mutated through a path that writes an audit
       entry (RegulatoryReviewGate). ModelAdmin.save_model() calls save()
       directly and would leave no RegulatoryAuditTrail record, which defeats
       the 21 CFR Part 11 trail these models exist to provide.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Gates are created by RATools.gap_analysis and advanced only by
# RATools.views.review_gate_action, which logs every transition via
# audit.log_event(). Nothing legitimately edits one by hand, so this stays
# view-only rather than offering an unaudited way to flip `status`.
@admin.register(models.RegulatoryReviewGate)
class RegulatoryReviewGateAdmin(_ReadOnlyModelAdmin):
    list_display = ("id", "content_type", "object_id", "status", "doer", "reviewer", "vp", "version")
    list_filter = ("status",)


@admin.register(models.RegulatoryAuditTrail)
class RegulatoryAuditTrailAdmin(_ReadOnlyModelAdmin):
    list_display = ("created_at", "user", "role_at_time", "action_type", "content_type", "object_id")
    list_filter = ("action_type",)
    search_fields = ("user__username", "reason")
    date_hierarchy = "created_at"


@admin.register(models.RegulatoryGapAnalysisReport)
class RegulatoryGapAnalysisReportAdmin(_ReadOnlyModelAdmin):
    list_display = ("id", "source_type", "object_id", "version", "gap_count", "answered_count", "created_at")
    list_filter = ("source_type",)
