from celery import shared_task

from .views import refresh_form483_excel_cache, refresh_gmpc_excel_cache


@shared_task
def process_form483_excel_task(master_id=None, baseline_path=None, baseline_source_key=None):
    from .models import ObservationImageExcelMaster

    print("Background Excel Processing Started")

    try:
        refresh_form483_excel_cache(
            baseline_path=baseline_path,
            baseline_source_key=baseline_source_key,
        )
    except Exception:
        if master_id:
            ObservationImageExcelMaster.objects.filter(pk=master_id).update(
                excel_processing_flag=False
            )
        raise

    if master_id:
        ObservationImageExcelMaster.objects.filter(pk=master_id).update(
            excel_processing_flag=True
        )

    print("Excel Processing Completed")


@shared_task
def process_gmpc_excel_task(
    master_id=None,
    active_excel_name=None,
    baseline_path=None,
    baseline_source_key=None,
):
    from .models import GMPCExcelMaster

    print(f"Background GMPC Excel Processing Started for {active_excel_name}")

    try:
        refresh_gmpc_excel_cache(
            country=active_excel_name,
            baseline_path=baseline_path,
            baseline_source_key=baseline_source_key,
        )
    except Exception:
        if master_id:
            GMPCExcelMaster.objects.filter(pk=master_id).update(
                excel_processing_flag=False
            )
        raise

    if master_id:
        GMPCExcelMaster.objects.filter(pk=master_id).update(
            excel_processing_flag=True
        )

    print(f"GMPC Excel Processing Completed for {active_excel_name}")
