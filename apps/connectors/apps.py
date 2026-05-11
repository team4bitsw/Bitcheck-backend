from django.apps import AppConfig


class ConnectorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.connectors'
    label = 'connectors'

    def ready(self) -> None:
        import apps.connectors.signals  # noqa: F401
        from apps.connectors.adapters import echo  # noqa: F401
