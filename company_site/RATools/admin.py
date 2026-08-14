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


@admin.register(models.DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "service", "slot_date", "slot_time", "status", "reschedule_count")
    list_filter = ("status", "service", "country")
    search_fields = ("full_name", "email", "company_name", "company_domain")
    readonly_fields = ("manage_token", "ics_sequence", "reminder_sent")
    date_hierarchy = "slot_date"


@admin.register(models.ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "company_name", "created_at")
    search_fields = ("full_name", "email", "company_name", "message")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(models.BookingHoliday)
class BookingHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "category")
    list_filter = ("category",)
    search_fields = ("name",)
    date_hierarchy = "date"
    ordering = ("date",)


@admin.register(models.BookingSettings)
class BookingSettingsAdmin(admin.ModelAdmin):
    list_display = ("meeting_duration_minutes", "buffer_minutes", "slot_interval_minutes")

    def has_add_permission(self, request):
        # Singleton — block "Add" once the one row exists, so admins are
        # taken straight to editing it instead of creating duplicates.
        return not models.BookingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Skip the list page entirely — jump straight to the single row's
        # change form (creating it on first visit) since there's only ever one.
        from django.shortcuts import redirect
        from django.urls import reverse
        settings_obj = models.BookingSettings.load()
        return redirect(reverse("admin:RATools_bookingsettings_change", args=[settings_obj.pk]))
