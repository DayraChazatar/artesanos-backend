# inventario/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from usuarios.models import Producto
from .services import registrar_stock_inicial


# ── Signal existente (no tocar) ──────────────────────────────────────────────
@receiver(post_save, sender=Producto)
def producto_creado_stock_inicial(sender, instance, created, **kwargs):
    if created and instance.cantidad > 0:
        registrar_stock_inicial(
            producto   = instance,
            creado_por = 'Sistema',
        )

# Existió aquí una señal que también "restauraba" stock al cancelar un
# pedido — se quitó porque duplicaba (con un error) lo que ya hace
# registrar_cancelacion() en services.py: esa señal sumaba la cantidad
# reservada al stock REAL (producto.cantidad) cada vez que un pedido pasaba
# a Cancelado, cuando esa cantidad nunca se había restado del stock real al
# reservarla — el resultado era inventario inflado con cada cancelación.