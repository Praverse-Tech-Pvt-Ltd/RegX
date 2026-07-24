from django.apps import AppConfig


class FdaDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fda_data"
    verbose_name = "FDA Source Data Governance"
