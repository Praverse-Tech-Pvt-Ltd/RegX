from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self):
        # Installed once, after settings and LOGGING are configured, so every
        # record created during a request carries its request_id.
        from .structured_logging import install_request_id_record_factory

        install_request_id_record_factory()
