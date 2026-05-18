# inventario/apps.py
from django.apps import AppConfig


class InventarioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventario'
    verbose_name = 'Inventario'

    def ready(self):
        # Conecta los signals al iniciar Django
        import inventario.signals  # noqa: F401
