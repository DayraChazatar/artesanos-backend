# inventario/views.py
from datetime import date
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view

from usuarios.models import Producto
from usuarios.models import Usuario

from .models      import Pedido, DetallePedido
from .serializers import (
    PedidoSerializer,
    CrearPedidoSerializer,
    CambiarEstadoSerializer,
)   

from .models import Kardex
from .serializers import KardexSerializer
from .services import (
    registrar_ajuste_manual,
    registrar_reposicion,
    registrar_reserva,
    registrar_venta,
    registrar_cancelacion,
    registrar_devolucion,
)
from usuarios.models import Producto

# ─── Helpers de stock ─────────────────────────────────────────────────────────
 
def _reservar_stock(producto: Producto, cantidad: int):
    """Resta de disponible y suma a reservado. Lanza ValueError si no hay stock."""
    if producto.cantidad < cantidad:
        raise ValueError(
            f'Stock insuficiente para "{producto.nombre}": '
            f'disponible {producto.cantidad}, solicitado {cantidad}.'
        )
    producto.cantidad           -= cantidad
    producto.cantidad_reservada  = getattr(producto, 'cantidad_reservada', 0) + cantidad
    producto.save()
 
 
def _liberar_reserva(producto: Producto, cantidad: int):
    """Cancela la reserva: devuelve al disponible."""
    producto.cantidad           += cantidad
    producto.cantidad_reservada  = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()
 
 
def _confirmar_entrega(producto: Producto, cantidad: int):
    """Entregado: solo descuenta de reservado (ya estaba fuera del disponible)."""
    producto.cantidad_reservada = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()
 
 
def _reponer_stock(producto: Producto, cantidad: int):
    """Devolución: reingresa al stock disponible."""
    producto.cantidad += cantidad
    producto.save()
 
 
# ─── 1. Crear pedido ──────────────────────────────────────────────────────────
 
@api_view(['POST'])
def crear_pedido(request):
    """
    Body esperado:
    {
      "cliente_id": 5,
      "items": [
        { "producto_id": 12, "cantidad": 2, "precio": 45000 },
        { "producto_id": 7,  "cantidad": 1, "precio": 80000 }
      ],
      "direccion": "Calle 10 #4-20, Pasto",
      "telefono":  "3001234567"
    }
    """
    ser = CrearPedidoSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
 
    data = ser.validated_data
 
    try:
        cliente = Usuario.objects.get(pk=data['cliente_id'])
    except Usuario.DoesNotExist:
        return Response({'error': 'Cliente no encontrado'}, status=status.HTTP_404_NOT_FOUND)
 
    items = data['items']
    if not items:
        return Response({'error': 'El pedido debe tener al menos un producto'}, status=400)
 
    try:
        with transaction.atomic():
            # Obtener productos y validar stock antes de crear nada
            productos_map: dict[int, Producto] = {}
            for item in items:
                pid = item['producto_id']
                try:
                    prod = Producto.objects.select_for_update().get(pk=pid)
                except Producto.DoesNotExist:
                    raise ValueError(f'Producto {pid} no encontrado.')
                productos_map[pid] = prod
 
            # Determinar artesano desde el primer producto
            primer_prod  = productos_map[items[0]['producto_id']]
            artesano_obj = getattr(primer_prod, 'artesano', None)
 
            # Calcular total
            total = sum(item['precio'] * item['cantidad'] for item in items)
 
            # Crear cabecera del pedido
            pedido = Pedido.objects.create(
                cliente   = cliente,
                artesano  = artesano_obj,
                estado    = 'Pendiente',
                total     = total,
                direccion = data.get('direccion', ''),
                telefono  = data.get('telefono', ''),
            )
 
            # Crear detalles + reservar stock
            for item in items:
                prod = productos_map[item['producto_id']]
                _reservar_stock(prod, item['cantidad'])
                DetallePedido.objects.create(
                    pedido   = pedido,
                    producto = prod,
                    cantidad = item['cantidad'],
                    precio   = item['precio'],
                )
 
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
 
    return Response(
        PedidoSerializer(pedido, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )
 
 
# ─── 2. Listar pedidos por cliente ───────────────────────────────────────────
 
@api_view(['GET'])
def pedidos_cliente(request, cliente_id):
    """GET /api/inventario/pedidos/cliente/<cliente_id>/"""
    pedidos = Pedido.objects.filter(cliente_id=cliente_id).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)
 
 
