from celery import shared_task


@shared_task
def send_demo_reminders_task():
    """Celery wrapper around `manage.py send_demo_reminders` — scheduled via
    CELERY_BEAT_SCHEDULE in settings.py. Safe to also run the management
    command manually/via cron; RATools.DemoRequest.reminder_sent prevents
    double-sends either way."""
    from django.core.management import call_command
    call_command("send_demo_reminders")
