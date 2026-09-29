from django.apps import AppConfig


class PrintingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.printing'
    verbose_name = 'Impresión local'

    def ready(self):
        from . import signals  # noqa: F401
