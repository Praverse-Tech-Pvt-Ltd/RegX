from django.apps import AppConfig


class DemoSeedConfig(AppConfig):
    """Composition root for demo/handoff setup. No models, no migrations.

    This app exists only so that `seed_regx_demo` has somewhere to live that
    is allowed to import every domain it composes. It contributes no models,
    no URLs, no API surface and no runtime behaviour -- nothing here executes
    unless a developer runs the management command by hand.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "demo_seed"
