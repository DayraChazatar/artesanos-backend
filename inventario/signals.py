# inventario/signals.py
"""
Signal que escucha cuando se crea un Producto nuevo y registra
automáticamente el stock inicial en Kardex.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

# IMPORTANTE: ajusta este import al app_label correcto de tu modelo Producto
from usuarios.models import Producto
from .services import registrar_stock_inicial


@receiver(post_save, sender=Producto)
def producto_creado_stock_inicial(sender, instance, created, **kwargs):
    """
    Se ejecuta automáticamente cada vez que se guarda un Producto.
    Solo actúa cuando el producto es nuevo (created=True) y tiene cantidad > 0.
    """
    if created and instance.cantidad > 0:
        registrar_stock_inicial(
            producto   = instance,
            creado_por = 'Sistema',   # no hay request aquí, es automático
        )
