from django.apps import AppConfig


class AidatabaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "AIDatabase"
    def ready(self):
        import AIDatabase.signals