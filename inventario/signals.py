# inventario/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from datetime import date

from usuarios.models import Producto
from .services import registrar_stock_inicial
from .models import Pedido, Kardex


# ── Signal existente (no tocar) ──────────────────────────────────────────────
@receiver(post_save, sender=Producto)
def producto_creado_stock_inicial(sender, instance, created, **kwargs):
    if created and instance.cantidad > 0:
        registrar_stock_inicial(
            producto   = instance,
            creado_por = 'Sistema',
        )


# ── Signal NUEVO: restaurar stock al cancelar pedido ─────────────────────────
@receiver(pre_save, sender=Pedido)
def restaurar_stock_al_cancelar(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        pedido_anterior = Pedido.objects.get(pk=instance.pk)
    except Pedido.DoesNotExist:
        return

    if pedido_anterior.estado != 'Cancelado' and instance.estado == 'Cancelado':

        ya_registrado = Kardex.objects.filter(
            pedido_ref=instance.codigo,
            subtipo='cancelacion'
        ).exists()

        if ya_registrado:
            return  # ya se procesó, salir

        for detalle in instance.detalles.all():
            producto = detalle.producto
            producto.cantidad += detalle.cantidad
            producto.save()

            Kardex.objects.create(
                producto         = producto,
                tipo             = 'Entrada',
                subtipo          = 'cancelacion',
                origen           = 'automatico',
                cantidad         = detalle.cantidad,
                stock_resultante = producto.cantidad,
                pedido_ref       = instance.codigo,
                fecha            = date.today(),
                nota             = f'Cancelación de pedido {instance.codigo} — stock liberado',
                creado_por       = 'Sistema',
            )