# ─── 3. Listar pedidos por artesano ──────────────────────────────────────────
 
@api_view(['GET'])
def pedidos_artesano(request, artesano_id):
    """GET /api/inventario/pedidos/artesano/<artesano_id>/"""
    pedidos = Pedido.objects.filter(artesano_id=artesano_id).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)
 
 
# ─── 4. Cambiar estado con lógica automática de stock ────────────────────────
 
# Transiciones válidas desde cada estado
TRANSICIONES_VALIDAS: dict[str, list[str]] = {
    'Pendiente':             ['En proceso', 'Enviado', 'Cancelado'],
    'En proceso':            ['Enviado', 'Cancelado'],
    'Enviado':               ['Entregado', 'Cancelado'],
    'Entregado':             ['Devolucion solicitada', 'Devolucion'],
    'Cancelado':             [],
    'Devolucion solicitada': ['Devuelto', 'Rechazado'],
    'Devuelto':              [],
    'Rechazado':             [],
    'Devolucion':            [],
}
 
@api_view(['POST'])
def cambiar_estado(request):
    """
    Body esperado:
    {
      "pedido_id": 42,          ← o bien →
      "pedido_ref": "PED-00042",
      "estado_nuevo": "Enviado",
      "admin_response": "",     (opcional, para respuestas de devolución)
      "admin_photos": []        (opcional)
    }
    """
    ser = CambiarEstadoSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
 
    data = ser.validated_data
 
    # Resolver pedido por id o por código
    if data.get('pedido_id'):
        pedido = get_object_or_404(Pedido, pk=data['pedido_id'])
    elif data.get('pedido_ref'):
        pedido = get_object_or_404(Pedido, codigo=data['pedido_ref'])
    else:
        return Response({'error': 'Proporciona pedido_id o pedido_ref'}, status=400)
 
    estado_anterior = pedido.estado
    estado_nuevo    = data['estado_nuevo']
 
    if estado_anterior == estado_nuevo:
        return Response({'error': 'El pedido ya tiene ese estado'}, status=400)
 
    permitidos = TRANSICIONES_VALIDAS.get(estado_anterior, [])
    if estado_nuevo not in permitidos:
        return Response(
            {'error': f'Transición no permitida: {estado_anterior} → {estado_nuevo}. '
                      f'Permitidas: {permitidos}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    try:
        with transaction.atomic():
            detalles = pedido.detalles.select_related('producto').select_for_update()
 
            for detalle in detalles:
                prod     = detalle.producto
                cantidad = detalle.cantidad
 
                # ── Lógica de stock según transición ──────────────────────
                #
                # Pendiente → cualquiera excepto Cancelado: stock ya reservado,
                #   no se toca disponible de nuevo.
                #
                # * → Cancelado    : liberar reserva → suma a disponible
                # * → Entregado    : confirmar entrega → quita de reservado
                # * → Devolucion   : reponer stock → suma a disponible
                # * → Devuelto     : reponer stock (flujo cliente)
                # Los demás cambios de estado (P→En proceso, P→Enviado, etc.)
                #   no modifican stock porque la reserva ya está hecha.
 
                if estado_nuevo == 'Cancelado':
                    # Solo liberar si el pedido tenía stock reservado
                    if estado_anterior not in ('Cancelado', 'Entregado',
                                               'Devolucion', 'Devuelto'):
                        _liberar_reserva(prod, cantidad)
 
                elif estado_nuevo in ('Entregado',):
                    _confirmar_entrega(prod, cantidad)
 
                elif estado_nuevo in ('Devolucion', 'Devuelto'):
                    _reponer_stock(prod, cantidad)
 
                # Devolucion solicitada / Rechazado / En proceso / Enviado
                # → no modifican stock
 
            # Actualizar estado del pedido
            pedido.estado = estado_nuevo
            pedido.save()
 
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 
    # Stock del primer producto para que el frontend pueda actualizarlo en vivo
    primer_detalle  = pedido.detalles.select_related('producto').first()
    stock_actual    = getattr(primer_detalle.producto, 'cantidad', None) if primer_detalle else None
    stock_reservado = getattr(primer_detalle.producto, 'cantidad_reservada', None) if primer_detalle else None
 
    return Response({
        'ok':             True,
        'pedido_id':      pedido.pk,
        'codigo':         pedido.codigo,
        'estado_anterior': estado_anterior,
        'estado_nuevo':   estado_nuevo,
        'stock_actual':   stock_actual,
        'stock_reservado': stock_reservado,
    })
# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inventario/kardex/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lista_kardex(request):
    qs = Kardex.objects.select_related('producto').all()

    desde       = request.query_params.get('desde')
    hasta       = request.query_params.get('hasta')
    producto_id = request.query_params.get('producto')
    tipo        = request.query_params.get('tipo')
    origen      = request.query_params.get('origen')

    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    if producto_id:
        qs = qs.filter(producto_id=producto_id)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if origen:
        qs = qs.filter(origen=origen)

    return Response(KardexSerializer(qs, many=True).data)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inventario/kardex/
# Entrada manual desde el formulario de Inventario
# Body: { producto, cantidad, fecha, nota, precio_pvp (opcional) }
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def crear_kardex(request):
    producto_id  = request.data.get('producto')
    cantidad_raw = request.data.get('cantidad')
    fecha        = request.data.get('fecha')
    nota         = request.data.get('nota', '')
    precio_pvp   = request.data.get('precio_pvp')   # ← NUEVO campo

    if not producto_id or cantidad_raw is None or not fecha:
        return Response(
            {'error': 'producto, cantidad y fecha son obligatorios.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad_raw = int(cantidad_raw)
    except (TypeError, ValueError):
        return Response(
            {'error': 'La cantidad debe ser un número entero.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if cantidad_raw <= 0:
        return Response(
            {'error': 'La cantidad debe ser mayor a 0.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Convertir precio_pvp si viene
    if precio_pvp is not None:
        try:
            precio_pvp = float(precio_pvp)
            if precio_pvp < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return Response(
                {'error': 'El precio de venta al público debe ser un número positivo.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    producto   = get_object_or_404(Producto, pk=producto_id)
    creado_por = request.user.get_full_name() or request.user.username

    try:
        movimiento = registrar_ajuste_manual(
            producto    = producto,
            cantidad_raw= cantidad_raw,
            nota        = nota,
            fecha       = fecha,
            creado_por  = creado_por,
            precio_pvp  = precio_pvp,   # ← NUEVO
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(KardexSerializer(movimiento).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inventario/reposicion/
# Botón +Stock desde tabla de Productos
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reposicion_stock(request):
    producto_id = request.data.get('producto')
    cantidad    = request.data.get('cantidad')
    nota        = request.data.get('nota', '')

    if not producto_id or not cantidad:
        return Response(
            {'error': 'producto y cantidad son obligatorios.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return Response(
            {'error': 'La cantidad debe ser un número entero mayor que 0.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    producto   = get_object_or_404(Producto, pk=producto_id)
    creado_por = request.user.get_full_name() or request.user.username

    try:
        movimiento = registrar_reposicion(
            producto   = producto,
            cantidad   = cantidad,
            nota       = nota,
            creado_por = creado_por,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            **KardexSerializer(movimiento).data,
            'stock_resultante': movimiento.stock_resultante,
        },
        status=status.HTTP_201_CREATED
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inventario/pedido/estado/
# Cambia el estado de un pedido y ejecuta la lógica de inventario automática
#
# Body: {
#   "pedido_ref": "PED-0001",
#   "producto_id": 1,
#   "cantidad": 2,
#   "estado_anterior": "Pendiente",
#   "estado_nuevo": "Entregado",
#   "nota": ""          (opcional)
# }
#
# Transiciones soportadas:
#   (nuevo)      → Pendiente  : reserva
#   Pendiente    → Entregado  : venta (resta stock real, libera reserva)
#   Pendiente    → Cancelado  : cancelacion (libera reserva)
#   Entregado    → Devolucion : devolucion (suma al stock)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_estado_pedido(request):
    pedido_ref      = request.data.get('pedido_ref')
    producto_id     = request.data.get('producto_id')
    cantidad        = request.data.get('cantidad')
    estado_anterior = request.data.get('estado_anterior', '')
    estado_nuevo    = request.data.get('estado_nuevo')
    nota            = request.data.get('nota', '')

    if not all([pedido_ref, producto_id, cantidad, estado_nuevo]):
        return Response(
            {'error': 'pedido_ref, producto_id, cantidad y estado_nuevo son obligatorios.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return Response(
            {'error': 'La cantidad debe ser un entero mayor a 0.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    producto   = get_object_or_404(Producto, pk=producto_id)
    creado_por = request.user.get_full_name() or request.user.username

    movimiento = None

    try:
        # ── Crear pedido → Pendiente (reserva) ──────────────────────────
        if estado_nuevo == 'Pendiente' and estado_anterior in ('', None):
            movimiento = registrar_reserva(
                producto   = producto,
                cantidad   = cantidad,
                pedido_ref = pedido_ref,
                creado_por = creado_por,
            )

        # ── Pendiente → Entregado (venta real) ──────────────────────────
        elif estado_anterior == 'Pendiente' and estado_nuevo == 'Entregado':
            movimiento = registrar_venta(
                producto   = producto,
                cantidad   = cantidad,
                pedido_ref = pedido_ref,
                creado_por = creado_por,
            )

        # ── Pendiente → Cancelado (liberar reserva) ─────────────────────
        elif estado_anterior == 'Pendiente' and estado_nuevo == 'Cancelado':
            movimiento = registrar_cancelacion(
                producto   = producto,
                cantidad   = cantidad,
                pedido_ref = pedido_ref,
                creado_por = creado_por,
            )

        # ── Entregado → Devolucion ───────────────────────────────────────
        elif estado_anterior == 'Entregado' and estado_nuevo == 'Devolucion':
            movimiento = registrar_devolucion(
                producto   = producto,
                cantidad   = cantidad,
                pedido_ref = pedido_ref,
                nota       = nota,
                creado_por = creado_por,
            )

        else:
            # Transición no relevante para inventario (ej: Enviado)
            return Response({
                'mensaje': f'Transición {estado_anterior} → {estado_nuevo} no afecta el inventario.',
                'stock_actual':      producto.cantidad,
                'stock_reservado':   producto.cantidad_reservada,
                'stock_disponible':  producto.cantidad - producto.cantidad_reservada,
            })

    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'movimiento':       KardexSerializer(movimiento).data,
        'stock_actual':     producto.cantidad,
        'stock_reservado':  producto.cantidad_reservada,
        'stock_disponible': producto.cantidad - producto.cantidad_reservada,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inventario/resumen/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def resumen_inventario(request):
    kardex = Kardex.objects.all()

    total_entradas = sum(
        k.cantidad for k in kardex
        if k.tipo in ('Entrada', 'Devolucion')
        and k.subtipo not in ('cancelacion',)   # cancelacion no es entrada real
    )
    total_salidas = sum(
        k.cantidad for k in kardex
        if k.tipo in ('Salida',)
    )
    valor_movido = sum(
        (k.precio_unitario or 0) * k.cantidad
        for k in kardex
        if k.tipo in ('Entrada', 'Devolucion', 'Salida')
        and k.subtipo not in ('reserva', 'cancelacion')
    )

    return Response({
        'total_entradas':    total_entradas,
        'total_salidas':     total_salidas,
        'balance_neto':      total_entradas - total_salidas,
        'total_movimientos': kardex.count(),
        'valor_movido':      float(valor_movido),
    })