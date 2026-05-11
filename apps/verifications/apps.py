from django.apps import AppConfig


class VerificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.verifications'
    label = 'verifications'
    verbose_name = 'Verifications'

    def ready(self) -> None:
        import apps.verifications.signals  # noqa: F401
