# inventario/services.py
"""
Lógica de negocio para todos los movimientos de inventario.
Todas las funciones reciben objetos ya validados y retornan el Kardex creado.
"""
from datetime import date
from django.db import transaction
from .models import Kardex


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _precio_pvp(producto):
    """Retorna el precio de venta al público o None si no está definido."""
    return getattr(producto, 'precio_pvp', None) or None


def _crear_movimiento(*, producto, tipo, subtipo, origen, cantidad,
                      fecha, nota, creado_por, pedido_ref=None):
    """
    Crea el registro Kardex y actualiza producto.cantidad en una transacción.
    No valida reglas de negocio — eso lo hace cada función pública.
    """
    with transaction.atomic():
        # Bloquear fila del producto para evitar condiciones de carrera
        from usuarios.models import Producto
        prod = Producto.objects.select_for_update().get(pk=producto.pk)

        if tipo == 'Entrada' or tipo == 'Devolucion':
            prod.cantidad += cantidad
        elif tipo in ('Salida', 'Ajuste'):
            prod.cantidad -= cantidad

        prod.save(update_fields=['cantidad'])

        movimiento = Kardex.objects.create(
            producto        = prod,
            tipo            = tipo,
            subtipo         = subtipo,
            origen          = origen,
            cantidad        = cantidad,
            stock_resultante= prod.cantidad,
            precio_unitario = _precio_pvp(prod),
            fecha           = fecha or date.today(),
            nota            = nota,
            creado_por      = creado_por,
            pedido_ref      = pedido_ref,
        )

    # Refrescar instancia del llamador
    producto.cantidad = prod.cantidad
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 1. STOCK INICIAL (al crear producto con cantidad > 0)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_stock_inicial(*, producto, creado_por='Sistema'):
    """
    Llamado desde el signal post_save cuando se crea un producto nuevo.
    No modifica producto.cantidad porque ya viene con el valor inicial.
    """
    with transaction.atomic():
        movimiento = Kardex.objects.create(
            producto        = producto,
            tipo            = 'Entrada',
            subtipo         = 'stock_inicial',
            origen          = 'automatico',
            cantidad        = producto.cantidad,
            stock_resultante= producto.cantidad,
            precio_unitario = _precio_pvp(producto),
            fecha           = date.today(),
            nota            = f'Stock inicial al crear el producto "{producto.nombre}"',
            creado_por      = creado_por,
        )
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 2. REPOSICIÓN MANUAL (botón +Stock desde Productos o Inventario)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_reposicion(*, producto, cantidad, nota='', creado_por, fecha=None):
    """
    Entrada de mercancía registrada manualmente.
    Valida que no supere el stock máximo.
    """
    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    if producto.stock_maximo and (producto.cantidad + cantidad) > producto.stock_maximo:
        raise ValueError(
            f'La entrada superaría el stock máximo ({producto.stock_maximo}). '
            f'Stock actual: {producto.cantidad}.'
        )

    subtipo = 'reposicion'
    return _crear_movimiento(
        producto  = producto,
        tipo      = 'Entrada',
        subtipo   = subtipo,
        origen    = 'manual',
        cantidad  = cantidad,
        fecha     = fecha,
        nota      = nota or f'Reposición de stock — {producto.nombre}',
        creado_por= creado_por,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. AJUSTE MANUAL (formulario de inventario — siempre entrada)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_ajuste_manual(*, producto, cantidad_raw, nota='', fecha, creado_por,
                             precio_pvp=None):
    """
    Registra una entrada manual desde el formulario del módulo Inventario.
    cantidad_raw: entero positivo (siempre es entrada en el formulario).
    precio_pvp: precio de venta al público ingresado en el formulario;
                si no se envía, se toma del producto.
    """
    if cantidad_raw <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    if producto.stock_maximo and (producto.cantidad + cantidad_raw) > producto.stock_maximo:
        raise ValueError(
            f'La entrada superaría el stock máximo ({producto.stock_maximo}). '
            f'Stock actual: {producto.cantidad}.'
        )

    with transaction.atomic():
        from usuarios.models import Producto as ProdModel
        prod = ProdModel.objects.select_for_update().get(pk=producto.pk)
        prod.cantidad += cantidad_raw

        # Actualizar precio_pvp si el usuario lo envió
        if precio_pvp is not None:
            prod.precio_pvp = precio_pvp
            prod.save(update_fields=['cantidad', 'precio_pvp'])
        else:
            prod.save(update_fields=['cantidad'])

        movimiento = Kardex.objects.create(
            producto        = prod,
            tipo            = 'Entrada',
            subtipo         = 'reposicion',
            origen          = 'manual',
            cantidad        = cantidad_raw,
            stock_resultante= prod.cantidad,
            precio_unitario = precio_pvp or _precio_pvp(prod),
            fecha           = fecha,
            nota            = nota,
            creado_por      = creado_por,
        )

    producto.cantidad = prod.cantidad
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 4. RESERVA DE PEDIDO (Pedido → Pendiente)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_reserva(*, producto, cantidad, pedido_ref, creado_por='Sistema'):
    """
    Cuando un pedido pasa a Pendiente:
    - Suma cantidad_reservada al producto (no resta stock real)
    - Registra el movimiento como trazabilidad (tipo Ajuste / subtipo reserva)
    """
    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    disponible = producto.cantidad - producto.cantidad_reservada
    if cantidad > disponible:
        raise ValueError(
            f'Stock disponible insuficiente. '
            f'Disponible: {disponible}, solicitado: {cantidad}.'
        )

    with transaction.atomic():
        from usuarios.models import Producto as ProdModel
        prod = ProdModel.objects.select_for_update().get(pk=producto.pk)
        prod.cantidad_reservada += cantidad
        prod.save(update_fields=['cantidad_reservada'])

        movimiento = Kardex.objects.create(
            producto        = prod,
            tipo            = 'Ajuste',
            subtipo         = 'reserva',
            origen          = 'automatico',
            cantidad        = cantidad,
            stock_resultante= prod.cantidad,   # stock real no cambia
            precio_unitario = _precio_pvp(prod),
            fecha           = date.today(),
            nota            = f'Reserva para pedido {pedido_ref}',
            creado_por      = creado_por,
            pedido_ref      = pedido_ref,
        )

    producto.cantidad_reservada = prod.cantidad_reservada
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 5. VENTA CONFIRMADA (Pedido → Entregado)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_venta(*, producto, cantidad, pedido_ref, creado_por='Sistema'):
    """
    Cuando un pedido pasa a Entregado:
    - Resta cantidad del stock real
    - Libera la reserva
    - Registra Kardex tipo Salida / subtipo venta
    """
    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    if producto.cantidad < cantidad:
        raise ValueError(
            f'Stock insuficiente para registrar la venta. '
            f'Stock actual: {producto.cantidad}, requerido: {cantidad}.'
        )

    with transaction.atomic():
        from usuarios.models import Producto as ProdModel
        prod = ProdModel.objects.select_for_update().get(pk=producto.pk)
        prod.cantidad -= cantidad
        # Liberar reserva (no puede quedar negativa)
        prod.cantidad_reservada = max(0, prod.cantidad_reservada - cantidad)
        prod.save(update_fields=['cantidad', 'cantidad_reservada'])

        movimiento = Kardex.objects.create(
            producto        = prod,
            tipo            = 'Salida',
            subtipo         = 'venta',
            origen          = 'automatico',
            cantidad        = cantidad,
            stock_resultante= prod.cantidad,
            precio_unitario = _precio_pvp(prod),
            fecha           = date.today(),
            nota            = f'Venta confirmada — pedido {pedido_ref}',
            creado_por      = creado_por,
            pedido_ref      = pedido_ref,
        )

    producto.cantidad = prod.cantidad
    producto.cantidad_reservada = prod.cantidad_reservada
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 6. CANCELACIÓN DE PEDIDO (Pedido → Cancelado)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_cancelacion(*, producto, cantidad, pedido_ref, creado_por='Sistema'):
    """
    Cuando un pedido pasa a Cancelado:
    - Libera la reserva (cantidad_reservada disminuye)
    - Stock real no cambia (nunca se restó al reservar)
    - Registra Kardex tipo Entrada / subtipo cancelacion (para trazabilidad)
    """
    with transaction.atomic():
        from usuarios.models import Producto as ProdModel
        prod = ProdModel.objects.select_for_update().get(pk=producto.pk)
        prod.cantidad_reservada = max(0, prod.cantidad_reservada - cantidad)
        prod.save(update_fields=['cantidad_reservada'])

        movimiento = Kardex.objects.create(
            producto        = prod,
            tipo            = 'Entrada',
            subtipo         = 'cancelacion',
            origen          = 'automatico',
            cantidad        = cantidad,
            stock_resultante= prod.cantidad,
            precio_unitario = _precio_pvp(prod),
            fecha           = date.today(),
            nota            = f'Cancelación de pedido {pedido_ref} — stock liberado',
            creado_por      = creado_por,
            pedido_ref      = pedido_ref,
        )

    producto.cantidad_reservada = prod.cantidad_reservada
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# 7. DEVOLUCIÓN (Pedido ya Entregado → Devolucion)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_devolucion(*, producto, cantidad, pedido_ref, nota='',
                          creado_por='Sistema'):
    """
    Cuando un pedido entregado se devuelve:
    - Suma cantidad al stock real
    - Registra Kardex tipo Devolucion / subtipo devolucion_cliente
    """
    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor a 0.')

    return _crear_movimiento(
        producto  = producto,
        tipo      = 'Devolucion',
        subtipo   = 'devolucion_cliente',
        origen    = 'automatico',
        cantidad  = cantidad,
        fecha     = date.today(),
        nota      = nota or f'Devolución de pedido {pedido_ref}',
        creado_por= creado_por,
        pedido_ref= pedido_ref,
    )