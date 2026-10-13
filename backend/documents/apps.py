import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    verbose_name = "Documents"

    def ready(self):
        from . import signals  # noqa: F401

        # Once per process (web and celery alike), so a stub scanner is visible
        # at startup and not only in per-upload log lines. Production refuses
        # to start with the stub unless DOCUMENT_SCANNER_ALLOW_STUB is set (see
        # regx/settings/production.py); this makes the escape hatch loud.
        if settings.DOCUMENT_SCANNER_BACKEND == "stub":
            logger.warning(
                "Malware scanning is DISABLED: DOCUMENT_SCANNER_BACKEND=stub marks every "
                "upload CLEAN without scanning it (DOCUMENT_SCANNER_ALLOW_STUB=%s). "
                "Set DOCUMENT_SCANNER_BACKEND=clamav before accepting real uploads.",
                getattr(settings, "DOCUMENT_SCANNER_ALLOW_STUB", False),
            )
