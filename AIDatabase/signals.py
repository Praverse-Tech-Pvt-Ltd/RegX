from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ObservationImageExcelMaster
from .tasks import process_form483_excel_task


@receiver(post_save, sender=ObservationImageExcelMaster)
def trigger_excel_processing(sender, instance, created, **kwargs):
    if getattr(instance, "_skip_post_save_task", False):
        return
    if instance.is_active:
        ObservationImageExcelMaster.objects.filter(pk=instance.pk).update(
            excel_processing_flag=False
        )
        print("[SIGNAL] Excel uploaded -> triggering Celery task")
        process_form483_excel_task.delay(instance.pk)
