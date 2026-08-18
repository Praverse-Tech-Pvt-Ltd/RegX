import os

from celery import Celery
from celery.signals import setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "regx.settings.development")

app = Celery("regx")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@setup_logging.connect
def configure_logging(**_kwargs):
    """Make the worker use Django's LOGGING instead of Celery's own handlers.

    worker_hijack_root_logger=False alone is not enough: the worker still
    installs its own text handler on the `celery` logger, so worker output would
    stay unstructured and -- more to the point -- would bypass the allow-list
    formatter that keeps task arguments out of the log. Connecting this signal
    disables Celery's logging setup entirely.
    """
    from logging.config import dictConfig

    from django.conf import settings

    dictConfig(settings.LOGGING)
