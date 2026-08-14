from django.contrib import admin
from django.db import transaction
from . import models
from .views import (
    refresh_form483_excel_cache,
    refresh_warning_letter_excel_cache,
    _build_excel_source_key,
)
from .tasks import process_form483_excel_task, process_gmpc_excel_task
# Register your models here.

admin.site.register(models.ANDA)
admin.site.register(models.ANDAeCTD)
admin.site.register(models.ANDATechnicalAcceptance)
admin.site.register(models.MajorCR)

admin.site.register(models.Form483Master)
admin.site.register(models.Form483System)
admin.site.register(models.Form483Observation)
admin.site.register(models.Form483ObeservationContent)
admin.site.register(models.UserCheckedUpdate)
# admin.site.register(models.Announcement)

admin.site.register(models.ChatMessage)
# admin.site.register(models.WarningLetter)
@admin.register(models.ObservationImage)
class ObservationImageAdmin(admin.ModelAdmin):
    list_display = ("image_name", "created_at")
    search_fields = ("image_name",)

    def save_model(self, request, obj, form, change):
        obj.full_clean()  # enforce validation in admin
        super().save_model(request, obj, form, change)

@admin.register(models.ObservationImageExcelMaster)
class ObservationImageExcelMasterAdmin(admin.ModelAdmin):
    list_display = ("display_name", "uploaded_at", "is_active", "excel_processing_flag")
    readonly_fields = ("excel_processing_flag",)

    def save_model(self, request, obj, form, change):
        baseline_path = None
        baseline_source_key = None
        file_replaced = "file" in getattr(form, "changed_data", [])
        obj._skip_post_save_task = True

        if change and obj.pk and file_replaced:
            previous_obj = models.ObservationImageExcelMaster.objects.filter(pk=obj.pk).first()
            if previous_obj and previous_obj.is_active and previous_obj.file:
                baseline_path = previous_obj.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_obj.pk,
                    path=baseline_path,
                )
        if baseline_path is None and obj.is_active:
            previous_active = (
                models.ObservationImageExcelMaster.objects
                .filter(is_active=True)
                .exclude(pk=obj.pk)
                .first()
            )
            if previous_active and previous_active.file:
                baseline_path = previous_active.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_active.pk,
                    path=baseline_path,
                )

        if obj.is_active:
            obj.excel_processing_flag = False

        super().save_model(request, obj, form, change)

        if obj.is_active and obj.file:
            transaction.on_commit(
                lambda: process_form483_excel_task.delay(
                    obj.pk,
                    baseline_path,
                    baseline_source_key,
                )
            )

@admin.register(models.WarningLetterPdf)
class WarningLetterPdfAdmin(admin.ModelAdmin):
    list_display = ("pdf_name", "created_at")
    search_fields = ("pdf_name",)

    def save_model(self, request, obj, form, change):
        obj.full_clean()  # enforce validation in admin
        super().save_model(request, obj, form, change)

@admin.register(models.WarningLetterExcelMaster)
class WarningLetterExcelMasterAdmin(admin.ModelAdmin):
    list_display = ("display_name", "uploaded_at", "is_active")

    def save_model(self, request, obj, form, change):
        baseline_path = None
        baseline_source_key = None
        file_replaced = "file" in getattr(form, "changed_data", [])

        if change and obj.pk and file_replaced:
            previous_obj = models.WarningLetterExcelMaster.objects.filter(pk=obj.pk).first()
            if previous_obj and previous_obj.is_active and previous_obj.file:
                baseline_path = previous_obj.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_obj.pk,
                    path=baseline_path,
                )
        if baseline_path is None and obj.is_active:
            previous_active = (
                models.WarningLetterExcelMaster.objects
                .filter(is_active=True)
                .exclude(pk=obj.pk)
                .first()
            )
            if previous_active and previous_active.file:
                baseline_path = previous_active.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_active.pk,
                    path=baseline_path,
                )

        super().save_model(request, obj, form, change)

        if obj.is_active and obj.file:
            transaction.on_commit(
                lambda: refresh_warning_letter_excel_cache(
                    baseline_path=baseline_path,
                    baseline_source_key=baseline_source_key,
                )
            )


@admin.register(models.Form483ExcelNewData)
class Form483ExcelNewDataAdmin(admin.ModelAdmin):
    list_display = ("company_name", "year_of_inspection", "system", "detected_at","form_483_observation")
    search_fields = ("company_name", "organization_name", "system", "reload_batch_id")
    list_filter = ("year_of_inspection", "system", "detected_at")


@admin.register(models.WarningLetterExcelNewData)
class WarningLetterExcelNewDataAdmin(admin.ModelAdmin):
    list_display = ("company_name", "letter_issue_date", "issuing_office", "detected_at")
    search_fields = ("company_name", "issuing_office", "reload_batch_id")
    list_filter = ("issuing_office", "year", "detected_at")

@admin.register(models.SystemChecklist)
class SystemChecklistAdmin(admin.ModelAdmin):
    list_display = ("system_name","version", "is_active","created_at")
    search_fields = ("system_name",)

admin.site.register(models.InvestigatorThemedKeywords)

@admin.register(models.GMPCExcelMaster)
class GMPCExcelMasterAdmin(admin.ModelAdmin):
    list_display = ("active_excel_name", "display_name", "uploaded_at", "is_active", "excel_processing_flag")
    readonly_fields = ("excel_processing_flag",)

    def save_model(self, request, obj, form, change):
        baseline_path = None
        baseline_source_key = None
        file_replaced = "file" in getattr(form, "changed_data", [])
        obj.active_excel_name = (obj.active_excel_name or "").strip() or None

        if change and obj.pk and file_replaced:
            previous_obj = models.GMPCExcelMaster.objects.filter(pk=obj.pk).first()
            if (
                previous_obj
                and previous_obj.is_active
                and previous_obj.file
                and (previous_obj.active_excel_name or "").strip() == (obj.active_excel_name or "")
            ):
                baseline_path = previous_obj.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_obj.pk,
                    path=baseline_path,
                )

        if baseline_path is None and obj.is_active and obj.active_excel_name:
            previous_active = (
                models.GMPCExcelMaster.objects
                .filter(is_active=True, active_excel_name__iexact=obj.active_excel_name)
                .exclude(pk=obj.pk)
                .order_by("-uploaded_at", "-pk")
                .first()
            )
            if previous_active and previous_active.file:
                baseline_path = previous_active.file.path
                baseline_source_key = _build_excel_source_key(
                    active_id=previous_active.pk,
                    path=baseline_path,
                )

        if obj.is_active:
            obj.excel_processing_flag = False

        super().save_model(request, obj, form, change)

        if obj.is_active and obj.file and obj.active_excel_name:
            transaction.on_commit(
                lambda: process_gmpc_excel_task.delay(
                    obj.pk,
                    obj.active_excel_name,
                    baseline_path,
                    baseline_source_key,
                )
            )

admin.site.register(models.GMPCExcelFilter)
