from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"

    def ready(self):
        from .cache import connect_signals

        connect_signals()
