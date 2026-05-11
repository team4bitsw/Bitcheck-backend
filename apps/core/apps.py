from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    label = 'core'
    verbose_name = 'Core'

    def ready(self) -> None:
        from apps.core.logger import configure_root_bitcheck_logging

        configure_root_bitcheck_logging()
